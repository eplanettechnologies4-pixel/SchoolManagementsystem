import io
import datetime
from django.utils import timezone
from reportlab.lib.pagesizes import mm, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.shapes import Drawing, Rect, String

def generate_admission_number():
    """
    Generates a unique admission number e.g., ADM-2026-0001
    """
    from students.models import StudentProfile
    year = datetime.datetime.now().year
    prefix = f"ADM-{year}-"
    last_student = StudentProfile.objects.filter(admission_number__startswith=prefix).order_by('-id').first()
    if last_student and last_student.admission_number:
        try:
            last_seq = int(last_student.admission_number.split('-')[-1])
            new_seq = last_seq + 1
        except ValueError:
            new_seq = StudentProfile.objects.count() + 1
    else:
        new_seq = StudentProfile.objects.count() + 1

    return f"{prefix}{new_seq:04d}"

def generate_roll_number(class_level, section):
    """
    Generates roll number per class/section e.g., 10A-01
    """
    from students.models import StudentProfile
    count = StudentProfile.objects.filter(class_level=class_level, section=section).count() + 1
    class_code = class_level.code or f"C{class_level.id}"
    sec_name = section.name.replace('Section ', '').strip()
    return f"{class_code}{sec_name}-{count:02d}"

def generate_student_id_card_pdf(student):
    """
    Generates a printable Student ID Card PDF binary stream using ReportLab.
    Standard ID Card Dimensions: 85.6mm x 54mm (landscape format).
    """
    buffer = io.BytesIO()
    # Card dimensions (Landscape CR80 standard)
    card_width, card_height = 85.6 * mm, 54 * mm

    doc = SimpleDocTemplate(
        buffer,
        pagesize=(card_width, card_height),
        leftMargin=3 * mm,
        rightMargin=3 * mm,
        topMargin=3 * mm,
        bottomMargin=3 * mm
    )

    story = []
    styles = getSampleStyleSheet()

    # Custom typography styles
    header_style = ParagraphStyle(
        'CardHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#0F172A'),
        alignment=1 # Center
    )
    subheader_style = ParagraphStyle(
        'CardSubHeader',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=6,
        leading=7,
        textColor=colors.HexColor('#475569'),
        alignment=1
    )
    name_style = ParagraphStyle(
        'CardName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=0
    )
    label_style = ParagraphStyle(
        'CardLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=6,
        leading=8,
        textColor=colors.HexColor('#334155')
    )
    value_style = ParagraphStyle(
        'CardValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=6,
        leading=8,
        textColor=colors.HexColor('#0F172A')
    )

    # 1. School Header Banner
    from academics.models import School
    school = School.objects.first()
    school_name = school.name.upper() if school else "APEX INTERNATIONAL ACADEMY"

    story.append(Paragraph(school_name, header_style))
    story.append(Paragraph("STUDENT IDENTIFICATION CARD", subheader_style))
    story.append(Spacer(1, 2 * mm))

    # 2. Student Info & Photo Layout Table
    full_name = student.get_full_name().upper()
    adm_no = student.admission_number
    roll_no = student.roll_number
    cls_sec = f"{student.class_level.name} - {student.section.name}"
    emergency = student.emergency_contact or (student.guardian.phone if student.guardian else "N/A")

    info_data = [
        [Paragraph(f"<b>{full_name}</b>", name_style), ""],
        [Paragraph("Adm No:", label_style), Paragraph(adm_no, value_style)],
        [Paragraph("Roll No:", label_style), Paragraph(roll_no, value_style)],
        [Paragraph("Class:", label_style), Paragraph(cls_sec, value_style)],
        [Paragraph("Emergency:", label_style), Paragraph(str(emergency), value_style)],
    ]

    info_table = Table(info_data, colWidths=[18 * mm, 38 * mm])
    info_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5),
        ('TOPPADDING', (0, 0), (-1, -1), 0.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    # Photo placeholder / real photo
    if student.photo and hasattr(student.photo, 'path'):
        try:
            img = RLImage(student.photo.path, width=18 * mm, height=22 * mm)
        except Exception:
            img = _draw_photo_placeholder()
    else:
        img = _draw_photo_placeholder()

    main_table_data = [[img, info_table]]
    main_table = Table(main_table_data, colWidths=[20 * mm, 58 * mm])
    main_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    story.append(main_table)

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

def _draw_photo_placeholder():
    d = Drawing(18 * mm, 22 * mm)
    d.add(Rect(0, 0, 18 * mm, 22 * mm, fillColor=colors.HexColor('#E2E8F0'), strokeColor=colors.HexColor('#94A3B8')))
    d.add(String(4 * mm, 9 * mm, "PHOTO", fontName="Helvetica-Bold", fontSize=6, fillColor=colors.HexColor('#64748B')))
    return d
