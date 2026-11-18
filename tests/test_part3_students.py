import pytest
import datetime
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from accounts.models import User, RoleChoices, AuditLog
from academics.models import School, AcademicYear, ClassLevel, Section
from students.models import (
    StudentProfile, GuardianProfile, StudentDocument,
    StudentStatusChoices, StudentDocumentType
)
from students.services.student_service import (
    validate_pakistan_cnic, validate_pakistan_phone, standardize_phone,
    generate_admission_number_atomic, generate_roll_number_atomic,
    find_or_create_guardian, check_duplicate_student,
    generate_admission_letter_pdf, generate_leaving_certificate_pdf
)


@pytest.fixture
def school_data(db):
    school = School.objects.create(name="Beaconhouse Lahore", code="BHL-01")
    year = AcademicYear.objects.create(
        school=school,
        name="2026-2027",
        start_date=datetime.date(2026, 8, 1),
        end_date=datetime.date(2027, 5, 31),
        is_current=True
    )
    c10 = ClassLevel.objects.create(school=school, name="Grade 10", numeric_order=10)
    sec_a = Section.objects.create(class_level=c10, name="Section A", capacity=30)
    
    admin_user = User.objects.create_user(
        username="admin_lahore",
        role=RoleChoices.ADMIN,
        school=school,
        password="AdminPassword123!"
    )
    return {
        'school': school,
        'academic_year': year,
        'class_level': c10,
        'section': sec_a,
        'admin_user': admin_user
    }


@pytest.mark.django_db
def test_cnic_and_phone_validations():
    # Valid CNIC
    validate_pakistan_cnic("35202-1234567-1")
    validate_pakistan_cnic("42101-7654321-9")

    # Invalid CNIC
    with pytest.raises(ValidationError):
        validate_pakistan_cnic("12345")
    with pytest.raises(ValidationError):
        validate_pakistan_cnic("3520212345671")

    # Valid Phone
    validate_pakistan_phone("+923001234567")
    validate_pakistan_phone("03001234567")

    # Invalid Phone
    with pytest.raises(ValidationError):
        validate_pakistan_phone("123456")

    # Standardize Phone
    assert standardize_phone("03001234567") == "+923001234567"


@pytest.mark.django_db
def test_atomic_number_generation(school_data):
    school = school_data['school']
    c10 = school_data['class_level']
    sec_a = school_data['section']

    adm1 = generate_admission_number_atomic(school=school, year=2026)
    assert adm1 == "ADM-2026-0001"

    # Create student with adm1
    u = User.objects.create_user(username="test_std_1", role=RoleChoices.STUDENT, school=school)
    StudentProfile.objects.create(
        user=u,
        school=school,
        admission_number=adm1,
        roll_number="C10A-01",
        class_level=c10,
        section=sec_a
    )

    adm2 = generate_admission_number_atomic(school=school, year=2026)
    assert adm2 == "ADM-2026-0002"

    roll2 = generate_roll_number_atomic(c10, sec_a)
    assert roll2 == "C10A-02"


@pytest.mark.django_db
def test_sibling_auto_link_by_guardian_cnic(school_data):
    school = school_data['school']
    c10 = school_data['class_level']
    sec_a = school_data['section']

    # Step 1: Create first guardian and child
    guardian_info = {
        'guardian_first_name': 'Tariq',
        'guardian_last_name': 'Mehmood',
        'guardian_cnic': '35202-9999999-1',
        'phone': '+923001112233',
        'relation': 'Father',
        'address': 'DHA Phase 5, Lahore'
    }
    g1, is_new1 = find_or_create_guardian(guardian_info, school=school)
    assert is_new1 is True
    assert g1.cnic == '35202-9999999-1'

    u1 = User.objects.create_user(username="child1", role=RoleChoices.STUDENT, school=school)
    s1 = StudentProfile.objects.create(
        user=u1,
        school=school,
        admission_number="ADM-2026-0001",
        roll_number="G10A-01",
        class_level=c10,
        section=sec_a,
        guardian=g1,
        bform_number="35202-1111111-1"
    )

    # Step 2: Second admission with same guardian CNIC
    g2, is_new2 = find_or_create_guardian(guardian_info, school=school)
    assert is_new2 is False
    assert g2.id == g1.id  # Same guardian profile reused

    u2 = User.objects.create_user(username="child2", role=RoleChoices.STUDENT, school=school)
    s2 = StudentProfile.objects.create(
        user=u2,
        school=school,
        admission_number="ADM-2026-0002",
        roll_number="G10A-02",
        class_level=c10,
        section=sec_a,
        guardian=g2,
        bform_number="35202-2222222-2"
    )

    # Verify both children linked under g1
    assert g1.students.count() == 2


