import re
import urllib.parse
from io import BytesIO
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

# ReportLab Imports
from reportlab.lib.pagesizes import letter, landscape, A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def format_whatsapp_phone_number(raw_phone):
    """
    Validates and formats raw phone numbers into standard international format for WhatsApp.
    e.g. 03001234567 -> 923001234567, +92 300 1234567 -> 923001234567
    """
    if not raw_phone:
        return False, "", "Parent/Guardian phone number is missing."

    clean = re.sub(r'[^\d+]', '', str(raw_phone)).strip()
    
    if clean.startswith('+'):
        clean = clean[1:]

    # Handle Pakistani national numbers (e.g., 03001234567 -> 923001234567)
    if clean.startswith('03') and len(clean) == 11:
        clean = '92' + clean[1:]
    elif clean.startswith('3') and len(clean) == 10:
        clean = '92' + clean

    if len(clean) < 10 or len(clean) > 15:
        return False, clean, f"Invalid phone number format: '{raw_phone}'. Must contain 10-15 digits."

    return True, clean, ""


def build_whatsapp_message(voucher, request=None):
    """
    Constructs professional WhatsApp message content and click-to-chat URL.
    """
    guardian = voucher.student.guardian
    phone = guardian.phone if guardian and guardian.phone else getattr(voucher.student.user, 'phone_number', '')

    is_valid, formatted_phone, error_msg = format_whatsapp_phone_number(phone)

    guardian_name = guardian.get_full_name() if guardian else "Parent/Guardian"
    school_name = getattr(settings, 'SCHOOL_NAME', 'E-Planet Educational Portal')

    pdf_url = ""
    if request:
        pdf_url = request.build_absolute_uri(reverse('voucher_pdf', kwargs={'pk': voucher.pk}))

    message_text = (
        f"Dear Sir,\n\n"
        f"Your child's fee voucher has been generated.\n\n"
        f"Student: {voucher.student.get_full_name()}\n"
        f"Admission No: {voucher.student.admission_number}\n"
        f"Class: {voucher.student.class_level.name} - {voucher.student.section.name}\n"
        f"Month: {voucher.billing_month}\n"
        f"Voucher No: {voucher.voucher_number}\n"
        f"Due Date: {voucher.due_date.strftime('%d-%b-%Y') if voucher.due_date else 'N/A'}\n"
        f"Total Payable: Rs. {voucher.total_payable:,.2f}\n"
    )
    if pdf_url:
        message_text += f"View/Download Voucher: {pdf_url}\n"

    message_text += f"\nPlease pay the fee before the due date.\n\nThank you,\n{school_name}"

    encoded_text = urllib.parse.quote(message_text)
    whatsapp_url = f"https://wa.me/{formatted_phone}?text={encoded_text}" if is_valid else ""

    return {
        'is_valid': is_valid,
        'phone_number': phone,
        'formatted_phone': formatted_phone,
        'error': error_msg,
        'message_text': message_text,
        'whatsapp_url': whatsapp_url,
    }


def send_whatsapp_notification(voucher):
    """
    Structured backend function for direct WhatsApp Business Cloud API integration.
    """
    wa_data = build_whatsapp_message(voucher)
    if not wa_data['is_valid']:
        return {'success': False, 'message': wa_data['error']}

    # In production with API credentials:
    # response = requests.post("https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages", ...)
    return {'success': True, 'message': 'WhatsApp payload prepared successfully.', 'data': wa_data}


