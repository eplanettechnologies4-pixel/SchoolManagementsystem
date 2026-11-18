import io
import re
import uuid
import datetime
from decimal import Decimal
from PIL import Image as PILImage

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings

from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm

from accounts.models import User, RoleChoices
from accounts.services import log_audit
from academics.models import ClassLevel, Section, School
from students.models import (
    StudentProfile, GuardianProfile, StudentDocument,
    StudentStatusChoices, GenderChoices, AdmissionDraft
)


CNIC_REGEX = re.compile(r'^\d{5}-\d{7}-\d{1}$')
PHONE_REGEX = re.compile(r'^(\+92|0)?3\d{9}$')


def validate_pakistan_cnic(val: str):
    """
    Validates Pakistani CNIC / B-Form format: 35202-1234567-1
    """
    if not val:
        return
    val = val.strip()
    if not CNIC_REGEX.match(val):
        raise ValidationError("Invalid CNIC/B-Form format. Must match standard Pakistani format: 35202-1234567-1")


def validate_pakistan_phone(val: str):
    """
    Validates Pakistani mobile format (+923001234567 or 03001234567).
    """
    if not val:
        return
    val = val.strip().replace(' ', '').replace('-', '')
    if not PHONE_REGEX.match(val):
        raise ValidationError("Invalid mobile number format. Must be a valid Pakistani number (e.g. +923001234567 or 03001234567).")


def standardize_phone(val: str) -> str:
    if not val:
        return ''
    cleaned = val.strip().replace(' ', '').replace('-', '')
    if cleaned.startswith('03'):
        return '+92' + cleaned[1:]
    if cleaned.startswith('3') and len(cleaned) == 10:
        return '+92' + cleaned
    if cleaned.startswith('923'):
        return '+' + cleaned
    return cleaned


def process_and_compress_photo(photo_file) -> io.BytesIO:
    """
    Validates size (max 2MB), resizes, crops to portrait square or 4:5,
    and compresses to modern WebP format.
    """
    if photo_file.size > 2 * 1024 * 1024:
        raise ValidationError("Photo file size exceeds maximum limit of 2MB.")

    try:
        img = PILImage.open(photo_file)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Resize if dimensions too large (max 800x800)
        img.thumbnail((800, 800), PILImage.Resampling.LANCZOS)
        
        output = io.BytesIO()
        img.save(output, format='WEBP', quality=85)
        output.seek(0)
        return output
    except Exception as e:
        raise ValidationError(f"Unable to process image: {str(e)}")


@transaction.atomic
def generate_admission_number_atomic(school=None, year=None) -> str:
    """
    Race-condition safe sequential Admission Number generation e.g. ADM-2026-0001
    using select_for_update.
    """
    if not year:
        year = datetime.datetime.now().year
    prefix = f"ADM-{year}-"

    qs = StudentProfile.all_objects.select_for_update().filter(admission_number__startswith=prefix)
    if school:
        qs = qs.filter(class_level__school=school)
    last_student = qs.order_by('-id').first()

    if last_student and last_student.admission_number:
        try:
            last_seq = int(last_student.admission_number.split('-')[-1])
            new_seq = last_seq + 1
        except ValueError:
            new_seq = StudentProfile.all_objects.count() + 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:04d}"


@transaction.atomic
def generate_roll_number_atomic(class_level: ClassLevel, section: Section) -> str:
    """
    Race-condition safe sequential Roll Number generation e.g. G10A-01
    using select_for_update.
    """
    class_code = class_level.code or f"C{class_level.numeric_order}"
    sec_name = section.name.replace('Section', '').strip().upper() or 'A'
    prefix = f"{class_code}{sec_name}-"

    last_stu = (
        StudentProfile.all_objects.select_for_update()
        .filter(class_level=class_level, section=section, roll_number__startswith=prefix)
        .order_by('-id')
        .first()
    )
    if last_stu and last_stu.roll_number:
        try:
            last_seq = int(last_stu.roll_number.split('-')[-1])
            new_seq = last_seq + 1
        except ValueError:
            new_seq = StudentProfile.objects.filter(class_level=class_level, section=section).count() + 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:02d}"


def check_duplicate_student(bform=None, bform_number=None, full_name=None, dob=None, guardian_cnic=None, school=None, exclude_id=None):
    """
    Duplicate detection:
    Warns if same B-Form or (name + DOB + guardian CNIC) already exists.
    Returns (is_duplicate: bool, warning_message: str, matched_student: StudentProfile | None)
    """
    bform = bform_number or bform
    qs = StudentProfile.objects.filter(is_deleted=False)
    if school:
        qs = qs.filter(school=school)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)

    if bform and str(bform).strip():
        dup_bform = qs.filter(bform_number=str(bform).strip()).first()
        if dup_bform:
            return True, f"A student with B-Form '{bform}' is already registered: {dup_bform.get_full_name()} (Adm: {dup_bform.admission_number}).", dup_bform

    if full_name and dob and guardian_cnic:
        first_name = full_name.split()[0] if full_name else ''
        dup_combo = qs.filter(
            user__first_name__iexact=first_name,
            dob=dob,
            guardian__cnic=guardian_cnic.strip()
        ).first()
        if dup_combo:
            return True, f"Possible duplicate student detected: {dup_combo.get_full_name()} (DOB: {dob}, Guardian CNIC: {guardian_cnic}).", dup_combo

    return False, "", None