@pytest.mark.django_db
def test_pdf_generation_admission_and_leaving_cert(school_data):
    school = school_data['school']
    c10 = school_data['class_level']
    sec_a = school_data['section']

    guardian = GuardianProfile.objects.create(
        school=school,
        first_name="Ahmed",
        last_name="Khan",
        cnic="35202-8888888-1",
        phone="+923005556677"
    )
    user = User.objects.create_user(
        username="std_test",
        first_name="Hamza",
        last_name="Ahmed",
        role=RoleChoices.STUDENT,
        school=school
    )
    student = StudentProfile.objects.create(
        user=user,
        school=school,
        admission_number="ADM-2026-0010",
        roll_number="G10A-10",
        class_level=c10,
        section=sec_a,
        guardian=guardian,
        dob=datetime.date(2010, 5, 15),
        bform_number="35202-7777777-1"
    )

    adm_pdf = generate_admission_letter_pdf(student)
    assert adm_pdf.startswith(b'%PDF')
    assert len(adm_pdf) > 1000

    slc_pdf = generate_leaving_certificate_pdf(student, reason="Relocated to Islamabad")
    assert slc_pdf.startswith(b'%PDF')
    assert len(slc_pdf) > 1000


@pytest.mark.django_db
def test_document_download_permission_check(school_data):
    school = school_data['school']
    c10 = school_data['class_level']
    sec_a = school_data['section']

    guardian_user = User.objects.create_user(username="parent_1", role=RoleChoices.PARENT, school=school)
    guardian = GuardianProfile.objects.create(
        user=guardian_user,
        school=school,
        first_name="Bilal",
        last_name="Shah",
        cnic="35202-6666666-1",
        phone="+923004443322"
    )
    std_user = User.objects.create_user(username="std_bilal", role=RoleChoices.STUDENT, school=school)
    student = StudentProfile.objects.create(
        user=std_user,
        school=school,
        admission_number="ADM-2026-0020",
        roll_number="G10A-20",
        class_level=c10,
        section=sec_a,
        guardian=guardian
    )

    other_student_user = User.objects.create_user(username="std_other", role=RoleChoices.STUDENT, school=school)

    # Create dummy document
    dummy_file = SimpleUploadedFile("birth_cert.pdf", b"%PDF-1.4 dummy file content", content_type="application/pdf")
    doc = StudentDocument.objects.create(
        school=school,
        student=student,
        document_type=StudentDocumentType.B_FORM,
        title="B-Form",
        file=dummy_file
    )

    client = Client()
    download_url = reverse('student_document_download', args=[doc.id])

    # Unauthenticated user -> redirect to login
    res = client.get(download_url)
    assert res.status_code == 302

    # Unauthorized other student -> 403 Forbidden
    client.force_login(other_student_user)
    res_other = client.get(download_url)
    assert res_other.status_code == 403

    # Authorized: Parent of student -> 200 OK
    client.force_login(guardian_user)
    res_parent = client.get(download_url)
    assert res_parent.status_code == 200

    # Authorized: Student themselves -> 200 OK
    client.force_login(std_user)
    res_self = client.get(download_url)
    assert res_self.status_code == 200


@pytest.mark.django_db
def test_admission_wizard_step1_post_and_duplicate_check(school_data):
    admin_user = school_data['admin_user']
    school = school_data['school']

    client = Client()
    client.force_login(admin_user)
    admission_url = reverse('student_admission')

    # POST Step 1
    post_data = {
        'wizard_step': '1',
        'step1-first_name': 'Danish',
        'step1-last_name': 'Ali',
        'step1-gender': 'MALE',
        'step1-dob': '2012-05-10',
        'step1-bform_number': '35202-1234567-1',
        'step1-religion': 'Islam',
        'step1-blood_group': 'B+',
        'step1-nationality': 'Pakistani',
        'action': 'next'
    }

    res = client.post(admission_url, post_data)
    assert res.status_code == 200
    # Wizard should advance to Step 2
    assert res.context['step'] == 2
    assert res.context['wizard_data']['step1']['bform_number'] == '35202-1234567-1'

    # Verify duplicate detection flags when same B-Form is registered
    c10 = school_data['class_level']
    sec_a = school_data['section']
    u = User.objects.create_user(username="existing_dup", role=RoleChoices.STUDENT, school=school)
    StudentProfile.objects.create(
        user=u,
        school=school,
        admission_number="ADM-2026-9999",
        roll_number="C10A-99",
        class_level=c10,
        section=sec_a,
        bform_number='35202-1234567-1'
    )

    # Re-post Step 1 with same B-Form
    res2 = client.post(admission_url, post_data)
    assert res2.status_code == 200
    assert len(res2.context['duplicate_warnings']) > 0
    assert 'already registered' in res2.context['duplicate_warnings'][0]
