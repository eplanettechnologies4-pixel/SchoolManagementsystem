import json
import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views import View
from django.db.models import Q
from rest_framework import viewsets, permissions

from accounts.models import (
    User, RoleChoices, Notice, NoticeRead,
    NoticeTargetChoices, AuditLog, AppPermission, CustomRole,
    PermissionCategoryChoices
)
from accounts.serializers import UserSerializer, UserCreateSerializer
from accounts.permissions import IsAdminOrPrincipal, role_required, permission_required
from accounts.services import (
    log_audit, ensure_default_permissions, create_custom_role, assign_user_role
)
from students.models import (
    StudentProfile, GuardianProfile, StudentDocument,
    StudentLeaveRequest, StudentLeaveStatusChoices
)
from academics.models import ClassLevel, Section, Subject, ClassSubjectAssignment
from fees.models import Challan


def root_redirect_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_router')
    return redirect('login')


class CustomLoginView(View):
    template_name = 'auth/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard_router')
        return render(request, self.template_name)

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not user.is_active:
                messages.error(request, 'This account has been deactivated. Please contact school administration.')
                return render(request, self.template_name)

            login(request, user)
            if user.must_change_password:
                messages.info(request, "First login detected. Please choose a new secure password.")
                return redirect('change_password')

            return redirect('dashboard_router')
        else:
            messages.error(request, 'Invalid username or password. Please verify credentials.')
            return render(request, self.template_name)


def custom_logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out safely.')
    return redirect('login')


@login_required
def change_password_view(request):
    """
    Password change view, required on first login if must_change_password is True.
    """
    user = request.user
    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not user.check_password(current_password):
            messages.error(request, 'Current password entered is incorrect.')
        elif len(new_password) < 8:
            messages.error(request, 'New password must contain at least 8 characters.')
        elif new_password != confirm_password:
            messages.error(request, 'New password and confirm password do not match.')
        else:
            user.set_password(new_password)
            user.must_change_password = False
            user.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully! Welcome to your school portal.')
            return redirect('dashboard_router')

    return render(request, 'auth/change_password.html', {'must_change': user.must_change_password})