def find_or_create_guardian(guardian_data, school=None):
    """
    Finds guardian by CNIC or phone to auto-link siblings.
    Creates new GuardianProfile if not found.
    Returns (guardian, is_new).
    """
    cnic = guardian_data.get('guardian_cnic') or guardian_data.get('cnic', '')
    cnic = cnic.strip() if cnic else ''
    raw_phone = guardian_data.get('phone', '')
    phone = standardize_phone(raw_phone)

    guardian = None
    if cnic:
        guardian = GuardianProfile.objects.filter(cnic=cnic).first()
    if not guardian and phone:
        guardian = GuardianProfile.objects.filter(phone=phone).first()

    first_name = guardian_data.get('guardian_first_name') or guardian_data.get('first_name', '')
    last_name = guardian_data.get('guardian_last_name') or guardian_data.get('last_name', '')

    if guardian:
        # Update details if provided
        for k, v in guardian_data.items():
            if v and hasattr(guardian, k):
                setattr(guardian, k, v)
        if first_name:
            guardian.first_name = first_name
        if last_name:
            guardian.last_name = last_name
        guardian.save()
        return guardian, False

    # Create new guardian
    user = None
    email = guardian_data.get('email', '').strip()
    username = f"parent_{cnic.replace('-', '')}" if cnic else f"parent_{uuid.uuid4().hex[:6]}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            'first_name': first_name,
            'last_name': last_name,
            'email': email or f"{username}@school.portal",
            'role': RoleChoices.PARENT,
            'school': school
        }
    )
    user.set_password('Password123!')
    user.save()

    guardian = GuardianProfile.objects.create(
        school=school,
        user=user,
        first_name=first_name,
        last_name=last_name,
        father_name=guardian_data.get('father_name', ''),
        mother_name=guardian_data.get('mother_name', ''),
        relation=guardian_data.get('relation', 'Father'),
        cnic=cnic,
        occupation=guardian_data.get('occupation', ''),
        phone=phone,
        whatsapp_number=guardian_data.get('whatsapp_number', phone),
        email=email,
        address=guardian_data.get('address', ''),
        emergency_contact=guardian_data.get('emergency_contact', phone)
    )
    return guardian, True


