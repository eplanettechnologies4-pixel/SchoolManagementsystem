import pytest
from django.test import Client
from django.urls import reverse
from django.core.exceptions import PermissionDenied

from accounts.models import User, RoleChoices, CustomRole, AppPermission
from academics.models import School
from accounts.services import (
    ensure_default_permissions, create_custom_role, assign_user_role
)
from accounts.permissions import permission_required


@pytest.fixture
def rbac_setup(db):
    school = School.objects.create(
        name="Aitchison College",
        code="AC-01",
        latitude=31.5204,
        longitude=74.3587,
        radius_meters=300
    )
    super_admin = User.objects.create_user(
        username="super_admin_user",
        role=RoleChoices.SUPER_ADMIN,
        school=school,
        password="SuperAdminPass123!"
    )
    teacher = User.objects.create_user(
        username="teacher_bilal",
        first_name="Bilal",
        last_name="Khan",
        role=RoleChoices.TEACHER,
        school=school,
        password="TeacherPass123!"
    )
    student = User.objects.create_user(
        username="student_zain",
        role=RoleChoices.STUDENT,
        school=school,
        password="StudentPass123!"
    )
    return {
        'school': school,
        'super_admin': super_admin,
        'teacher': teacher,
        'student': student,
    }


@pytest.mark.django_db
def test_default_permissions_seeded(rbac_setup):
    """
    Verifies that system permissions across all categories are seeded correctly.
    """
    perms = ensure_default_permissions()
    assert len(perms) >= 15

    codes = [p.code for p in perms]
    assert 'students.view' in codes
    assert 'students.create' in codes
    assert 'staff.payroll' in codes
    assert 'fees.collect' in codes
    assert 'roles.manage' in codes


@pytest.mark.django_db
def test_create_custom_role_with_permissions(rbac_setup):
    """
    Super Admin creates a custom role 'Vice Principal' with specific permissions.
    """
    school = rbac_setup['school']
    admin = rbac_setup['super_admin']

    role = create_custom_role(
        school=school,
        name="Vice Principal",
        code="VICE_PRINCIPAL",
        base_role=RoleChoices.ADMIN,
        description="Assists Principal in academic operations",
        permission_codes=['students.create', 'academics.edit', 'staff.attendance'],
        created_by=admin
    )

    assert role.name == "Vice Principal"
    assert role.code == "VICE_PRINCIPAL"
    assert role.base_role == RoleChoices.ADMIN
    assert role.permissions.count() == 3

    perm_codes = list(role.permissions.values_list('code', flat=True))
    assert 'students.create' in perm_codes
    assert 'staff.attendance' in perm_codes


@pytest.mark.django_db
def test_assign_custom_role_to_user_and_check_permissions(rbac_setup):
    """
    Assigning a custom role dynamically grants configured permissions to a user.
    """
    school = rbac_setup['school']
    admin = rbac_setup['super_admin']
    teacher = rbac_setup['teacher']

    role = create_custom_role(
        school=school,
        name="Exam Controller",
        code="EXAM_CONTROLLER",
        base_role=RoleChoices.TEACHER,
        permission_codes=['academics.view', 'academics.edit', 'reports.view'],
        created_by=admin
    )

    assign_user_role(
        user=teacher,
        custom_role=role,
        assigned_by=admin
    )

    teacher.refresh_from_db()
    assert teacher.custom_role == role
    assert teacher.get_display_role_name() == "Exam Controller"

    # User now has permissions granted by custom role
    assert teacher.has_app_permission('academics.edit') is True
    assert teacher.has_app_permission('reports.view') is True

    # User does NOT have ungranted permissions
    assert teacher.has_app_permission('staff.payroll') is False
    assert teacher.has_app_permission('fees.challans') is False


@pytest.mark.django_db
def test_role_management_view_access(rbac_setup):
    """
    Verifies that only Super Admin / Admin can access Role & RBAC pages.
    Teachers and Students are blocked (403 Forbidden).
    """
    client = Client()
    admin = rbac_setup['super_admin']
    teacher = rbac_setup['teacher']
    student = rbac_setup['student']

    # 1. Super Admin access -> 200 OK
    client.force_login(admin)
    res_admin = client.get(reverse('role_list'))
    assert res_admin.status_code == 200
    assert b"Roles &amp; Permissions Management" in res_admin.content or b"Roles" in res_admin.content

    res_users = client.get(reverse('role_user_assignment'))
    assert res_users.status_code == 200

    # 2. Teacher access -> 403 Forbidden
    client.force_login(teacher)
    res_teacher = client.get(reverse('role_list'))
    assert res_teacher.status_code == 403

    # 3. Student access -> 403 Forbidden
    client.force_login(student)
    res_student = client.get(reverse('role_list'))
    assert res_student.status_code == 403


@pytest.mark.django_db
def test_role_user_assignment_action(rbac_setup):
    """
    Super Admin can reassign a user's role via the role_user_assignment POST view.
    """
    client = Client()
    admin = rbac_setup['super_admin']
    teacher = rbac_setup['teacher']
    school = rbac_setup['school']

    # Create a custom role
    role = create_custom_role(
        school=school,
        name="Senior Coordinator",
        code="SENIOR_COORD",
        base_role=RoleChoices.TEACHER,
        permission_codes=['students.create', 'reports.view'],
        created_by=admin
    )

    client.force_login(admin)
    res = client.post(reverse('role_user_assignment'), {
        'user_id': teacher.id,
        'target_role': RoleChoices.TEACHER,
        'custom_role_id': role.id
    })
    assert res.status_code == 302

    teacher.refresh_from_db()
    assert teacher.custom_role == role
    assert teacher.has_app_permission('students.create') is True


@pytest.mark.django_db
def test_permission_required_decorator(rbac_setup):
    """
    Verifies that @permission_required decorator enforces access based on has_app_permission.
    """
    teacher = rbac_setup['teacher']
    admin = rbac_setup['super_admin']

    @permission_required('staff.payroll')
    def dummy_payroll_view(request):
        return "SUCCESS"

    class MockRequest:
        def __init__(self, user):
            self.user = user

    # Admin has all permissions
    req_admin = MockRequest(admin)
    assert dummy_payroll_view(req_admin) == "SUCCESS"

    # Teacher without staff.payroll permission raises PermissionDenied
    req_teacher = MockRequest(teacher)
    with pytest.raises(PermissionDenied):
        dummy_payroll_view(req_teacher)