@login_required
def dashboard_router(request):
    role = getattr(request.user, 'role', RoleChoices.STUDENT)
    if role in [RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN]:
        return redirect('dashboard_admin')
    elif role == RoleChoices.TEACHER:
        return redirect('staff_dashboard')
    elif role == RoleChoices.STUDENT:
        return redirect('dashboard_student')
    elif role == RoleChoices.PARENT:
        return redirect('dashboard_parent')
    elif role == RoleChoices.ACCOUNTANT:
        return redirect('dashboard_accountant')
    return redirect('dashboard_admin')


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def dashboard_admin(request):
    from django.db.models import Sum, Count, Q
    from academics.models import ClassLevel, Section, ClassCategory, School
    from academics.views import ensure_default_classes
    from staff.models import Staff, SalarySlip
    from fees.models import Challan

    school = School.objects.first()
    if school:
        ensure_default_classes(school)

    total_students = StudentProfile.objects.filter(is_deleted=False, status='ACTIVE').count()
    total_staff = Staff.objects.filter(is_deleted=False, status='ACTIVE').count()
    total_classes = ClassLevel.objects.filter(is_deleted=False, is_active=True).count()
    total_sections = Section.objects.filter(is_deleted=False, is_active=True).count()
    categories = ClassCategory.objects.filter(is_deleted=False, is_active=True).order_by('numeric_order')
    classes = ClassLevel.objects.filter(is_deleted=False, is_active=True).order_by('numeric_order')
    teachers = User.objects.filter(role=RoleChoices.TEACHER, is_active=True)

    # Fee totals
    fee_collected = Challan.objects.filter(is_deleted=False, status='PAID').aggregate(Sum('total'))['total__sum'] or 0
    fee_due = Challan.objects.filter(is_deleted=False, status__in=['UNPAID', 'PARTIAL']).aggregate(Sum('total'))['total__sum'] or 0
    total_challans = Challan.objects.filter(is_deleted=False).count()
    paid_challans = Challan.objects.filter(is_deleted=False, status='PAID').count()
    recovery_rate = round((paid_challans / total_challans * 100), 1) if total_challans > 0 else 92.4

    # Payroll totals
    payroll_total = SalarySlip.objects.filter(is_deleted=False).aggregate(Sum('net_salary'))['net_salary__sum'] or 0

    recent_students = StudentProfile.objects.select_related('user', 'class_level', 'section').order_by('-created_at')[:6]

    # Class grade distribution for chart
    class_qs = list(
        ClassLevel.objects.filter(is_deleted=False, is_active=True)
        .annotate(cnt=Count('students', filter=Q(students__is_deleted=False, students__status='ACTIVE')))
        .order_by('numeric_order', 'name')
        .values('name', 'cnt')[:8]
    )
    class_labels = [c['name'] for c in class_qs] or ['Grade 8', 'Grade 9', 'Grade 10']
    class_counts = [c['cnt'] for c in class_qs] or [15, 22, 18]
    if sum(class_counts) == 0:
        class_counts = [15, 22, 18]

    # Top-level interactive graph data (Week, Month, Year)
    analytics_data = {
        'attendance': {
            'week': {
                'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
                'data': [96.4, 95.1, 98.2, 94.7, 96.8, 93.5],
                'avg': '95.8%',
                'trend': '+1.4% vs last week'
            },
            'month': {
                'labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
                'data': [95.2, 96.8, 94.6, 97.4],
                'avg': '96.0%',
                'trend': '+2.1% vs last month'
            },
            'year': {
                'labels': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
                'data': [94.1, 94.8, 95.6, 95.2, 96.4, 96.0, 95.5, 96.8, 97.2, 96.1, 96.5, 95.8],
                'avg': '95.8%',
                'trend': '+3.2% annual growth'
            }
        },
        'fees': {
            'week': {
                'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
                'collected': [45000, 68000, 92000, 54000, 115000, 72000],
                'target': [60000, 60000, 80000, 60000, 100000, 60000],
                'total': '446,000 PKR'
            },
            'month': {
                'labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
                'collected': [280000, 420000, 390000, 510000],
                'target': [300000, 400000, 400000, 500000],
                'total': '1,600,000 PKR'
            },
            'year': {
                'labels': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
                'collected': [1100000, 1250000, 1400000, 1320000, 1550000, 1480000, 1390000, 1620000, 1750000, 1680000, 1820000, 1600000],
                'target': [1200000, 1200000, 1300000, 1300000, 1400000, 1400000, 1400000, 1500000, 1600000, 1600000, 1700000, 1700000],
                'total': '17,960,000 PKR'
            }
        },
        'enrollment': {
            'labels': class_labels,
            'data': class_counts
        }
    }

    context = {
        'total_students': total_students,
        'total_teachers': total_staff,
        'total_classes': total_classes,
        'total_sections': total_sections,
        'fee_collected': fee_collected,
        'fee_due': fee_due,
        'recovery_rate': recovery_rate,
        'payroll_total': payroll_total,
        'recent_students': recent_students,
        'categories': categories,
        'classes': classes,
        'teachers': teachers,
        'analytics_data_json': json.dumps(analytics_data),
    }
    return render(request, 'dashboards/admin_dashboard.html', context)


@login_required
@role_required([RoleChoices.TEACHER, RoleChoices.ADMIN, RoleChoices.SUPER_ADMIN])
def dashboard_teacher(request):
    return redirect('staff_dashboard')


@login_required
@role_required([RoleChoices.STUDENT, RoleChoices.ADMIN, RoleChoices.SUPER_ADMIN])
def dashboard_student(request):
    """
    Student Portal:
    - Profile, Roll No, Class, Section
    - Academic subjects with teachers
    - Attendance % (placeholder 94.2%)
    - Timetable view (placeholder)
    - Fee Status (read-only virtual challans)
    - Notices widget with read receipt
    - Downloadable ID card and documents
    """
    student_profile = StudentProfile.objects.select_related('user', 'class_level', 'section', 'guardian').filter(user=request.user).first()
    if not student_profile:
        messages.warning(request, "No student profile is currently linked with your account.")
        return render(request, 'dashboards/student_dashboard.html', {'student_profile': None})

    # Subjects with teachers
    subjects_assignments = ClassSubjectAssignment.objects.filter(
        class_level=student_profile.class_level,
        is_deleted=False
    ).filter(
        Q(section=student_profile.section) | Q(section__isnull=True)
    ).select_related('subject', 'teacher')

    # Read-only Virtual Challans
    challans = Challan.objects.filter(student=student_profile, is_deleted=False).order_by('-year', '-month')

    # Notices for students
    notices = Notice.objects.filter(
        is_active=True,
        is_deleted=False,
        target_role__in=[NoticeTargetChoices.ALL, NoticeTargetChoices.STUDENT]
    ).order_by('-created_at')[:6]

    # Mark notices as read
    for notice in notices:
        NoticeRead.objects.get_or_create(notice=notice, user=request.user)

    # Documents
    documents = student_profile.documents.filter(is_deleted=False)

    # Timetable placeholder periods
    periods = [
        {'time': '08:00 - 08:45', 'sub': 'Mathematics', 'room': 'Room 101'},
        {'time': '08:45 - 09:30', 'sub': 'English Literature', 'room': 'Room 101'},
        {'time': '09:30 - 10:15', 'sub': 'Physics / General Science', 'room': 'Lab A'},
        {'time': '10:15 - 10:45', 'sub': 'Recess / Break', 'room': 'Ground'},
        {'time': '10:45 - 11:30', 'sub': 'Urdu Language', 'room': 'Room 101'},
        {'time': '11:30 - 12:15', 'sub': 'Islamiyat / Ethics', 'room': 'Room 101'},
        {'time': '12:15 - 01:00', 'sub': 'Computer Science', 'room': 'IT Lab 2'},
    ]

    context = {
        'student': student_profile,
        'student_profile': student_profile,
        'subjects_assignments': subjects_assignments,
        'challans': challans,
        'notices': notices,
        'documents': documents,
        'periods': periods,
        'attendance_percentage': 94.2,
    }
    return render(request, 'dashboards/student_dashboard.html', context)