def generate_voucher_pdf(voucher):
    """
    Generates a 3-copy printable Pakistani School Fee Voucher PDF (Bank Copy, School Copy, Student Copy)
    using ReportLab.
    """
    buffer = BytesIO()
    # Landscape orientation for 3 side-by-side copies
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=0.25 * inch,
        leftMargin=0.25 * inch,
        topMargin=0.25 * inch,
        bottomMargin=0.25 * inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'VoucherTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=colors.HexColor('#1b1b6f')
    )
    subtitle_style = ParagraphStyle(
        'VoucherSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=9,
        alignment=1,
        textColor=colors.HexColor('#475569')
    )
    copy_tag_style = ParagraphStyle(
        'CopyTag',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.HexColor('#ff8000')
    )
    label_style = ParagraphStyle(
        'LabelStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=9,
        textColor=colors.HexColor('#0f172a')
    )
    value_style = ParagraphStyle(
        'ValueStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=9,
        textColor=colors.HexColor('#334155')
    )

    copy_titles = ["BANK COPY", "SCHOOL COPY", "STUDENT / PARENT COPY"]
    
    def create_single_copy_flowables(copy_name):
        copy_elements = []
        # Header
        copy_elements.append(Paragraph("E-PLANET EDUCATIONAL PORTAL", title_style))
        copy_elements.append(Paragraph("Main Campus, Education City • Contact: +92 42 35551234", subtitle_style))
        copy_elements.append(Spacer(1, 2))
        copy_elements.append(Paragraph(f"--- {copy_name} ---", copy_tag_style))
        copy_elements.append(Spacer(1, 4))

        # Meta Details Table
        meta_data = [
            [Paragraph("Voucher #:", label_style), Paragraph(voucher.voucher_number, value_style),
             Paragraph("Billing Month:", label_style), Paragraph(voucher.billing_month, value_style)],
            [Paragraph("Issue Date:", label_style), Paragraph(voucher.issue_date.strftime('%d-%b-%Y'), value_style),
             Paragraph("Due Date:", label_style), Paragraph(voucher.due_date.strftime('%d-%b-%Y'), value_style)],
            [Paragraph("Student Name:", label_style), Paragraph(voucher.student.get_full_name(), value_style),
             Paragraph("Adm No:", label_style), Paragraph(voucher.student.admission_number, value_style)],
            [Paragraph("Class & Sec:", label_style), Paragraph(f"{voucher.student.class_level.name} - {voucher.student.section.name}", value_style),
             Paragraph("Roll No:", label_style), Paragraph(voucher.student.roll_number, value_style)],
        ]
        meta_table = Table(meta_data, colWidths=[0.75*inch, 1.25*inch, 0.75*inch, 1.25*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        copy_elements.append(meta_table)
        copy_elements.append(Spacer(1, 4))

        # Particulars Breakdown Table
        breakdown_data = [
            [Paragraph("<b>Fee Particulars</b>", label_style), Paragraph("<b>Amount (Rs.)</b>", label_style)]
        ]
        
        items = [
            ("Tuition Fee", voucher.tuition_fee),
            ("Admission Fee", voucher.admission_fee),
            ("Exam Fee", voucher.exam_fee),
            ("Transport Fee", voucher.transport_fee),
            ("Hostel Fee", voucher.hostel_fee),
            ("Other Charges", voucher.other_charges),
        ]
        for name, amt in items:
            if Decimal(amt or 0) > Decimal('0.00'):
                breakdown_data.append([Paragraph(name, value_style), Paragraph(f"{amt:,.2f}", value_style)])

        breakdown_data.append([Paragraph("<b>Subtotal</b>", label_style), Paragraph(f"<b>{voucher.subtotal:,.2f}</b>", label_style)])
        
        if Decimal(voucher.discount_amount or 0) > Decimal('0.00'):
            breakdown_data.append([Paragraph("Concession / Discount", value_style), Paragraph(f"- {voucher.discount_amount:,.2f}", value_style)])
        if Decimal(voucher.previous_balance or 0) > Decimal('0.00'):
            breakdown_data.append([Paragraph("Previous Arrears", value_style), Paragraph(f"+ {voucher.previous_balance:,.2f}", value_style)])
        if Decimal(voucher.late_fine or 0) > Decimal('0.00'):
            breakdown_data.append([Paragraph("Late Payment Fine", value_style), Paragraph(f"+ {voucher.late_fine:,.2f}", value_style)])

        breakdown_data.append([Paragraph("<b>TOTAL PAYABLE</b>", label_style), Paragraph(f"<b>Rs. {voucher.total_payable:,.2f}</b>", label_style)])

        b_table = Table(breakdown_data, colWidths=[2.5*inch, 1.5*inch])
        b_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#009688')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#fef3c7')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        copy_elements.append(b_table)
        copy_elements.append(Spacer(1, 4))

        # Instructions Footer
        instructions = (
            "<b>Bank:</b> Allied Bank Ltd (A/C: 0010048291001)<br/>"
            "<b>Note:</b> Pay before due date to avoid Rs. 500 late fine.<br/>"
            "Computer generated voucher. No signature required."
        )
        copy_elements.append(Paragraph(instructions, subtitle_style))
        copy_elements.append(Spacer(1, 8))
        copy_elements.append(Paragraph("___________________________<br/>Authorized Officer / Cashier", copy_tag_style))
        
        return copy_elements

    # Render 3 columns side-by-side
    col1 = create_single_copy_flowables("BANK COPY")
    col2 = create_single_copy_flowables("SCHOOL COPY")
    col3 = create_single_copy_flowables("STUDENT / PARENT COPY")

    master_table = Table([[col1, col2, col3]], colWidths=[3.7*inch, 3.7*inch, 3.7*inch])
    master_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('RIGHTPADDING', (0,0), (0,0), 6),
        ('LEFTPADDING', (1,0), (1,0), 6),
        ('RIGHTPADDING', (1,0), (1,0), 6),
        ('LEFTPADDING', (2,0), (2,0), 6),
        ('LINEAFTER', (0,0), (0,0), 1, colors.HexColor('#cbd5e1')),
        ('LINEAFTER', (1,0), (1,0), 1, colors.HexColor('#cbd5e1')),
    ]))

    story = [master_table]
    doc.build(story)
    
    pdf_value = buffer.getvalue()
    buffer.close()
    return pdf_value


