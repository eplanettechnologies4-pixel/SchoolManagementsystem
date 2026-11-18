import datetime
import io
import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from accounts.models import User, RoleChoices
from academics.models import School, AcademicYear, ClassLevel, Section, Subject
from students.models import StudentProfile, GuardianProfile
from academics.services.promotion_service import preview_promotion, execute_promotion, rollback_promotion
from academics.services.class_export_import import export_class_list_pdf, export_class_list_excel, import_classes_csv


@pytest.fixture
def setup_academic_data(db):
    school = School.objects.create(name='Islamabad Model Campus', code='IMC-01', address='H-8 Islamabad', phone='051111222', email='info@imc.edu.pk')
    ay1 = AcademicYear.objects.create(school=school, name='2026-2027', start_date=datetime.date(2026, 8, 1), end_date=datetime.date(2027, 6, 30), is_current=True)
    c9 = ClassLevel.objects.create(school=school, name='Class 9', code='C9', numeric_order=9, description="Secondary Class 9")
    c10 = ClassLevel.objects.create(school=school, name='Class 10', code='C10', numeric_order=10, description="Matric Final Class 10")

    sec9a = Section.objects.create(class_level=c9, name='Section A', capacity=5, room_number='Room 9A')
    sec10a = Section.objects.create(class_level=c10, name='Section A', capacity=5, room_number='Room 10A')

    admin = User.objects.create_user(username='admin_acad', password='Password123!', role=RoleChoices.ADMIN, school=school)
    teacher = User.objects.create_user(username='teacher_sci', password='Password123!', role=RoleChoices.TEACHER, school=school)

    # Students in Class 9
    students = []
    for i in range(1, 4):
        u = User.objects.create_user(username=f'stu_c9_{i}', password='Password123!', role=RoleChoices.STUDENT, school=school)
        sp = StudentProfile.objects.create(
            user=u,
            admission_number=f'ADM-2026-00{i}',
            roll_number=f'C9A-0{i}',
            class_level=c9,
            section=sec9a,
            status='ACTIVE'
        )
        students.append(sp)

    sub = Subject.objects.create(
        school=school,
        class_level=c9,
        name='Physics',
        code='PHY-9',
        credit_hours=4,
        is_optional=False,
        assigned_teacher=teacher
    )

    return {
        'school': school,
        'ay1': ay1,
        'c9': c9,
        'c10': c10,
        'sec9a': sec9a,
        'sec10a': sec10a,
        'admin': admin,
        'teacher': teacher,
        'students': students,
        'subject': sub,
    }


@pytest.mark.django_db
def test_section_capacity_validation_and_display(setup_academic_data):
    data = setup_academic_data
    sec = data['sec9a']
    assert sec.current_enrollment_count == 3
    assert sec.enrollment_display == "3/5 filled"
    assert sec.is_full is False

    # Capacity cannot be less than enrolled students
    sec.capacity = 2
    with pytest.raises(ValidationError):
        sec.clean()


@pytest.mark.django_db
def test_single_active_academic_year(setup_academic_data):
    data = setup_academic_data
    school = data['school']
    assert AcademicYear.objects.filter(school=school, is_current=True).count() == 1

    # Creating a new current year automatically deactivates previous
    ay2 = AcademicYear.objects.create(
        school=school,
        name='2027-2028',
        start_date=datetime.date(2027, 8, 1),
        end_date=datetime.date(2028, 6, 30),
        is_current=True
    )
    assert AcademicYear.objects.filter(school=school, is_current=True).count() == 1
    data['ay1'].refresh_from_db()
    assert data['ay1'].is_current is False
    assert ay2.is_current is True


@pytest.mark.django_db
def test_student_promotion_and_audit_rollback(setup_academic_data):
    data = setup_academic_data
    c9 = data['c9']
    c10 = data['c10']
    sec10a = data['sec10a']
    students = data['students']

    # Preview promotion
    preview = preview_promotion(from_class_id=c9.id, to_class_id=c10.id)
    assert preview['total_students'] == 3
    assert len(preview['section_capacities']) == 1

    # Execute promotion with 1 student held back (student 3)
    held_back_id = students[2].id
    res = execute_promotion(
        from_class_id=c9.id,
        to_class_id=c10.id,
        target_section_id=sec10a.id,
        hold_back_ids=[held_back_id],
        user=data['admin']
    )
    assert res['promoted_count'] == 2
    assert res['held_back_count'] == 1

    students[0].refresh_from_db()
    students[1].refresh_from_db()
    students[2].refresh_from_db()

    assert students[0].class_level == c10
    assert students[1].class_level == c10
    assert students[2].class_level == c9  # Held back

    # Rollback promotion via AuditLog
    rollback_res = rollback_promotion(audit_log_id=res['audit_log_id'], user=data['admin'])
    assert rollback_res['reverted_count'] == 2

    students[0].refresh_from_db()
    students[1].refresh_from_db()
    assert students[0].class_level == c9
    assert students[1].class_level == c9


@pytest.mark.django_db
def test_class_export_pdf_and_excel(setup_academic_data):
    data = setup_academic_data
    c9 = data['c9']

    pdf_bytes = export_class_list_pdf(c9)
    assert isinstance(pdf_bytes, bytes)
    assert b'%PDF' in pdf_bytes

    excel_bytes = export_class_list_excel(c9)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 500


@pytest.mark.django_db
def test_class_import_csv(setup_academic_data):
    data = setup_academic_data
    school = data['school']

    csv_content = (
        "class_name,class_code,numeric_order,section_name,capacity,room_number\n"
        "Class 7,C7,7,Section A,35,Room 7A\n"
        "Class 8,C8,8,Section B,30,Room 8B\n"
    )
    file_obj = io.BytesIO(csv_content.encode('utf-8'))
    report = import_classes_csv(file_obj, school=school)

    assert report['classes_created'] == 2
    assert report['sections_created'] == 2
    assert len(report['errors']) == 0
    assert ClassLevel.objects.filter(school=school, code='C7').exists()


@pytest.mark.django_db
def test_class_category_creation_and_filtering(setup_academic_data):
    from academics.models import ClassCategory
    data = setup_academic_data
    school = data['school']
    admin = data['admin']

    client = Client()
    client.force_login(admin)

    # 1. Create Class Category via POST action
    resp = client.post('/academics/classes/', {
        'action': 'create_category',
        'name': 'Primary Wing',
        'code': 'PRI',
        'numeric_order': 2,
        'description': 'Classes 1 through 5'
    }, follow=True)
    assert resp.status_code == 200
    category = ClassCategory.objects.filter(code='PRI').first()
    assert category is not None
    assert category.name == 'Primary Wing'

    # 2. Create Class with Category
    resp_class = client.post('/academics/classes/', {
        'action': 'create_class',
        'name': 'Class 11',
        'code': 'C11',
        'numeric_order': 14,
        'category': category.id,
        'description': 'Grade 11 Higher Secondary'
    }, follow=True)
    assert resp_class.status_code == 200
    cls = ClassLevel.objects.filter(code='C11').first()
    assert cls is not None
    assert cls.category == category