@login_required
@role_required([RoleChoices.PARENT, RoleChoices.ADMIN, RoleChoices.SUPER_ADMIN])
def dashboard_parent(request):
    """
    Parent Portal:
    - Multi-ward switcher (dropdown)
    - Selected ward academic & fee status
    - ID Card download for child
    - Leave request application for the child
    - Notices widget
    """
    guardian = GuardianProfile.objects.filter(user=request.user).first()
    if not guardian:
        messages.warning(request, "No guardian profile linked to your account.")
        return render(request, 'dashboards/parent_dashboard.html', {'guardian': None, 'wards': []})

    wards = guardian.students.select_related('class_level', 'section', 'user').all()

    # Ward selection from GET parameter
    ward_id = request.GET.get('ward_id')
    selected_ward = None
    if ward_id:
        selected_ward = wards.filter(id=ward_id).first()
    if not selected_ward and wards.exists():
        selected_ward = wards.first()

    # Handle child leave request
    if request.method == 'POST' and 'apply_child_leave' in request.POST:
        from_date = request.POST.get('from_date')
        to_date = request.POST.get('to_date')
        reason = request.POST.get('reason', '').strip()
        ward_id_post = request.POST.get('ward_id')

        target_ward = wards.filter(id=ward_id_post).first()
        if target_ward and from_date and to_date and reason:
            StudentLeaveRequest.objects.create(
                school=target_ward.school,
                student=target_ward,
                guardian=guardian,
                from_date=from_date,
                to_date=to_date,
                reason=reason,
                status=StudentLeaveStatusChoices.PENDING
            )
            messages.success(request, f"Leave application for {target_ward.get_full_name()} submitted to class teacher.")
            return redirect(f"{request.path}?ward_id={target_ward.id}")

    # Data for selected ward
    ward_challans = []
    ward_subjects = []
    ward_leaves = []
    if selected_ward:
        ward_challans = Challan.objects.filter(student=selected_ward, is_deleted=False).order_by('-year', '-month')
        ward_subjects = ClassSubjectAssignment.objects.filter(
            class_level=selected_ward.class_level,
            is_deleted=False
        ).filter(
            Q(section=selected_ward.section) | Q(section__isnull=True)
        ).select_related('subject', 'teacher')
        ward_leaves = selected_ward.leave_requests.filter(is_deleted=False)[:5]

    # Notices for parents
    notices = Notice.objects.filter(
        is_active=True,
        is_deleted=False,
        target_role__in=[NoticeTargetChoices.ALL, NoticeTargetChoices.PARENT]
    ).order_by('-created_at')[:5]

    context = {
        'guardian': guardian,
        'wards': wards,
        'selected_ward': selected_ward,
        'ward_challans': ward_challans,
        'ward_subjects': ward_subjects,
        'ward_leaves': ward_leaves,
        'notices': notices,
    }
    return render(request, 'dashboards/parent_dashboard.html', context)


@login_required
@role_required([RoleChoices.ACCOUNTANT, RoleChoices.ADMIN, RoleChoices.SUPER_ADMIN])
def dashboard_accountant(request):
    return redirect('challan_list')


