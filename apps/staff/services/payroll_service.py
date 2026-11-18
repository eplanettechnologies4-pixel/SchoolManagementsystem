import io
import datetime
import calendar
import qrcode
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, Q

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm

from staff.models import (
    Staff, StaffAttendance, LeaveRequest, LeaveType, SalarySlip,
    AttendanceStatusChoices, LeaveStatusChoices, LateDeductionPolicyChoices,
    SalarySlipStatusChoices, SalaryPaymentMethodChoices, StaffStatusChoices
)
from accounts.services import log_audit


@transaction.atomic
def generate_salary_slip_number(year: int = None, month: int = None) -> str:
    """
    Race-condition safe sequential generation of Salary Slip Number e.g. PAY-202611-0001
    using transaction.atomic and select_for_update.
    """
    if not year:
        year = datetime.date.today().year
    if not month:
        month = datetime.date.today().month

    prefix = f"PAY-{year}{month:02d}-"
    last_slip = (
        SalarySlip.all_objects.select_for_update()
        .filter(slip_number__startswith=prefix)
        .order_by('-id')
        .first()
    )

    if last_slip and last_slip.slip_number:
        try:
            last_seq = int(last_slip.slip_number.split('-')[-1])
            new_seq = last_seq + 1
        except (ValueError, IndexError):
            new_seq = SalarySlip.all_objects.count() + 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:04d}"