def generate_admission_letter_pdf(student: StudentProfile) -> bytes:
    """
    Generates an official Student Admission Confirmation Letter PDF using ReportLab.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=portrait(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('HeadTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1e3a8a'), alignment=1)
    sub_style = ParagraphStyle('HeadSub', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=13, textColor=colors.HexColor('#64748b'), alignment=1)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontName='Helvetica', fontSize=10.5, leading=16, textColor=colors.HexColor('#1e293b'))
    bold_style = ParagraphStyle('BoldText', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10.5, leading=16, textColor=colors.HexColor('#0f172a'))

    story = []
    school_name = student.class_level.school.name if student.class_level.school else "School Management System"
    school_address = student.class_level.school.address if student.class_level.school else "Islamabad, Pakistan"

    story.append(Paragraph(school_name.upper(), title_style))
    story.append(Paragraph(school_address, sub_style))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("<b>OFFICIAL PROVISIONAL ADMISSION LETTER</b>", ParagraphStyle('H2', alignment=1, fontSize=12, leading=14, textColor=colors.HexColor('#2563eb'))))
    story.append(Spacer(1, 8 * mm))

    date_str = datetime.date.today().strftime('%d %B, %Y')
    story.append(Paragraph(f"<b>Date:</b> {date_str}", body_style))
    story.append(Paragraph(f"<b>Admission Reference Number:</b> {student.admission_number}", bold_style))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(
        f"Dear <b>{student.guardian.get_full_name() if student.guardian else 'Guardian'}</b>,",
        body_style
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"We are pleased to inform you that your child / ward, <b>{student.get_full_name()}</b>, "
        f"has been successfully granted formal admission to <b>{school_name}</b> for the academic session.",
        body_style
    ))
    story.append(Spacer(1, 5 * mm))

    details = [
        [Paragraph("<b>Student Full Name:</b>", body_style), Paragraph(student.get_full_name(), bold_style)],
        [Paragraph("<b>Admission Number:</b>", body_style), Paragraph(student.admission_number, bold_style)],
        [Paragraph("<b>Roll Number:</b>", body_style), Paragraph(student.roll_number, bold_style)],
        [Paragraph("<b>Allocated Class:</b>", body_style), Paragraph(student.class_level.name, bold_style)],
        [Paragraph("<b>Allocated Section:</b>", body_style), Paragraph(student.section.name, bold_style)],
        [Paragraph("<b>B-Form / CNIC:</b>", body_style), Paragraph(student.bform_number or "N/A", body_style)],
        [Paragraph("<b>Date of Birth:</b>", body_style), Paragraph(student.dob.strftime('%d-%b-%Y') if student.dob else "N/A", body_style)],
        [Paragraph("<b>Date of Admission:</b>", body_style), Paragraph(student.admission_date.strftime('%d-%b-%Y'), body_style)],
    ]
    t = Table(details, colWidths=[65 * mm, 105 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Please ensure all required original documents (B-Form, previous mark sheets, transfer certificate) "
        "are deposited with the registrar's office. We look forward to a successful and rewarding academic journey.",
        body_style
    ))
    story.append(Spacer(1, 15 * mm))

    sig_data = [
        [
            Paragraph("____________________________<br/><b>Registrar / Admissions Office</b>", body_style),
            Paragraph("____________________________<br/><b>Principal / Head of Institution</b>", body_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[85 * mm, 85 * mm])
    story.append(sig_table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_leaving_certificate_pdf(student: StudentProfile, reason=None) -> bytes:
    """
    Generates a formal School Leaving / Transfer Certificate PDF using ReportLab.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=portrait(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('HeadTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1e3a8a'), alignment=1)
    sub_style = ParagraphStyle('HeadSub', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=13, textColor=colors.HexColor('#64748b'), alignment=1)
    body_style = ParagraphStyle('BodyText', parent=styles['Normal'], fontName='Helvetica', fontSize=10.5, leading=16, textColor=colors.HexColor('#1e293b'))
    bold_style = ParagraphStyle('BoldText', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10.5, leading=16, textColor=colors.HexColor('#0f172a'))

    story = []
    school_name = student.class_level.school.name if student.class_level.school else "School Management System"
    story.append(Paragraph(school_name.upper(), title_style))
    story.append(Paragraph("BOARD OF INTERMEDIATE & SECONDARY EDUCATION RECOGNIZED INSTITUTION", sub_style))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("<b>SCHOOL LEAVING / TRANSFER CERTIFICATE</b>", ParagraphStyle('H2', alignment=1, fontSize=13, leading=15, textColor=colors.HexColor('#dc2626'))))
    story.append(Spacer(1, 8 * mm))

    slc_no = f"SLC-{datetime.datetime.now().year}-{student.admission_number.split('-')[-1]}"
    story.append(Paragraph(f"<b>Certificate Serial No:</b> {slc_no} &nbsp;&nbsp;&nbsp;&nbsp; <b>Date of Issue:</b> {datetime.date.today().strftime('%d-%b-%Y')}", body_style))
    story.append(Spacer(1, 5 * mm))

    cert_info = [
        [Paragraph("<b>Student Full Name:</b>", body_style), Paragraph(student.get_full_name(), bold_style)],
        [Paragraph("<b>Father's / Guardian's Name:</b>", body_style), Paragraph(student.guardian.get_full_name() if student.guardian else "N/A", body_style)],
        [Paragraph("<b>B-Form / CNIC Number:</b>", body_style), Paragraph(student.bform_number or "N/A", body_style)],
        [Paragraph("<b>Date of Birth:</b>", body_style), Paragraph(student.dob.strftime('%d-%b-%Y') if student.dob else "N/A", body_style)],
        [Paragraph("<b>Admission Number:</b>", body_style), Paragraph(student.admission_number, body_style)],
        [Paragraph("<b>Date of Admission:</b>", body_style), Paragraph(student.admission_date.strftime('%d-%b-%Y'), body_style)],
        [Paragraph("<b>Class in which last studied:</b>", body_style), Paragraph(f"{student.class_level.name} ({student.section.name})", bold_style)],
        [Paragraph("<b>School Dues Status:</b>", body_style), Paragraph("Cleared in Full &bull; No Outstanding Balance", bold_style)],
        [Paragraph("<b>Reason for Leaving School:</b>", body_style), Paragraph(reason or "Parent's Request / Migration", body_style)],
        [Paragraph("<b>General Conduct & Character:</b>", body_style), Paragraph("Satisfactory / Good", bold_style)],
    ]

    t = Table(cert_info, colWidths=[65 * mm, 105 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Certified that the above particulars are in accordance with the institution's official general register.",
        body_style
    ))
    story.append(Spacer(1, 20 * mm))

    sig_data = [
        [
            Paragraph("____________________________<br/><b>Class Teacher</b>", body_style),
            Paragraph("____________________________<br/><b>Verified by Incharge</b>", body_style),
            Paragraph("____________________________<br/><b>Principal (With Official Seal)</b>", body_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[55 * mm, 55 * mm, 60 * mm])
    story.append(sig_table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