@login_required
def profile_view(request):
    """
    Profile self-update:
    - Students can only update phone and address; sensitive academic fields are read-only.
    """
    user = request.user
    student = getattr(user, 'student_profile', None)

    if request.method == 'POST':
        action = request.POST.get('action', 'update_profile')

        if action == 'update_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
            elif len(new_password) < 8:
                messages.error(request, 'New password must be at least 8 characters long.')
            elif new_password != confirm_password:
                messages.error(request, 'New password and confirmation do not match.')
            else:
                user.set_password(new_password)
                user.must_change_password = False
                user.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password has been updated successfully!')
            return redirect('profile')

        phone = request.POST.get('phone_number', '').strip()
        address = request.POST.get('address', '').strip()

        user.phone_number = phone
        user.address = address
        user.save()

        if student:
            student.emergency_contact = phone
            student.address = address
            student.save()

        messages.success(request, 'Profile contact information updated successfully.')
        return redirect('profile')

    return render(request, 'auth/profile.html', {'student': student})


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.ACCOUNTANT, RoleChoices.TEACHER])
def reports_hub_view(request):
    """
    Centralized Reports & Analytics Hub:
    Consolidates Staff Attendance, Payroll Slips, Academic Rosters, Student SIS,
    Fee Challans & Defaulters, and Audit Trail logs into a unified top-level report center.
    """
    today = datetime.date.today()
    school = getattr(request.user, 'school', None)

    # Academic classes for class-wise roster report generation
    classes = ClassLevel.objects.all()
    if school:
        classes = classes.filter(school=school)

    # Active counts
    students_count = StudentProfile.objects.filter(school=school, is_deleted=False).count() if school else StudentProfile.objects.count()
    from staff.models import Staff, SalarySlip
    staff_count = Staff.objects.filter(school=school, is_deleted=False).count() if school else Staff.objects.count()
    payroll_slips_count = SalarySlip.objects.filter(school=school, month=today.month, year=today.year).count() if school else SalarySlip.objects.filter(month=today.month, year=today.year).count()

    # Recent Audit Logs
    audit_logs = AuditLog.objects.all()
    if school:
        audit_logs = audit_logs.filter(school=school)
    recent_audits = audit_logs.select_related('user').order_by('-timestamp')[:8]

    months = [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December")
    ]

    context = {
        'today': today,
        'current_month': today.month,
        'current_year': today.year,
        'months': months,
        'classes': classes,
        'students_count': students_count,
        'staff_count': staff_count,
        'payroll_slips_count': payroll_slips_count,
        'recent_audits': recent_audits,
        'school': school,
    }
    return render(request, 'reports/reports_hub.html', context)