def calculate_staff_monthly_salary(
    staff: Staff,
    month: int,
    year: int,
    bonus: Decimal = Decimal('0.00'),
    tax_deduction: Decimal = Decimal('0.00'),
    other_deductions: Decimal = Decimal('0.00'),
    unpaid_leave_override: int = None,
    generated_by=None,
    remarks: str = None
) -> SalarySlip:
    """
    Calculates and persists or updates the monthly SalarySlip for a staff member.
    Enforces salary deductions:
      1. Absent days: (basic_salary / total_days) * absent_days
      2. Half days: (basic_salary / total_days / 2) * half_days
      3. Late arrivals: based on staff.late_deduction_policy (e.g. 3 lates = 1 day cut, 2 lates = half day cut)
      4. Unpaid leaves: approved leaves exceeding annual quota + unapproved leave attendances
      5. Taxes and other deductions
    """
    _, total_calendar_days = calendar.monthrange(year, month)
    total_days = total_calendar_days

    start_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, total_days)

    # Attendance logs for the month
    month_attendances = StaffAttendance.objects.filter(
        staff=staff,
        date__range=(start_date, end_date)
    )

    present_count = month_attendances.filter(status=AttendanceStatusChoices.PRESENT).count()
    late_count = month_attendances.filter(status=AttendanceStatusChoices.LATE).count()
    half_day_count = month_attendances.filter(status=AttendanceStatusChoices.HALF_DAY).count()
    leave_att_count = month_attendances.filter(status=AttendanceStatusChoices.LEAVE).count()
    absent_count = month_attendances.filter(status=AttendanceStatusChoices.ABSENT).count()

    # Leave quota analysis
    if unpaid_leave_override is not None:
        unpaid_leave_days = int(unpaid_leave_override)
        total_leave_days = leave_att_count or unpaid_leave_days
    else:
        # Sum of allowed leave quota for school
        allowed_quota_types = LeaveType.objects.filter(school=staff.school, is_active=True)
        total_annual_quota = sum(lt.days_per_year for lt in allowed_quota_types)
        if total_annual_quota <= 0:
            total_annual_quota = 12

        # Approved leaves this year
        approved_year_requests = LeaveRequest.objects.filter(
            staff=staff,
            status=LeaveStatusChoices.APPROVED,
            from_date__year=year
        )

        # Approved leaves before this month
        prior_requests = approved_year_requests.filter(to_date__lt=start_date)
        prior_taken_days = sum(r.total_days for r in prior_requests)
        remaining_quota = max(0, total_annual_quota - prior_taken_days)

        # Dates covered by approved requests during this month
        approved_dates_in_month = set()
        for req in approved_year_requests.filter(from_date__lte=end_date, to_date__gte=start_date):
            c_date = max(req.from_date, start_date)
            max_d = min(req.to_date, end_date)
            while c_date <= max_d:
                approved_dates_in_month.add(c_date)
                c_date += datetime.timedelta(days=1)

        approved_month_count = len(approved_dates_in_month)
        leave_att_dates = set(month_attendances.filter(status=AttendanceStatusChoices.LEAVE).values_list('date', flat=True))
        
        # If staff attended status is LEAVE but no approved leave request exists
        unapproved_leave_days = len(leave_att_dates - approved_dates_in_month)
        
        # Excess days beyond annual quota taken this month
        excess_approved = max(0, approved_month_count - remaining_quota)
        
        unpaid_leave_days = unapproved_leave_days + excess_approved
        total_leave_days = max(leave_att_count, approved_month_count)

    # Base financial figures
    basic_salary = Decimal(str(staff.basic_salary or '0.00'))
    allowances = Decimal(str(staff.allowances or '0.00'))
    bonus = Decimal(str(bonus or '0.00'))
    gross_salary = basic_salary + allowances + bonus

    # Per-day rate calculated on calendar days
    per_day_rate = (basic_salary / Decimal(str(total_days))) if total_days > 0 else Decimal('0.00')

    # Absent cut
    absent_deduction = round(Decimal(absent_count) * per_day_rate, 2)

    # Half day cut (half of per_day_rate per half-day)
    half_day_deduction = round(Decimal(half_day_count) * (per_day_rate / Decimal('2.00')), 2)

    # Late arrival deduction
    policy = staff.late_deduction_policy
    if policy == LateDeductionPolicyChoices.EVERY_3_LATES_1_DAY:
        cut_units = late_count // 3
        late_deduction = round(Decimal(cut_units) * per_day_rate, 2)
    elif policy == LateDeductionPolicyChoices.HALF_DAY_PER_2_LATES:
        cut_units = late_count // 2
        late_deduction = round(Decimal(cut_units) * (per_day_rate / Decimal('2.00')), 2)
    else:
        late_deduction = Decimal('0.00')

    # Leave cut
    leave_deduction = round(Decimal(unpaid_leave_days) * per_day_rate, 2)

    tax_deduction = Decimal(str(tax_deduction or '0.00'))
    other_deductions = Decimal(str(other_deductions or '0.00'))

    total_deductions = (
        absent_deduction +
        half_day_deduction +
        late_deduction +
        leave_deduction +
        tax_deduction +
        other_deductions
    )

    net_salary = max(Decimal('0.00'), gross_salary - total_deductions)

    # Upsert SalarySlip
    slip = SalarySlip.objects.filter(staff=staff, month=month, year=year).first()
    if not slip:
        slip_number = generate_salary_slip_number(year=year, month=month)
        slip = SalarySlip(
            school=staff.school,
            staff=staff,
            slip_number=slip_number,
            month=month,
            year=year
        )

    slip.total_days = total_days
    slip.present_days = present_count
    slip.absent_days = absent_count
    slip.leave_days = total_leave_days
    slip.unpaid_leave_days = unpaid_leave_days
    slip.late_count = late_count
    slip.half_day_count = half_day_count

    slip.basic_salary = basic_salary
    slip.allowances = allowances
    slip.bonus = bonus
    slip.gross_salary = gross_salary

    slip.absent_deduction = absent_deduction + half_day_deduction  # incorporate half days
    slip.leave_deduction = leave_deduction
    slip.late_deduction = late_deduction
    slip.tax_deduction = tax_deduction
    slip.other_deductions = other_deductions
    slip.total_deductions = total_deductions

    slip.net_salary = net_salary
    if remarks:
        slip.remarks = remarks
    slip.save()

    log_audit(
        user=generated_by,
        action="UPDATE" if slip.pk else "CREATE",
        instance=slip,
        changes={
            'slip_number': slip.slip_number,
            'staff': staff.employee_id,
            'month_year': f"{month}/{year}",
            'gross': str(gross_salary),
            'deductions': str(total_deductions),
            'net': str(net_salary),
        },
        school=staff.school
    )

    return slip


def generate_bulk_payroll(school, month: int, year: int, generated_by=None) -> list[SalarySlip]:
    """
    Executes automated monthly payroll run for all active staff members in the school.
    """
    active_staff = Staff.objects.filter(
        school=school,
        status=StaffStatusChoices.ACTIVE
    ).select_related('user', 'shift')

    slips = []
    for member in active_staff:
        slip = calculate_staff_monthly_salary(
            staff=member,
            month=month,
            year=year,
            generated_by=generated_by
        )
        slips.append(slip)
    return slips


def mark_salary_slip_paid(
    slip: SalarySlip,
    payment_method: str = SalaryPaymentMethodChoices.BANK_TRANSFER,
    transaction_reference: str = None,
    disbursed_by=None,
    remarks: str = None
) -> SalarySlip:
    """
    Marks a salary slip as PAID and records disbursement audit log.
    """
    slip.status = SalarySlipStatusChoices.PAID
    slip.payment_date = datetime.date.today()
    slip.payment_method = payment_method
    slip.transaction_reference = transaction_reference or f"TXN-{int(timezone.now().timestamp())}"
    slip.disbursed_by = disbursed_by
    if remarks:
        slip.remarks = remarks
    slip.save()

    log_audit(
        user=disbursed_by,
        action="UPDATE",
        instance=slip,
        changes={
            'status': SalarySlipStatusChoices.PAID,
            'payment_method': payment_method,
            'ref': slip.transaction_reference,
            'net_salary': str(slip.net_salary)
        },
        school=slip.school
    )
    return slip


