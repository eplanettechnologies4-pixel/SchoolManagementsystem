import io
import csv
import datetime
from django.db import transaction
from django.core.exceptions import ValidationError

from accounts.models import User, RoleChoices
from academics.models import ClassLevel, Section
from students.models import StudentProfile, GuardianProfile, StudentStatusChoices
from students.services.student_service import (
    generate_admission_number_atomic, generate_roll_number_atomic,
    find_or_create_guardian, validate_pakistan_cnic, validate_pakistan_phone,
    check_duplicate_student
)


def import_students_csv(file_obj, school, user=None, request=None):
    """
    Parses CSV/Excel file and bulk-creates student and guardian profiles with validation.
    Expected Columns:
    first_name, last_name, gender, dob, bform_number, guardian_first_name, guardian_last_name,
    guardian_cnic, guardian_phone, class_code, section_name
    """
    report = {
        'total_rows': 0,
        'students_created': 0,
        'errors': [],
    }

    try:
        content = file_obj.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
    except Exception as e:
        report['errors'].append(f"File decoding error: {str(e)}")
        return report

    row_idx = 1
    for row in reader:
        row_idx += 1
        report['total_rows'] += 1

        first_name = row.get('first_name', '').strip()
        last_name = row.get('last_name', '').strip()
        gender = row.get('gender', 'MALE').strip().upper()
        dob_str = row.get('dob', '').strip()
        bform = row.get('bform_number', '').strip()
        g_first_name = row.get('guardian_first_name', '').strip()
        g_last_name = row.get('guardian_last_name', '').strip()
        g_cnic = row.get('guardian_cnic', '').strip()
        g_phone = row.get('guardian_phone', '').strip()
        class_code = row.get('class_code', '').strip()
        section_name = row.get('section_name', '').strip()

        if not first_name or not class_code:
            report['errors'].append(f"Row {row_idx}: 'first_name' and 'class_code' are required.")
            continue

        class_obj = ClassLevel.objects.filter(code=class_code, is_active=True).first()
        if not class_obj:
            report['errors'].append(f"Row {row_idx}: Class code '{class_code}' not found.")
            continue

        section_obj = None
        if section_name:
            section_obj = Section.objects.filter(class_level=class_obj, name=section_name, is_active=True).first()
        if not section_obj:
            section_obj = Section.objects.filter(class_level=class_obj, is_active=True).first()

        if not section_obj:
            report['errors'].append(f"Row {row_idx}: No active section found for class '{class_code}'.")
            continue

        if section_obj.is_full:
            report['errors'].append(f"Row {row_idx}: Section '{section_obj.name}' is already at full capacity.")
            continue

        dob = None
        if dob_str:
            try:
                dob = datetime.date.fromisoformat(dob_str)
            except ValueError:
                dob = datetime.date(2012, 1, 1)

        # Duplicate check
        is_dup, dup_msg = check_duplicate_student(bform=bform, full_name=f"{first_name} {last_name}", dob=dob, guardian_cnic=g_cnic, school=school)
        if is_dup:
            report['errors'].append(f"Row {row_idx}: Duplicate skipped - {dup_msg}")
            continue

        try:
            with transaction.atomic():
                # 1. Guardian (Auto-link sibling if CNIC exists)
                guardian, _ = find_or_create_guardian({
                    'first_name': g_first_name or "Guardian",
                    'last_name': g_last_name or last_name,
                    'cnic': g_cnic,
                    'phone': g_phone or "+923000000000",
                    'relation': 'Father',
                }, school=school)

                # 2. Student User
                adm_no = generate_admission_number_atomic(school=school)
                roll_no = generate_roll_number_atomic(class_obj, section_obj)
                username = f"stu_{adm_no.lower().replace('-', '_')}"

                user_obj = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    role=RoleChoices.STUDENT,
                    school=school
                )
                user_obj.set_password('Password123!')
                user_obj.save()

                # 3. Student Profile
                student = StudentProfile.objects.create(
                    school=school,
                    user=user_obj,
                    admission_number=adm_no,
                    roll_number=roll_no,
                    class_level=class_obj,
                    section=section_obj,
                    guardian=guardian,
                    dob=dob,
                    gender=gender if gender in ['MALE', 'FEMALE', 'OTHER'] else 'MALE',
                    bform_number=bform,
                    status=StudentStatusChoices.ACTIVE
                )
                report['students_created'] += 1
        except Exception as e:
            report['errors'].append(f"Row {row_idx}: Creation error - {str(e)}")

    return report

