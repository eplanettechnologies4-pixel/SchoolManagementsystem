from accounts.models import AuditLog


def log_audit(user=None, action="UPDATE", instance=None, changes=None, request=None, ip_address=None, school=None, model_name=None, object_id=None, old_values=None, new_values=None):
    """
    Central helper for creating persistent audit log entries.
    Captures actor, action, model, object_id, old/new changes, IP address, and school.
    Supports both direct instance passing and explicit model_name/object_id parameters.
    """
    if request and not ip_address:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')

    if not school:
        school = getattr(instance, 'school', None)
        if not school and user and getattr(user, 'school', None):
            school = user.school

    if instance:
        if not model_name:
            model_name = instance.__class__.__name__
        if not object_id:
            object_id = str(getattr(instance, 'pk', ''))
        object_repr = str(instance)[:255]
    else:
        model_name = model_name or "System"
        object_id = str(object_id or "")
        object_repr = f"{model_name} #{object_id}"

    if not changes:
        changes = {}
        if old_values is not None:
            changes['old'] = old_values
        if new_values is not None:
            changes['new'] = new_values

    return AuditLog.objects.create(
        school=school,
        user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr,
        changes=changes,
        ip_address=ip_address
    )


# ============================================================================
# ROLE & PERMISSION MANAGEMENT SERVICES
# ============================================================================

SYSTEM_PERMISSIONS = [
    # Students / SIS
    ('students.view', 'View Student Directory & Profiles', 'STUDENTS', 'Access student list and view profile cards'),
    ('students.create', 'Student Admission & Creation', 'STUDENTS', 'Register new students via admission wizard'),
    ('students.edit', 'Edit Student Profiles', 'STUDENTS', 'Update student biodata and guardian info'),
    ('students.delete', 'Archive / Delete Students', 'STUDENTS', 'Soft-delete student profiles'),
    ('students.export', 'Generate ID Cards & Certificates', 'STUDENTS', 'Download ID cards, admission letters, leaving certificates'),

    # Academics & Classes
    ('academics.view', 'View Classes, Sections & Subjects', 'ACADEMICS', 'Browse active classes, rosters, and subject syllabi'),
    ('academics.edit', 'Create & Manage Classes/Sections', 'ACADEMICS', 'Add classes, edit sections, configure capacities'),
    ('academics.assignment', 'Teacher Subject Assignments', 'ACADEMICS', 'Assign subjects to teachers and configure periods'),
    ('academics.promote', 'Bulk Student Promotion', 'ACADEMICS', 'Execute end-of-year class promotions with audit rollback'),

    # Faculty & Staff
    ('staff.view', 'View Staff Directory & Profiles', 'STAFF', 'Browse faculty records and employment profiles'),
    ('staff.create', 'Register New Staff Members', 'STAFF', 'Create employee records and teacher logins'),
    ('staff.attendance', 'Staff Check-In & Leave Review', 'STAFF', 'Record GPS check-ins and approve leave requests'),
    ('staff.payroll', 'Manage Staff Payroll & Deductions', 'STAFF', 'Execute monthly payroll, absent/late cuts, and salary slips'),

    # Fees & Financials
    ('fees.view', 'View Fee Dashboard & Defaulters', 'FEES', 'Access fee collection analytics and outstanding lists'),
    ('fees.challans', 'Generate & Manage Fee Challans', 'FEES', 'Issue 3-part bank challans with QR codes'),
    ('fees.collect', 'Record Payments & Disbursements', 'FEES', 'Mark virtual fee payments and salary disbursements'),

    # Reports & Analytics
    ('reports.view', 'Central Reports Hub Access', 'REPORTS', 'Download monthly attendance sheets, rosters, and audit trails'),

    # System & Settings
    ('roles.manage', 'Manage Dynamic Roles & Permissions', 'SETTINGS', 'Create custom roles, edit matrices, and reassign user roles'),
    ('audit.view', 'View Audit Trail & Security Logs', 'SETTINGS', 'Inspect system mutation history, IP addresses, and user actions'),
]


def ensure_default_permissions():
    """
    Ensures all baseline application permissions exist in the database.
    """
    from accounts.models import AppPermission
    created_perms = []
    for code, name, category, desc in SYSTEM_PERMISSIONS:
        perm, _ = AppPermission.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'category': category,
                'description': desc
            }
        )
        created_perms.append(perm)
    return created_perms


def create_custom_role(school, name: str, code: str, base_role: str, description: str = "", permission_codes: list = None, created_by=None):
    """
    Creates a new custom role with assigned permissions.
    """
    from accounts.models import CustomRole, AppPermission
    ensure_default_permissions()

    code = code.strip().upper().replace(' ', '_')
    role, created = CustomRole.objects.get_or_create(
        school=school,
        code=code,
        defaults={
            'name': name,
            'base_role': base_role,
            'description': description
        }
    )
    if not created:
        role.name = name
        role.base_role = base_role
        role.description = description
        role.save()

    if permission_codes is not None:
        perms = AppPermission.objects.filter(code__in=permission_codes)
        role.permissions.set(perms)

    log_audit(
        user=created_by,
        action="CREATE" if created else "UPDATE",
        instance=role,
        changes={'code': role.code, 'name': role.name, 'permissions': permission_codes or []},
        school=school
    )
    return role


def assign_user_role(user, role_code: str = None, custom_role=None, assigned_by=None):
    """
    Updates a user's role and/or custom role dynamically.
    """
    from accounts.models import RoleChoices
    old_role = user.role
    old_custom = user.custom_role.name if user.custom_role else None

    if role_code and role_code in RoleChoices.values:
        user.role = role_code

    if custom_role is not None:
        user.custom_role = custom_role
        if custom_role and custom_role.base_role:
            user.role = custom_role.base_role

    user.save()

    log_audit(
        user=assigned_by,
        action="UPDATE",
        instance=user,
        changes={
            'role': {'old': old_role, 'new': user.role},
            'custom_role': {'old': old_custom, 'new': user.custom_role.name if user.custom_role else None}
        },
        school=user.school
    )
    return user

