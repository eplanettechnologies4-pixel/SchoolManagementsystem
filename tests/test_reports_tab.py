import pytest
from django.test import Client
from django.urls import reverse
from accounts.models import User, RoleChoices
from academics.models import School


@pytest.fixture
def reports_setup(db):
    school = School.objects.create(
        name="Beaconhouse Model School",
        code="BMS-01",
        latitude=31.5204,
        longitude=74.3587,
        radius_meters=300
    )
    admin = User.objects.create_user(
        username="report_admin",
        role=RoleChoices.ADMIN,
        school=school,
        password="AdminPassword123!"
    )
    teacher = User.objects.create_user(
        username="report_teacher",
        role=RoleChoices.TEACHER,
        school=school,
        password="TeacherPassword123!"
    )
    accountant = User.objects.create_user(
        username="report_accountant",
        role=RoleChoices.ACCOUNTANT,
        school=school,
        password="AccPassword123!"
    )
    student = User.objects.create_user(
        username="report_student",
        role=RoleChoices.STUDENT,
        school=school,
        password="StudentPassword123!"
    )
    return {
        'school': school,
        'admin': admin,
        'teacher': teacher,
        'accountant': accountant,
        'student': student,
    }


@pytest.mark.django_db
def test_reports_hub_view_access(reports_setup):
    """
    Test permissions for the Central Reports Hub:
    Admin, Teacher, and Accountant can view; Student cannot.
    """
    client = Client()

    # 1. Unauthenticated -> Redirect to login
    res = client.get(reverse('reports_hub'))
    assert res.status_code == 302
    assert '/login/' in res.url

    # 2. Admin -> 200 OK
    client.force_login(reports_setup['admin'])
    res = client.get(reverse('reports_hub'))
    assert res.status_code == 200
    assert b"Central Reports" in res.content or b"Reports" in res.content
    assert b"Staff" in res.content and b"Attendance" in res.content
    assert b"Financial" in res.content and b"Fee" in res.content

    # 3. Teacher -> 200 OK
    client.force_login(reports_setup['teacher'])
    res = client.get(reverse('reports_hub'))
    assert res.status_code == 200

    # 4. Accountant -> 200 OK
    client.force_login(reports_setup['accountant'])
    res = client.get(reverse('reports_hub'))
    assert res.status_code == 200

    # 5. Student -> 403 Forbidden
    client.force_login(reports_setup['student'])
    res = client.get(reverse('reports_hub'))
    assert res.status_code == 403


@pytest.mark.django_db
def test_top_reports_tab_rendered_in_base_template(reports_setup):
    """
    Verifies that:
    1. The top app bar header renders the Reports tab.
    2. The dropdown is strictly hidden by default with x-cloak and display: none.
    3. The hover-expandable sidebar renders sub-navigation modules.
    """
    client = Client()
    client.force_login(reports_setup['admin'])

    res = client.get(reverse('reports_hub'))
    assert res.status_code == 200
    content = res.content.decode('utf-8')

    # Top Reports Tab elements
    assert "reportsDropdownOpen" in content
    assert "style=\"display: none;\"" in content
    assert "x-cloak" in content

    # Expandable Sidebar with Subnav
    assert "isExpanded()" in content
    assert "activeSubmenu" in content
    assert "Dashboard" in content
    assert "Students (SIS)" in content
    assert "Academics" in content
    assert "Faculty & Staff" in content
    assert "Fee Management" in content


@pytest.mark.django_db
def test_staff_attendance_excel_no_merged_cell_error(reports_setup):
    """
    Verifies that the Staff Attendance Excel report exports cleanly without 'MergedCell' errors.
    """
    client = Client()
    client.force_login(reports_setup['admin'])

    res = client.get(reverse('staff_attendance_excel'))
    assert res.status_code == 200
    assert res['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert len(res.content) > 1000