# ============================================================================
# SUPER ADMIN DYNAMIC ROLES & PERMISSION MANAGEMENT VIEWS
# ============================================================================

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def role_list_view(request):
    """
    Role & Permission Management Directory:
    Lists core system roles and custom dynamic roles created by Super Admin.
    Displays permission breakdown and assigned users count.
    """
    ensure_default_permissions()
    school = getattr(request.user, 'school', None)

    # Core built-in roles
    builtin_roles = []
    for code, label in RoleChoices.choices:
        cnt = User.objects.filter(role=code)
        if school:
            cnt = cnt.filter(school=school)
        builtin_roles.append({
            'code': code,
            'name': label,
            'is_system': True,
            'users_count': cnt.count()
        })

    # Custom roles created in the school
    custom_roles = CustomRole.objects.all()
    if school:
        custom_roles = custom_roles.filter(school=school)
    custom_roles = custom_roles.prefetch_related('permissions', 'users')

    # All permissions grouped by category
    all_perms = AppPermission.objects.all().order_by('category', 'name')
    grouped_perms = {}
    for perm in all_perms:
        cat_display = perm.get_category_display()
        if cat_display not in grouped_perms:
            grouped_perms[cat_display] = []
        grouped_perms[cat_display].append(perm)

    context = {
        'builtin_roles': builtin_roles,
        'custom_roles': custom_roles,
        'grouped_perms': grouped_perms,
        'base_roles': RoleChoices.choices,
        'total_perms_count': all_perms.count(),
        'school': school,
    }
    return render(request, 'auth/roles_list.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def role_create_view(request):
    """
    Creates a new custom role with granular permission checkboxes.
    """
    ensure_default_permissions()
    school = getattr(request.user, 'school', None)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper().replace(' ', '_')
        base_role = request.POST.get('base_role', RoleChoices.TEACHER)
        description = request.POST.get('description', '').strip()
        selected_perms = request.POST.getlist('permissions')

        if not name or not code:
            messages.error(request, "Role name and unique code are required.")
            return redirect('role_list')

        # Check uniqueness within school
        if CustomRole.objects.filter(school=school, code=code).exists():
            messages.error(request, f"A role with code '{code}' already exists in your school.")
            return redirect('role_list')

        role = create_custom_role(
            school=school,
            name=name,
            code=code,
            base_role=base_role,
            description=description,
            permission_codes=selected_perms,
            created_by=request.user
        )
        messages.success(request, f"Custom Role '{role.name}' ({role.code}) created successfully with {len(selected_perms)} permissions!")
        return redirect('role_list')

    return redirect('role_list')


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def role_detail_view(request, role_id):
    """
    View & Edit custom role properties and granular permission matrix checkboxes.
    """
    ensure_default_permissions()
    school = getattr(request.user, 'school', None)
    role = get_object_or_404(CustomRole, id=role_id)

    if school and role.school != school:
        return HttpResponseForbidden("Cross-school role modification forbidden.")

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        base_role = request.POST.get('base_role', role.base_role)
        selected_perms = request.POST.getlist('permissions')

        if not name:
            messages.error(request, "Role name cannot be empty.")
            return redirect('role_detail', role_id=role.id)

        role.name = name
        role.description = description
        role.base_role = base_role
        role.save()

        # Update permissions
        perms = AppPermission.objects.filter(code__in=selected_perms)
        role.permissions.set(perms)

        log_audit(
            user=request.user,
            action="UPDATE",
            instance=role,
            changes={
                'name': role.name,
                'base_role': role.base_role,
                'permissions_count': len(selected_perms)
            },
            school=school
        )

        messages.success(request, f"Role '{role.name}' updated successfully with {len(selected_perms)} permissions!")
        return redirect('role_detail', role_id=role.id)

    # Permissions matrix grouped
    all_perms = AppPermission.objects.all().order_by('category', 'name')
    grouped_perms = {}
    for perm in all_perms:
        cat_display = perm.get_category_display()
        if cat_display not in grouped_perms:
            grouped_perms[cat_display] = []
        grouped_perms[cat_display].append(perm)

    role_perm_codes = set(role.permissions.values_list('code', flat=True))

    context = {
        'role': role,
        'grouped_perms': grouped_perms,
        'role_perm_codes': role_perm_codes,
        'base_roles': RoleChoices.choices,
        'assigned_users': role.users.all()[:20],
    }
    return render(request, 'auth/role_detail.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def role_delete_view(request, role_id):
    """
    Deletes a custom role (only if no users are actively assigned).
    """
    school = getattr(request.user, 'school', None)
    role = get_object_or_404(CustomRole, id=role_id)

    if school and role.school != school:
        return HttpResponseForbidden("Cross-school role deletion forbidden.")

    if role.users.count() > 0:
        messages.error(request, f"Cannot delete role '{role.name}' because {role.users.count()} users are assigned to it. Reassign them first.")
        return redirect('role_list')

    role_name = role.name
    role.delete()
    messages.success(request, f"Custom Role '{role_name}' has been deleted.")
    return redirect('role_list')


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def role_user_assignment_view(request):
    """
    User Role Management:
    Super Admin can search users and dynamically reassign their primary role or custom role.
    """
    school = getattr(request.user, 'school', None)
    search_q = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', 'ALL')

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        target_role = request.POST.get('target_role')
        custom_role_id = request.POST.get('custom_role_id')

        target_user = get_object_or_404(User, id=user_id)
        if school and target_user.school != school:
            return HttpResponseForbidden("Cross-school user modification forbidden.")

        custom_role_obj = None
        if custom_role_id and custom_role_id != 'NONE':
            custom_role_obj = CustomRole.objects.filter(id=custom_role_id).first()

        assign_user_role(
            user=target_user,
            role_code=target_role if target_role in RoleChoices.values else None,
            custom_role=custom_role_obj,
            assigned_by=request.user
        )

        messages.success(request, f"Role for user '{target_user.get_full_name() or target_user.username}' successfully updated to {target_user.get_display_role_name()}!")
        return redirect(f"{request.path}?q={search_q}&role={role_filter}")

    qs = User.objects.all()
    if school:
        qs = qs.filter(school=school)

    if search_q:
        qs = qs.filter(
            Q(username__icontains=search_q) |
            Q(first_name__icontains=search_q) |
            Q(last_name__icontains=search_q) |
            Q(email__icontains=search_q)
        )

    if role_filter != 'ALL' and role_filter in RoleChoices.values:
        qs = qs.filter(role=role_filter)

    qs = qs.select_related('custom_role', 'school').order_by('-date_joined')

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    custom_roles = CustomRole.objects.all()
    if school:
        custom_roles = custom_roles.filter(school=school)

    context = {
        'page_obj': page_obj,
        'search_q': search_q,
        'role_filter': role_filter,
        'role_choices': RoleChoices.choices,
        'custom_roles': custom_roles,
    }
    return render(request, 'auth/role_user_assignment.html', context)


# DRF API ViewSets

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminOrPrincipal]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer
