import pytest
import datetime
from django.test import Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User, RoleChoices, Notice, NoticeRead, NoticeTargetChoices
from academics.models import School, AcademicYear, ClassLevel, Section
from students.models import (
    StudentProfile, GuardianProfile, StudentDocument,
    StudentLeaveRequest, StudentLeaveStatusChoices
)
from fees.models import Challan, ChallanStatusChoices


@pytest.fixture
def portal_setup(db):
    school = School.objects.create(name="Lahore Grammar School", code="LGS-01")
    year = AcademicYear.objects.create(
        school=school,
        name="2026-2027",
        start_date=datetime.date(2026, 8, 1),
        end_date=datetime.date(2027, 5, 31),
        is_current=True
    )
    c9 = ClassLevel.objects.create(school=school, name="Grade 9", numeric_order=9)
    sec_a = Section.objects.create(class_level=c9, name="Section A", capacity=30)

    # Guardian 1 & Child 1
    p1_user = User.objects.create_user(username="parent_one", role=RoleChoices.PARENT, school=school, password="Password123!")
    g1 = GuardianProfile.objects.create(
        user=p1_user,
        school=school,
        first_name="Kamran",
        last_name="Akmal",
        cnic="35202-1111111-1",
        phone="+923001111111"
    )

    s1_user = User.objects.create_user(username="student_one", role=RoleChoices.STUDENT, school=school, password="Password123!")
    s1 = StudentProfile.objects.create(
        user=s1_user,
        school=school,
        admission_number="ADM-2026-0101",
        roll_number="C09A-01",
        class_level=c9,
        section=sec_a,
        guardian=g1
    )

    # Child 2 of Guardian 1 (Multi-ward test)
    s2_user = User.objects.create_user(username="student_two", role=RoleChoices.STUDENT, school=school, password="Password123!")
    s2 = StudentProfile.objects.create(
        user=s2_user,
        school=school,
        admission_number="ADM-2026-0102",
        roll_number="C09A-02",
        class_level=c9,
        section=sec_a,
        guardian=g1
    )

    # Student 3 & Guardian 2 (Unrelated, for ID tampering test)
    p2_user = User.objects.create_user(username="parent_two", role=RoleChoices.PARENT, school=school, password="Password123!")
    g2 = GuardianProfile.objects.create(
        user=p2_user,
        school=school,
        first_name="Rashid",
        last_name="Latif",
        cnic="35202-2222222-2",
        phone="+923002222222"
    )
    s3_user = User.objects.create_user(username="student_three", role=RoleChoices.STUDENT, school=school, password="Password123!")
    s3 = StudentProfile.objects.create(
        user=s3_user,
        school=school,
        admission_number="ADM-2026-0103",
        roll_number="C09A-03",
        class_level=c9,
        section=sec_a,
        guardian=g2
    )

    # Create dummy private document for Student 1
    doc1 = StudentDocument.objects.create(
        school=school,
        student=s1,
        title="Student 1 Marksheet",
        file=SimpleUploadedFile("s1_marks.pdf", b"%PDF-1.4 s1 file", content_type="application/pdf")
    )

    return {
        'school': school,
        'guardian_1': g1,
        'parent_1_user': p1_user,
        'student_1': s1,
        'student_1_user': s1_user,
        'student_2': s2,
        'student_2_user': s2_user,
        'guardian_2': g2,
        'parent_2_user': p2_user,
        'student_3': s3,
        'student_3_user': s3_user,
        'doc_1': doc1,
    }


@pytest.mark.django_db
def test_student_dashboard_and_notice_read_tracking(portal_setup):
    s1_user = portal_setup['student_1_user']
    s1 = portal_setup['student_1']
    school = portal_setup['school']

    notice = Notice.objects.create(
        school=school,
        title="Sports Gala 2026",
        content="Annual sports competition starting next Monday.",
        target_role=NoticeTargetChoices.ALL,
        is_active=True
    )

    client = Client()
    client.force_login(s1_user)

    res = client.get(reverse('dashboard_student'))
    assert res.status_code == 200
    assert "Sports Gala 2026" in res.content.decode()

    # Verify notice read receipt was created
    assert NoticeRead.objects.filter(notice=notice, user=s1_user).exists()


