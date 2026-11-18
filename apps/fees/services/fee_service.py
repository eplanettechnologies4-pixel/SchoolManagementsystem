import io
import datetime
import qrcode
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, Q

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm

from fees.models import Challan, Payment, ChallanStatusChoices


@transaction.atomic
def generate_challan_number(year=None) -> str:
    """
    Race-condition safe generation of Challan Number e.g. CHL-2026-0001
    using transaction.atomic and select_for_update.
    """
    if not year:
        year = datetime.datetime.now().year
    prefix = f"CHL-{year}-"
    
    last_chl = (
        Challan.all_objects.select_for_update()
        .filter(challan_no__startswith=prefix)
        .order_by('-id')
        .first()
    )
    if last_chl and last_chl.challan_no:
        try:
            last_seq = int(last_chl.challan_no.split('-')[-1])
            new_seq = last_seq + 1
        except ValueError:
            new_seq = Challan.all_objects.count() + 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:04d}"


def get_accountant_dashboard_metrics(school=None):
    """
    Returns total due, collected (virtual/real), and defaulters list for the accountant dashboard.
    """
    qs = Challan.objects.all()
    if school:
        qs = qs.filter(school=school)

    total_due = qs.aggregate(s=Sum('total'))['s'] or Decimal('0.00')
    total_collected = qs.aggregate(s=Sum('paid_amount'))['s'] or Decimal('0.00')
    total_remaining = max(Decimal('0.00'), total_due - total_collected)

    today = datetime.date.today()
    # Defaulters: Unpaid or Partial whose due_date < today
    defaulters = (
        qs.filter(
            Q(status__in=[ChallanStatusChoices.UNPAID, ChallanStatusChoices.PARTIAL]),
            Q(due_date__lt=today)
        )
        .select_related('student__user', 'student__class_level', 'student__section')
        .order_by('due_date')
    )

    return {
        'total_due': total_due,
        'total_collected': total_collected,
        'total_remaining': total_remaining,
        'defaulters_count': defaulters.count(),
        'defaulters': defaulters[:50],
        'total_challans': qs.count(),
        'paid_count': qs.filter(status=ChallanStatusChoices.PAID).count(),
        'unpaid_count': qs.filter(status=ChallanStatusChoices.UNPAID).count(),
    }


def generate_challan_pdf(challan: Challan) -> bytes:
    """
    Generates a 3-part bank/school/student printable fee challan PDF using ReportLab
    with embedded QR code and prominent VIRTUAL / TEST watermarks.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ChallanTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=1
    )
    badge_style = ParagraphStyle(
        'VirtualBadge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#dc2626'),
        alignment=1
    )
    label_style = ParagraphStyle(
        'ChallanLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor('#334155')
    )
    val_style = ParagraphStyle(
        'ChallanVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor('#0f172a')
    )

    # Generate QR Code in memory
    qr = qrcode.QRCode(box_size=3, border=1)
    qr_payload = (
        f"CHALLAN:{challan.challan_no}|"
        f"STUDENT:{challan.student.admission_number}|"
        f"NAME:{challan.student.get_full_name()}|"
        f"TOTAL:{challan.total}|"
        f"PAID:{challan.paid_amount}|"
        f"STATUS:{challan.status}|"
        f"TEST:VIRTUAL_SIMULATION"
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = io.BytesIO()
    img.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    qr_img = RLImage(qr_buffer, width=22 * mm, height=22 * mm)

    school_name = challan.school.name if challan.school else "School Management System"

    copies = ["BANK COPY", "INSTITUTION COPY", "STUDENT COPY"]
    columns = []

    for copy_name in copies:
        col_story = []
        col_story.append(Paragraph(school_name, title_style))
        col_story.append(Paragraph(f"<b>{copy_name}</b>", ParagraphStyle('sub', alignment=1, fontSize=8, textColor=colors.HexColor('#475569'))))
        col_story.append(Paragraph("★ VIRTUAL / TEST SIMULATION ONLY ★", badge_style))
        col_story.append(Spacer(1, 3 * mm))

        info_data = [
            [Paragraph("Challan No:", label_style), Paragraph(f"<b>{challan.challan_no}</b>", val_style)],
            [Paragraph("Admission No:", label_style), Paragraph(challan.student.admission_number, val_style)],
            [Paragraph("Student Name:", label_style), Paragraph(challan.student.get_full_name(), val_style)],
            [Paragraph("Class / Sec:", label_style), Paragraph(f"{challan.student.class_level.name} - {challan.student.section.name}", val_style)],
            [Paragraph("Roll No:", label_style), Paragraph(challan.student.roll_number, val_style)],
            [Paragraph("Billing Month:", label_style), Paragraph(f"{challan.month} {challan.year}", val_style)],
            [Paragraph("Due Date:", label_style), Paragraph(challan.due_date.strftime('%d-%b-%Y'), val_style)],
            [Paragraph("Status:", label_style), Paragraph(f"<b>{challan.status.upper()}</b>", val_style)],
        ]
        info_table = Table(info_data, colWidths=[24 * mm, 58 * mm])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
        ]))
        col_story.append(info_table)
        col_story.append(Spacer(1, 2 * mm))

        fee_breakdown = [
            [Paragraph("<b>Description</b>", label_style), Paragraph("<b>Amount (Rs.)</b>", label_style)],
            [Paragraph("Monthly Tuition & Academic Charges", val_style), Paragraph(f"{challan.total:,.2f}", val_style)],
            [Paragraph("<b>Total Payable:</b>", label_style), Paragraph(f"<b>Rs. {challan.total:,.2f}</b>", label_style)],
            [Paragraph("<b>Paid Amount:</b>", label_style), Paragraph(f"<b>Rs. {challan.paid_amount:,.2f}</b>", label_style)],
            [Paragraph("<b>Remaining Balance:</b>", label_style), Paragraph(f"<b>Rs. {challan.remaining_balance:,.2f}</b>", label_style)],
        ]
        fee_table = Table(fee_breakdown, colWidths=[54 * mm, 28 * mm])
        fee_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 1.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ]))
        col_story.append(fee_table)
        col_story.append(Spacer(1, 3 * mm))

        # QR Code + Stamp Placeholder
        btm_table = Table([
            [qr_img, Paragraph("<font size=6>Scan QR for digital verification.<br/>Simulated virtual fee challan.<br/>Immutable ledger record.</font>", val_style)]
        ], colWidths=[26 * mm, 56 * mm])
        btm_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        col_story.append(btm_table)

        col_story.append(Spacer(1, 2 * mm))
        col_story.append(Paragraph("<font size=6 color='#94a3b8'>Authorized Cashier / Bank Officer Signature ________________</font>", val_style))
        columns.append(col_story)

    # 3-part layout container
    main_table = Table([columns], colWidths=[90 * mm, 90 * mm, 90 * mm])
    main_table.setStyle(TableStyle([
        ('LINEBEFORE', (1, 0), (1, -1), 0.5, colors.HexColor('#94a3b8')),
        ('LINEBEFORE', (2, 0), (2, -1), 0.5, colors.HexColor('#94a3b8')),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3 * mm),
    ]))

    doc.build([main_table])
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
