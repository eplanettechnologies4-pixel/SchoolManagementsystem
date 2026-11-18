import io
import math
import datetime
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm

from staff.models import (
    Staff, StaffAttendance, ShiftTiming, AttendanceStatusChoices,
    AttendanceMethodChoices, LeaveRequest, LeaveStatusChoices
)
from accounts.models import User, RoleChoices
from accounts.services import log_audit


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes distance in meters between two latitude/longitude points
    using the Haversine formula.
    """
    R = 6371000  # Radius of earth in meters
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@transaction.atomic
def generate_employee_id_atomic(school=None, year=None) -> str:
    """
    Race-condition safe sequential Employee ID e.g. EMP-2026-0001
    """
    if not year:
        year = datetime.datetime.now().year
    prefix = f"EMP-{year}-"

    qs = Staff.objects.select_for_update().filter(employee_id__startswith=prefix)
    if school:
        qs = qs.filter(school=school)

    last_staff = qs.order_by('-employee_id').first()
    if last_staff:
        try:
            last_seq = int(last_staff.employee_id.split('-')[-1])
            new_seq = last_seq + 1
        except (ValueError, IndexError):
            new_seq = 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:04d}"


def record_staff_check_in(staff: Staff, lat=None, lng=None, method='GPS', marked_by=None, now_dt=None):
    """
    Processes check-in: computes geofence distance, checks shift timing + grace period,
    flags out-of-range if applicable, and saves StaffAttendance.
    """
    if not now_dt:
        now_dt = timezone.localtime(timezone.now())

    today = now_dt.date()
    current_time = now_dt.time()

    # Determine status by shift
    shift = staff.shift
    if not shift and staff.school:
        shift = ShiftTiming.objects.filter(school=staff.school, is_active=True).first()

    status = AttendanceStatusChoices.PRESENT
    if shift:
        grace_limit = datetime.datetime.combine(today, shift.start_time) + datetime.timedelta(minutes=shift.grace_minutes)
        if now_dt > timezone.make_aware(grace_limit) if timezone.is_aware(now_dt) else (now_dt > grace_limit):
            status = AttendanceStatusChoices.LATE

    # Geofence check
    distance_meters = None
    is_out_of_range = False
    school = staff.school
    if lat is not None and lng is not None and school and school.latitude and school.longitude:
        distance_meters = haversine_distance_meters(school.latitude, school.longitude, lat, lng)
        if distance_meters > school.radius_meters:
            is_out_of_range = True

    attendance, created = StaffAttendance.objects.get_or_create(
        staff=staff,
        date=today,
        defaults={
            'school': staff.school,
            'check_in': current_time,
            'status': status,
            'method': method,
            'location_lat': lat,
            'location_lng': lng,
            'distance_meters': distance_meters,
            'is_out_of_range': is_out_of_range,
            'marked_by': marked_by or staff.user
        }
    )

    if not created and not attendance.check_in:
        attendance.check_in = current_time
        attendance.status = status
        attendance.location_lat = lat
        attendance.location_lng = lng
        attendance.distance_meters = distance_meters
        attendance.is_out_of_range = is_out_of_range
        attendance.save()

    return attendance, created, is_out_of_range


def record_staff_check_out(staff: Staff, now_dt=None):
    """
    Records staff check-out time.
    """
    if not now_dt:
        now_dt = timezone.localtime(timezone.now())

    today = now_dt.date()
    attendance = StaffAttendance.objects.filter(staff=staff, date=today).first()
    if not attendance:
        # Check-out without check-in creates attendance record
        attendance = StaffAttendance.objects.create(
            staff=staff,
            school=staff.school,
            date=today,
            check_out=now_dt.time(),
            status=AttendanceStatusChoices.PRESENT,
            method=AttendanceMethodChoices.GPS,
            marked_by=staff.user
        )
    else:
        attendance.check_out = now_dt.time()
        attendance.save()

    return attendance


def get_staff_tracking_today(school=None, date=None):
    """
    Gathers today's staff live tracking metrics and geolocation records.
    """
    if not date:
        date = datetime.date.today()

    staff_qs = Staff.objects.filter(status='ACTIVE')
    att_qs = StaffAttendance.objects.filter(date=date)
    if school:
        staff_qs = staff_qs.filter(school=school)
        att_qs = att_qs.filter(school=school)

    total_staff = staff_qs.count()
    attendances = att_qs.select_related('staff__user')

    present_count = attendances.filter(status=AttendanceStatusChoices.PRESENT).count()
    late_count = attendances.filter(status=AttendanceStatusChoices.LATE).count()
    leave_count = attendances.filter(status=AttendanceStatusChoices.LEAVE).count()
    absent_count = attendances.filter(status=AttendanceStatusChoices.ABSENT).count()
    
    # Staff not yet marked
    marked_staff_ids = attendances.values_list('staff_id', flat=True)
    unmarked_count = total_staff - attendances.count()

    locations = []
    for att in attendances:
        if att.location_lat and att.location_lng:
            locations.append({
                'name': att.staff.get_full_name(),
                'emp_id': att.staff.employee_id,
                'lat': float(att.location_lat),
                'lng': float(att.location_lng),
                'status': att.status,
                'check_in': att.check_in.strftime('%H:%M') if att.check_in else '',
                'is_out_of_range': att.is_out_of_range,
                'distance': round(att.distance_meters, 1) if att.distance_meters else 0
            })

    return {
        'date': date,
        'total_staff': total_staff,
        'present_count': present_count,
        'late_count': late_count,
        'leave_count': leave_count,
        'absent_count': absent_count,
        'unmarked_count': max(0, unmarked_count),
        'attendances': attendances,
        'locations': locations,
    }


def export_staff_attendance_pdf(school, month=None, year=None) -> bytes:
    """
    Generates a monthly staff attendance sheet PDF using ReportLab in landscape orientation.
    """
    if not month:
        month = datetime.date.today().month
    if not year:
        year = datetime.date.today().year

    start_date = datetime.date(year, month, 1)
    # End date calculation
    if month == 12:
        end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    staff_members = Staff.objects.filter(school=school, status='ACTIVE').order_by('employee_id')
    attendances = StaffAttendance.objects.filter(
        school=school,
        date__gte=start_date,
        date__lte=end_date
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('RepTitle', fontName='Helvetica-Bold', fontSize=14, leading=16, textColor=colors.HexColor('#1e3a8a'))
    body_style = ParagraphStyle('RepBody', fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor('#334155'))
    bold_style = ParagraphStyle('RepBold', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#0f172a'))

    story = []
    story.append(Paragraph(f"<b>{(school.name if school else 'SCHOOL').upper()}</b> — MONTHLY STAFF ATTENDANCE REPORT", title_style))
    story.append(Paragraph(f"Period: {start_date.strftime('%B %Y')} &nbsp;&nbsp;|&nbsp;&nbsp; Generated on: {datetime.date.today().strftime('%d-%b-%Y')}", body_style))
    story.append(Spacer(1, 5 * mm))

    # Table headers
    headers = [
        Paragraph("<b>Emp ID</b>", bold_style),
        Paragraph("<b>Staff Name</b>", bold_style),
        Paragraph("<b>Designation</b>", bold_style),
        Paragraph("<b>Present</b>", bold_style),
        Paragraph("<b>Late</b>", bold_style),
        Paragraph("<b>Leave</b>", bold_style),
        Paragraph("<b>Absent</b>", bold_style),
        Paragraph("<b>Attendance %</b>", bold_style),
    ]
    table_data = [headers]

    for st in staff_members:
        st_atts = attendances.filter(staff=st)
        pres = st_atts.filter(status=AttendanceStatusChoices.PRESENT).count()
        late = st_atts.filter(status=AttendanceStatusChoices.LATE).count()
        leave = st_atts.filter(status=AttendanceStatusChoices.LEAVE).count()
        absent = st_atts.filter(status=AttendanceStatusChoices.ABSENT).count()
        total_days = end_date.day
        eff_present = pres + late
        pct = round((eff_present / total_days * 100), 1) if total_days else 0

        table_data.append([
            Paragraph(st.employee_id, body_style),
            Paragraph(st.get_full_name(), bold_style),
            Paragraph(st.designation, body_style),
            Paragraph(str(pres), body_style),
            Paragraph(str(late), body_style),
            Paragraph(str(leave), body_style),
            Paragraph(str(absent), body_style),
            Paragraph(f"{pct}%", bold_style),
        ])

    col_widths = [28 * mm, 50 * mm, 45 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 28 * mm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def export_staff_attendance_excel(school, month=None, year=None) -> io.BytesIO:
    """
    Generates a monthly staff attendance report spreadsheet (.xlsx) using openpyxl.
    """
    if not month:
        month = datetime.date.today().month
    if not year:
        year = datetime.date.today().year

    start_date = datetime.date(year, month, 1)
    if month == 12:
        end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    staff_members = Staff.objects.filter(school=school, status='ACTIVE').order_by('employee_id')
    attendances = StaffAttendance.objects.filter(
        school=school,
        date__gte=start_date,
        date__lte=end_date
    )

    wb = Workbook()
    ws = wb.active
    ws.title = f"Attendance {month}-{year}"

    # Header styling
    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    ws.merge_cells('A1:H1')
    ws['A1'] = f"{(school.name if school else 'SCHOOL').upper()} — STAFF ATTENDANCE REPORT ({start_date.strftime('%B %Y')})"
    ws['A1'].font = Font(name="Calibri", size=13, bold=True, color="1E3A8A")
    ws['A1'].alignment = Alignment(horizontal="center")

    headers = ["Employee ID", "Full Name", "Designation", "Present Days", "Late Days", "Leave Days", "Absent Days", "Attendance %"]
    ws.append([])
    ws.append(headers)

    for col_idx in range(1, 9):
        cell = ws.cell(row=3, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    row_num = 4
    for st in staff_members:
        st_atts = attendances.filter(staff=st)
        pres = st_atts.filter(status=AttendanceStatusChoices.PRESENT).count()
        late = st_atts.filter(status=AttendanceStatusChoices.LATE).count()
        leave = st_atts.filter(status=AttendanceStatusChoices.LEAVE).count()
        absent = st_atts.filter(status=AttendanceStatusChoices.ABSENT).count()
        total_days = end_date.day
        eff_present = pres + late
        pct = round((eff_present / total_days * 100), 1) if total_days else 0

        ws.append([
            st.employee_id,
            st.get_full_name(),
            st.designation,
            pres,
            late,
            leave,
            absent,
            f"{pct}%"
        ])
        row_num += 1

    # Adjust column widths safely handling merged header cells
    for col_idx, col in enumerate(ws.columns, start=1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or '')
            # Ignore row 1 merged title to avoid extreme column widths
            if cell.row != 1 and len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 13)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output