@pytest.mark.django_db
def test_parent_dashboard_multi_ward_and_leave_request(portal_setup):
    p1_user = portal_setup['parent_1_user']
    s1 = portal_setup['student_1']
    s2 = portal_setup['student_2']

    client = Client()
    client.force_login(p1_user)

    # 1. Access dashboard, verify both wards are available
    res = client.get(reverse('dashboard_parent'))
    assert res.status_code == 200
    content = res.content.decode()
    assert s1.get_full_name() in content
    assert s2.get_full_name() in content

    # 2. Parent submits child leave request
    leave_data = {
        'apply_child_leave': '1',
        'ward_id': s1.id,
        'from_date': (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
        'to_date': (datetime.date.today() + datetime.timedelta(days=3)).strftime('%Y-%m-%d'),
        'reason': 'Medical checkup in Lahore'
    }
    post_res = client.post(reverse('dashboard_parent'), leave_data)
    assert post_res.status_code == 302

    child_leave = StudentLeaveRequest.objects.filter(student=s1).first()
    assert child_leave is not None
    assert child_leave.status == StudentLeaveStatusChoices.PENDING
    assert child_leave.total_days == 3


@pytest.mark.django_db
def test_id_tampering_and_object_level_permissions(portal_setup):
    s1 = portal_setup['student_1']
    s1_user = portal_setup['student_1_user']
    s3 = portal_setup['student_3']
    s3_user = portal_setup['student_3_user']
    p2_user = portal_setup['parent_2_user']
    doc1 = portal_setup['doc_1']

    client = Client()

    # 1. Student 3 attempts to view Student 1's profile -> Redirected with error
    client.force_login(s3_user)
    tamper_view = client.get(reverse('student_detail', args=[s1.id]))
    assert tamper_view.status_code == 302
    assert tamper_view.url == reverse('dashboard_student')

    # 2. Student 3 attempts to download Student 1's ID Card -> 403 Forbidden
    id_card_tamper = client.get(reverse('student_id_card_pdf', args=[s1.id]))
    assert id_card_tamper.status_code == 403

    # 3. Student 3 attempts to download Student 1's private document -> 403 Forbidden
    doc_tamper = client.get(reverse('student_document_download', args=[doc1.id]))
    assert doc_tamper.status_code == 403

    # 4. Unrelated Parent 2 attempts to download Student 1's document -> 403 Forbidden
    client.force_login(p2_user)
    parent_doc_tamper = client.get(reverse('student_document_download', args=[doc1.id]))
    assert parent_doc_tamper.status_code == 403


@pytest.mark.django_db
def test_forced_password_change_flow(portal_setup):
    school = portal_setup['school']
    user = User.objects.create_user(
        username="new_seeded_user",
        password="TempPassword123!",
        role=RoleChoices.STUDENT,
        school=school,
        must_change_password=True
    )

    client = Client()
    client.force_login(user)

    # 1. Attempt to access dashboard -> Intercepted by middleware and redirected to /change-password/
    res = client.get(reverse('dashboard_student'))
    assert res.status_code == 302
    assert res.url == reverse('change_password')

    # 2. Access change-password page directly -> 200 OK
    res_page = client.get(reverse('change_password'))
    assert res_page.status_code == 200

    # 3. Submit valid new password
    change_res = client.post(reverse('change_password'), {
        'current_password': 'TempPassword123!',
        'new_password': 'BrandNewSecurePassword123!',
        'confirm_password': 'BrandNewSecurePassword123!'
    })
    assert change_res.status_code == 302

    user.refresh_from_db()
    assert user.must_change_password is False
    assert user.check_password('BrandNewSecurePassword123!') is True