def generate_payslip_pdf(salary_slip: SalarySlip) -> bytes:
    """
    Generates a formal, printable Salary Slip PDF using ReportLab with:
      - School branding & Employee Details
      - Attendance metrics breakdown
      - Side-by-side Earnings & Deductions table
      - Net Payable highlight box
      - Verification QR Code & Authorization signatures
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )

    styles = getSampleStyleSheet()

    primary_color = colors.HexColor("#1e40af")      # Deep primary blue
    secondary_color = colors.HexColor("#2563eb")    # Bright blue
    dark_gray = colors.HexColor("#1f2937")
    light_gray = colors.HexColor("#f8fafc")
    border_gray = colors.HexColor("#e2e8f0")
    danger_color = colors.HexColor("#dc2626")
    success_color = colors.HexColor("#16a34a")

    title_style = ParagraphStyle(
        'PayslipTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=primary_color,
        alignment=1
    )
    sub_title_style = ParagraphStyle(
        'PayslipSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=14,
        textColor=dark_gray,
        alignment=1
    )
    label_style = ParagraphStyle(
        'LabelStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=dark_gray
    )
    val_style = ParagraphStyle(
        'ValStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=dark_gray
    )
    tbl_header_style = ParagraphStyle(
        'TblHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.white
    )
    badge_style = ParagraphStyle(
        'BadgeStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=success_color if salary_slip.status == SalarySlipStatusChoices.PAID else primary_color,
        alignment=2
    )

    month_name = calendar.month_name[salary_slip.month]
    school_name = salary_slip.school.name if salary_slip.school else "E-Planet Educational Portal"

    # Header Section
    story = [
        Paragraph(school_name.upper(), title_style),
        Paragraph(f"MONTHLY SALARY SLIP - {month_name.upper()} {salary_slip.year}", sub_title_style),
        Spacer(1, 4 * mm),
        HRFlowable(width="100%", thickness=1.5, color=primary_color, spaceAfter=12),
    ]

    # Meta Info (Staff Details + Slip Meta)
    info_data = [
        [
            Paragraph("<b>Slip Number:</b>", label_style),
            Paragraph(salary_slip.slip_number, val_style),
            Paragraph("<b>Date of Issue:</b>", label_style),
            Paragraph(salary_slip.created_at.strftime('%d-%b-%Y') if salary_slip.created_at else datetime.date.today().strftime('%d-%b-%Y'), val_style),
        ],
        [
            Paragraph("<b>Employee Name:</b>", label_style),
            Paragraph(salary_slip.staff.get_full_name(), val_style),
            Paragraph("<b>Employee ID:</b>", label_style),
            Paragraph(salary_slip.staff.employee_id, val_style),
        ],
        [
            Paragraph("<b>Designation:</b>", label_style),
            Paragraph(salary_slip.staff.designation or "Faculty", val_style),
            Paragraph("<b>Department:</b>", label_style),
            Paragraph(salary_slip.staff.department or "Academics", val_style),
        ],
        [
            Paragraph("<b>Bank Name:</b>", label_style),
            Paragraph(salary_slip.staff.bank_name or "N/A", val_style),
            Paragraph("<b>Account Number:</b>", label_style),
            Paragraph(salary_slip.staff.bank_account_number or "N/A", val_style),
        ],
        [
            Paragraph("<b>Status:</b>", label_style),
            Paragraph(f"<b>{salary_slip.get_status_display().upper()}</b>", badge_style),
            Paragraph("<b>Payment Method:</b>", label_style),
            Paragraph(salary_slip.get_payment_method_display(), val_style),
        ]
    ]

    info_table = Table(info_data, colWidths=[35 * mm, 55 * mm, 35 * mm, 55 * mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), light_gray),
        ('BOX', (0, 0), (-1, -1), 0.5, border_gray),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, border_gray),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 4 * mm))

    # Attendance Metrics Summary Table
    att_header = [
        Paragraph("<b>Total Month Days</b>", label_style),
        Paragraph("<b>Present</b>", label_style),
        Paragraph("<b>Absent</b>", label_style),
        Paragraph("<b>Approved Leaves</b>", label_style),
        Paragraph("<b>Unpaid Leaves</b>", label_style),
        Paragraph("<b>Late Arrivals</b>", label_style),
    ]
    att_row = [
        Paragraph(str(salary_slip.total_days), val_style),
        Paragraph(str(salary_slip.present_days), val_style),
        Paragraph(f"<font color='{danger_color.hexval()}'><b>{salary_slip.absent_days}</b></font>", val_style),
        Paragraph(str(salary_slip.leave_days), val_style),
        Paragraph(f"<font color='{danger_color.hexval()}'><b>{salary_slip.unpaid_leave_days}</b></font>", val_style),
        Paragraph(str(salary_slip.late_count), val_style),
    ]
    att_table = Table([att_header, att_row], colWidths=[30 * mm] * 6)
    att_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ('BOX', (0, 0), (-1, -1), 0.5, border_gray),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, border_gray),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(att_table)
    story.append(Spacer(1, 5 * mm))

    # Earnings & Deductions Breakdown
    earn_deduct_data = [
        [
            Paragraph("<b>EARNINGS & ALLOWANCES</b>", tbl_header_style),
            Paragraph("<b>AMOUNT (PKR)</b>", tbl_header_style),
            Paragraph("<b>DEDUCTIONS & PENALTIES</b>", tbl_header_style),
            Paragraph("<b>AMOUNT (PKR)</b>", tbl_header_style),
        ],
        [
            Paragraph("Basic Salary", val_style),
            Paragraph(f"{salary_slip.basic_salary:,.2f}", val_style),
            Paragraph(f"Absent Days Cut ({salary_slip.absent_days} d)", val_style),
            Paragraph(f"{salary_slip.absent_deduction:,.2f}", val_style),
        ],
        [
            Paragraph("House / Conveyance Allowances", val_style),
            Paragraph(f"{salary_slip.allowances:,.2f}", val_style),
            Paragraph(f"Unpaid Leave Cut ({salary_slip.unpaid_leave_days} d)", val_style),
            Paragraph(f"{salary_slip.leave_deduction:,.2f}", val_style),
        ],
        [
            Paragraph("Performance Bonus / Incentives", val_style),
            Paragraph(f"{salary_slip.bonus:,.2f}", val_style),
            Paragraph(f"Late Arrival Cut ({salary_slip.late_count} lates)", val_style),
            Paragraph(f"{salary_slip.late_deduction:,.2f}", val_style),
        ],
        [
            Paragraph("-", val_style),
            Paragraph("-", val_style),
            Paragraph("Income Tax Deduction", val_style),
            Paragraph(f"{salary_slip.tax_deduction:,.2f}", val_style),
        ],
        [
            Paragraph("-", val_style),
            Paragraph("-", val_style),
            Paragraph("Other Advance / Deductions", val_style),
            Paragraph(f"{salary_slip.other_deductions:,.2f}", val_style),
        ],
        [
            Paragraph("<b>GROSS EARNINGS</b>", label_style),
            Paragraph(f"<b>PKR {salary_slip.gross_salary:,.2f}</b>", label_style),
            Paragraph("<b>TOTAL DEDUCTIONS</b>", label_style),
            Paragraph(f"<b><font color='{danger_color.hexval()}'>PKR {salary_slip.total_deductions:,.2f}</font></b>", label_style),
        ]
    ]

    fin_table = Table(earn_deduct_data, colWidths=[55 * mm, 35 * mm, 55 * mm, 35 * mm])
    fin_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), primary_color),
        ('BACKGROUND', (2, 0), (3, 0), primary_color),
        ('BOX', (0, 0), (-1, -1), 0.5, border_gray),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, border_gray),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#f8fafc")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(fin_table)
    story.append(Spacer(1, 5 * mm))

    # Net Salary Highlight Box
    net_box_data = [
        [
            Paragraph("<b>NET PAYABLE SALARY</b>", ParagraphStyle('NetLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, textColor=primary_color)),
            Paragraph(f"<b>PKR {salary_slip.net_salary:,.2f}</b>", ParagraphStyle('NetVal', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, textColor=primary_color, alignment=2)),
        ]
    ]
    net_table = Table(net_box_data, colWidths=[90 * mm, 90 * mm])
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
        ('BOX', (0, 0), (-1, -1), 1.5, primary_color),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(net_table)
    story.append(Spacer(1, 8 * mm))

    # QR Code & Signatures
    qr_img = qrcode.make(f"SLIP:{salary_slip.slip_number}|STAFF:{salary_slip.staff.employee_id}|NET:{salary_slip.net_salary}|STATUS:{salary_slip.status}")
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    qr_flowable = RLImage(qr_buffer, width=24 * mm, height=24 * mm)

    sign_data = [
        [
            qr_flowable,
            Paragraph("<br/><br/>________________________<br/><b>Prepared By / Accountant</b>", val_style),
            Paragraph("<br/><br/>________________________<br/><b>Principal / Director</b>", val_style),
            Paragraph("<br/><br/>________________________<br/><b>Employee Signature</b>", val_style),
        ]
    ]
    sign_table = Table(sign_data, colWidths=[35 * mm, 50 * mm, 50 * mm, 45 * mm])
    sign_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(KeepTogether(sign_table))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

