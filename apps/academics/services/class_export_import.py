import io
import csv
import datetime
from decimal import Decimal
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm

from academics.models import ClassLevel, Section
from students.models import StudentProfile


def export_class_list_pdf(class_level: ClassLevel) -> bytes:
    """
    Generates a formal Class Student Directory PDF using ReportLab.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=portrait(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=16,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1
    )
    sub_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#64748b'),
        alignment=1
    )
    th_style = ParagraphStyle(
        'TH',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#334155')
    )
    td_style = ParagraphStyle(
        'TD',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#0f172a')
    )

    story = []
    school_name = class_level.school.name if class_level.school else "School Management System"
    story.append(Paragraph(school_name, title_style))
    story.append(Paragraph(f"Class Directory: <b>{class_level.name}</b> (Code: {class_level.code})", sub_style))
    story.append(Spacer(1, 4 * mm))

    students = StudentProfile.objects.filter(
        class_level=class_level,
        is_deleted=False
    ).select_related('section', 'user', 'guardian').order_by('section__name', 'roll_number')

    table_data = [
        [
            Paragraph("<b>Adm #</b>", th_style),
            Paragraph("<b>Roll #</b>", th_style),
            Paragraph("<b>Student Full Name</b>", th_style),
            Paragraph("<b>Section</b>", th_style),
            Paragraph("<b>Gender</b>", th_style),
            Paragraph("<b>Guardian Contact</b>", th_style),
            Paragraph("<b>Status</b>", th_style),
        ]
    ]

    for s in students:
        sec_name = s.section.name if s.section else "Unassigned"
        phone = s.guardian.phone if s.guardian else "N/A"
        table_data.append([
            Paragraph(s.admission_number, td_style),
            Paragraph(s.roll_number, td_style),
            Paragraph(s.get_full_name(), td_style),
            Paragraph(sec_name, td_style),
            Paragraph(s.get_gender_display(), td_style),
            Paragraph(phone, td_style),
            Paragraph(s.get_status_display(), td_style),
        ])

    table = Table(table_data, colWidths=[24 * mm, 18 * mm, 50 * mm, 24 * mm, 16 * mm, 34 * mm, 22 * mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(table)

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(f"<font size=7 color='#94a3b8'>Generated on {datetime.datetime.now().strftime('%d-%b-%Y %H:%M')} &bull; Total Enrolled Students: {students.count()}</font>", sub_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def export_class_list_excel(class_level: ClassLevel) -> bytes:
    """
    Generates a styled Excel workbook (.xlsx) listing student records for a class.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{class_level.code}_Students"

    # Header styling
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # Title row
    ws.merge_cells('A1:G1')
    ws['A1'] = f"{class_level.school.name if class_level.school else 'SMS'} — {class_level.name} Student Directory"
    ws['A1'].font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
    ws['A1'].alignment = Alignment(horizontal="left", vertical="center")

    headers = ["Admission No", "Roll No", "Student Full Name", "Section", "Gender", "Guardian Phone", "Status"]
    ws.append([]) # row 2 empty
    ws.append(headers) # row 3

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=3, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    students = StudentProfile.objects.filter(
        class_level=class_level,
        is_deleted=False
    ).select_related('section', 'user', 'guardian').order_by('section__name', 'roll_number')

    for s in students:
        sec = s.section.name if s.section else "Unassigned"
        phone = s.guardian.phone if s.guardian else "N/A"
        ws.append([
            s.admission_number,
            s.roll_number,
            s.get_full_name(),
            sec,
            s.get_gender_display(),
            phone,
            s.get_status_display()
        ])

    # Apply borders and auto column width
    for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=1, max_col=7):
        for cell in row:
            cell.border = thin_border
            if cell.row > 3:
                cell.font = Font(name="Calibri", size=10)

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    excel_bytes = output.getvalue()
    output.close()
    return excel_bytes


def import_classes_csv(file_obj, school, user=None, request=None):
    """
    Parses CSV for bulk class/section creation:
    Expected Columns: class_name, class_code, numeric_order, section_name, capacity, room_number
    """
    report = {
        'total_rows': 0,
        'classes_created': 0,
        'sections_created': 0,
        'errors': [],
    }

    try:
        content = file_obj.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
    except Exception as e:
        report['errors'].append(f"Unable to read CSV file: {str(e)}")
        return report

    row_idx = 1
    for row in reader:
        row_idx += 1
        report['total_rows'] += 1
        class_name = row.get('class_name', '').strip()
        class_code = row.get('class_code', '').strip()
        numeric_order = row.get('numeric_order', '1').strip()
        section_name = row.get('section_name', '').strip()
        capacity = row.get('capacity', '40').strip()
        room_number = row.get('room_number', '').strip()

        if not class_name or not class_code:
            report['errors'].append(f"Row {row_idx}: 'class_name' and 'class_code' are required.")
            continue

        try:
            num_order = int(numeric_order)
            cap = int(capacity)
        except ValueError:
            report['errors'].append(f"Row {row_idx}: numeric_order and capacity must be positive integers.")
            continue

        class_obj, created_cls = ClassLevel.all_objects.get_or_create(
            school=school,
            code=class_code,
            defaults={
                'name': class_name,
                'numeric_order': num_order,
                'is_active': True,
                'is_deleted': False
            }
        )
        if created_cls:
            report['classes_created'] += 1

        if section_name:
            sec_obj, created_sec = Section.all_objects.get_or_create(
                class_level=class_obj,
                name=section_name,
                defaults={
                    'capacity': cap,
                    'room_number': room_number,
                    'is_active': True,
                    'is_deleted': False
                }
            )
            if created_sec:
                report['sections_created'] += 1

    return report