def generate_receipt_pdf(payment):
    """
    Generates an official Payment Receipt PDF using ReportLab.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('RTitle', fontName='Helvetica-Bold', fontSize=14, leading=16, alignment=1, textColor=colors.HexColor('#009688'))
    subtitle_style = ParagraphStyle('RSubTitle', fontName='Helvetica', fontSize=9, leading=11, alignment=1, textColor=colors.HexColor('#64748b'))
    tag_style = ParagraphStyle('RTag', fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#ff8000'))
    
    label_style = ParagraphStyle('RLabel', fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.HexColor('#0f172a'))
    val_style = ParagraphStyle('RVal', fontName='Helvetica', fontSize=9, leading=11, textColor=colors.HexColor('#334155'))

    story = []
    story.append(Paragraph("E-PLANET EDUCATIONAL PORTAL", title_style))
    story.append(Paragraph("Main Campus, Education City • Contact: +92 42 35551234", subtitle_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph("OFFICIAL FEE PAYMENT RECEIPT", tag_style))
    story.append(Spacer(1, 10))

    receipt_data = [
        [Paragraph("Receipt No:", label_style), Paragraph(payment.receipt_number, val_style),
         Paragraph("Payment Date:", label_style), Paragraph(payment.payment_date.strftime('%d-%b-%Y'), val_style)],
        [Paragraph("Voucher No:", label_style), Paragraph(payment.voucher.voucher_number, val_style),
         Paragraph("Billing Month:", label_style), Paragraph(payment.voucher.billing_month, val_style)],
        [Paragraph("Student Name:", label_style), Paragraph(payment.voucher.student.get_full_name(), val_style),
         Paragraph("Admission No:", label_style), Paragraph(payment.voucher.student.admission_number, val_style)],
        [Paragraph("Class & Section:", label_style), Paragraph(f"{payment.voucher.student.class_level.name} - {payment.voucher.student.section.name}", val_style),
         Paragraph("Payment Method:", label_style), Paragraph(payment.get_payment_method_display(), val_style)],
        [Paragraph("Amount Paid:", label_style), Paragraph(f"<b>Rs. {payment.amount_paid:,.2f}</b>", label_style),
         Paragraph("Remaining Balance:", label_style), Paragraph(f"Rs. {payment.voucher.remaining_balance:,.2f}", val_style)],
        [Paragraph("Reference / Txn #:", label_style), Paragraph(payment.transaction_reference or "N/A", val_style),
         Paragraph("Received By:", label_style), Paragraph(payment.received_by.get_full_name() if payment.received_by else "Cashier", val_style)],
    ]

    r_table = Table(receipt_data, colWidths=[1.5*inch, 2.2*inch, 1.5*inch, 2.2*inch])
    r_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#009688')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(r_table)
    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>Status:</b> PAID RECEIPT • Thank you for your payment.", subtitle_style))
    story.append(Spacer(1, 30))
    story.append(Paragraph("___________________________<br/>Accounts Officer Stamp & Signature", tag_style))

    doc.build(story)
    pdf_val = buffer.getvalue()
    buffer.close()
    return pdf_val
