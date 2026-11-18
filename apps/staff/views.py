import json
import datetime
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden, Http404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from accounts.models import User, RoleChoices
from accounts.permissions import role_required, IsAdminOrPrincipal
from accounts.services import log_audit
from academics.models import ClassSubjectAssignment
from staff.models import (
    Staff, StaffAttendance, StaffDocument, LeaveType,
    LeaveRequest, ShiftTiming, AttendanceStatusChoices,
    LeaveStatusChoices, AttendanceMethodChoices, SalarySlip,
    SalarySlipStatusChoices, SalaryPaymentMethodChoices, LateDeductionPolicyChoices
)
from staff.forms import (
    StaffForm, LeaveRequestForm, LeaveReviewForm, StaffDocumentForm,
    PayrollGenerateForm, SalarySlipPaymentForm
)
from staff.services.attendance_service import (
    record_staff_check_in, record_staff_check_out,
    get_staff_tracking_today, export_staff_attendance_pdf,
    export_staff_attendance_excel, generate_employee_id_atomic
)
from staff.services.payroll_hooks import get_monthly_staff_attendance_summary
from staff.services.payroll_service import (
    calculate_staff_monthly_salary, generate_bulk_payroll,
    mark_salary_slip_paid, generate_payslip_pdf
)



@login_required
def staff_dashboard_view(request):
    """
    Teacher / Staff Portal Dashboard:
    - Today's check-in/out button with GPS capture
    - 'Aaj ki classes' (Today's classes / assigned subjects)
    - Attendance summary for this month
    - Leave balance and quick leave application
    """
    staff = getattr(request.user, 'staff_profile', None)
    if not staff:
        if request.user.role in [RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN]:
            return redirect('staff_tracking_dashboard')
        messages.error(request, "Staff profile not linked to this account.")
        return redirect('dashboard')

    today = datetime.date.today()
    today_att = StaffAttendance.objects.filter(staff=staff, date=today).first()

    # Aaj ki classes (ClassSubjectAssignment for this teacher)
    assigned_classes = ClassSubjectAssignment.objects.filter(
        teacher=request.user,
        is_deleted=False
    ).select_related('class_level', 'section', 'subject')

    # Monthly attendance summary
    now = timezone.localtime(timezone.now())
    payroll_summary = get_monthly_staff_attendance_summary(staff, now.month, now.year)

    # Leave balance
    leave_types = LeaveType.objects.filter(school=staff.school, is_active=True)
    leave_balances = []
    for lt in leave_types:
        used = LeaveRequest.objects.filter(
            staff=staff,
            leave_type=lt,
            status=LeaveStatusChoices.APPROVED,
            from_date__year=now.year
        )
        days_used = sum([req.total_days for req in used])
        leave_balances.append({
            'name': lt.name,
            'allowed': lt.days_per_year,
            'used': days_used,
            'remaining': max(0, lt.days_per_year - days_used)
        })

    recent_leaves = staff.leave_requests.filter(is_deleted=False)[:5]
    leave_form = LeaveRequestForm()

    # Staff Compensation & Salary Slips
    recent_salary_slips = staff.salary_slips.filter(is_deleted=False)[:6]
    current_month_slip = staff.salary_slips.filter(month=now.month, year=now.year).first()

    context = {
        'staff': staff,
        'today': today,
        'today_att': today_att,
        'assigned_classes': assigned_classes,
        'payroll_summary': payroll_summary,
        'leave_balances': leave_balances,
        'recent_leaves': recent_leaves,
        'leave_form': leave_form,
        'recent_salary_slips': recent_salary_slips,
        'current_month_slip': current_month_slip,
        'school': staff.school,
    }
    return render(request, 'staff/staff_dashboard.html', context)


@login_required
def staff_check_in_action(request):
    """
    Handles staff check-in with GPS coordinates.
    """
    staff = getattr(request.user, 'staff_profile', None)
    if not staff:
        return JsonResponse({'success': False, 'message': 'Staff profile not found'}, status=400)

    if request.method == 'POST':
        lat = request.POST.get('latitude')
        lng = request.POST.get('longitude')
        try:
            lat = float(lat) if lat else None
            lng = float(lng) if lng else None
        except ValueError:
            lat, lng = None, None

        att, created, is_out_of_range = record_staff_check_in(staff, lat=lat, lng=lng, method='GPS', marked_by=request.user)

        if is_out_of_range:
            messages.warning(request, f"Checked in successfully at {att.check_in.strftime('%H:%M')}, but GPS location was outside allowed school radius.")
        else:
            messages.success(request, f"Checked in successfully at {att.check_in.strftime('%H:%M')} (Status: {att.get_status_display()}).")

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
            return JsonResponse({
                'success': True,
                'check_in': att.check_in.strftime('%H:%M'),
                'status': att.get_status_display(),
                'is_out_of_range': is_out_of_range
            })

    return redirect('staff_dashboard')


@login_required
def staff_check_out_action(request):
    """
    Handles staff check-out.
    """
    staff = getattr(request.user, 'staff_profile', None)
    if not staff:
        return JsonResponse({'success': False, 'message': 'Staff profile not found'}, status=400)

    if request.method == 'POST':
        att = record_staff_check_out(staff)
        messages.success(request, f"Checked out successfully at {att.check_out.strftime('%H:%M')}.")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'check_out': att.check_out.strftime('%H:%M')})

    return redirect('staff_dashboard')


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def staff_tracking_dashboard(request):
    """
    Admin & Principal live staff tracking dashboard with Leaflet map.
    """
    date_str = request.GET.get('date')
    if date_str:
        try:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = datetime.date.today()
    else:
        target_date = datetime.date.today()

    metrics = get_staff_tracking_today(school=request.user.school, date=target_date)

    context = {
        'metrics': metrics,
        'locations_json': json.dumps(metrics['locations']),
        'target_date': target_date,
        'school': request.user.school,
    }
    return render(request, 'staff/staff_tracking_dashboard.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def staff_list_view(request):
    """
    Staff directory with department filters and search.
    """
    query = request.GET.get('q', '').strip()
    department = request.GET.get('department')
    status = request.GET.get('status')

    qs = Staff.objects.select_related('user', 'shift').all()
    if request.user.school:
        qs = qs.filter(school=request.user.school)

    if query:
        qs = qs.filter(
            user__first_name__icontains=query
        ) | qs.filter(
            user__last_name__icontains=query
        ) | qs.filter(
            employee_id__icontains=query
        ) | qs.filter(
            designation__icontains=query
        )

    if department:
        qs = qs.filter(department=department)
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    departments = Staff.objects.filter(school=request.user.school).values_list('department', flat=True).distinct()

    context = {
        'staff_list': page_obj,
        'departments': [d for d in departments if d],
        'query': query,
        'selected_dept': department,
        'selected_status': status,
    }
    return render(request, 'staff/staff_list.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def staff_create_view(request):
    """
    Registers a new staff member with auto-generated Employee ID.
    """
    if request.method == 'POST':
        form = StaffForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                first_name = form.cleaned_data['first_name']
                last_name = form.cleaned_data['last_name']
                email = form.cleaned_data['email']
                emp_id = generate_employee_id_atomic(school=request.user.school)

                # Create User account
                username = f"emp_{emp_id.lower().replace('-', '_')}"
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    password="StaffPassword123!",
                    role=RoleChoices.TEACHER,
                    school=request.user.school,
                    phone_number=form.cleaned_data.get('phone', ''),
                    cnic_bform=form.cleaned_data.get('cnic', ''),
                    address=form.cleaned_data.get('address', ''),
                    must_change_password=True
                )

                staff = form.save(commit=False)
                staff.user = user
                staff.school = request.user.school
                staff.employee_id = emp_id
                staff.save()

                log_audit(
                    user=request.user,
                    action="CREATE",
                    model_name="Staff",
                    object_id=staff.id,
                    new_values={'employee_id': emp_id, 'name': staff.get_full_name(), 'designation': staff.designation},
                    request=request
                )

                messages.success(request, f"Staff member '{staff.get_full_name()}' created successfully! Employee ID: {emp_id}")
                return redirect('staff_detail', staff_id=staff.id)
    else:
        form = StaffForm()

    return render(request, 'staff/staff_form.html', {'form': form})


@login_required
def staff_detail_view(request, staff_id):
    """
    Staff profile page with documents, attendance summary, and assigned classes.
    """
    staff = get_object_or_404(Staff.objects.select_related('user', 'shift', 'school'), id=staff_id)
    
    # Ownership / RBAC check
    if request.user.role == RoleChoices.TEACHER and getattr(request.user, 'staff_profile', None) != staff:
        return HttpResponseForbidden("Access denied. You can only view your own profile.")

    assigned_classes = ClassSubjectAssignment.objects.filter(
        teacher=staff.user,
        is_deleted=False
    ).select_related('class_level', 'section', 'subject')

    now = timezone.localtime(timezone.now())
    payroll_summary = get_monthly_staff_attendance_summary(staff, now.month, now.year)
    documents = staff.documents.filter(is_deleted=False)

    context = {
        'staff': staff,
        'assigned_classes': assigned_classes,
        'payroll_summary': payroll_summary,
        'documents': documents,
    }
    return render(request, 'staff/staff_detail.html', context)


@login_required
def staff_leave_apply_view(request):
    """
    Staff submits a leave application.
    """
    staff = getattr(request.user, 'staff_profile', None)
    if not staff:
        messages.error(request, "Only staff members can apply for leave.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.school = staff.school
            leave.staff = staff
            leave.status = LeaveStatusChoices.PENDING
            leave.save()
            messages.success(request, "Leave request submitted successfully. Awaiting administration approval.")
            return redirect('staff_dashboard')
    else:
        form = LeaveRequestForm()

    return render(request, 'staff/leave_apply.html', {'form': form})


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def staff_leave_review_view(request, leave_id):
    """
    Admin/Principal approves or rejects a staff leave request.
    """
    leave = get_object_or_404(LeaveRequest, id=leave_id)

    if request.method == 'POST':
        form = LeaveReviewForm(request.POST)
        if form.is_valid():
            leave.status = form.cleaned_data['status']
            leave.review_comments = form.cleaned_data['review_comments']
            leave.approved_by = request.user
            leave.save()

            log_audit(
                user=request.user,
                action="UPDATE",
                model_name="LeaveRequest",
                object_id=leave.id,
                new_values={'status': leave.status, 'comments': leave.review_comments},
                request=request
            )

            messages.success(request, f"Leave request for {leave.staff.get_full_name()} marked as {leave.status}.")
            return redirect('staff_tracking_dashboard')
    else:
        form = LeaveReviewForm(initial={'status': leave.status, 'review_comments': leave.review_comments})

    return render(request, 'staff/leave_review.html', {'leave': leave, 'form': form})


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def staff_attendance_pdf_view(request):
    """
    Exports monthly staff attendance report PDF.
    """
    month = int(request.GET.get('month', datetime.date.today().month))
    year = int(request.GET.get('year', datetime.date.today().year))
    pdf_bytes = export_staff_attendance_pdf(request.user.school, month=month, year=year)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Staff_Attendance_{month}_{year}.pdf"'
    return response


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def staff_attendance_excel_view(request):
    """
    Exports monthly staff attendance report Excel file.
    """
    month = int(request.GET.get('month', datetime.date.today().month))
    year = int(request.GET.get('year', datetime.date.today().year))
    excel_io = export_staff_attendance_excel(request.user.school, month=month, year=year)
    response = HttpResponse(excel_io.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Staff_Attendance_{month}_{year}.xlsx"'
    return response


# ============================================================================
# STAFF SALARY, DEDUCTIONS & PAYROLL VIEWS
# ============================================================================

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.ACCOUNTANT])
def payroll_dashboard_view(request):
    """
    Staff Payroll Management Dashboard:
    - Filters: Month, Year, Status, Staff Search query
    - Summary Cards: Gross Payroll, Total Deductions (Absent, Leave, Late cuts), Net Payable, Paid amount
    - Bulk Payroll Generation trigger
    - Paginated list of monthly salary slips
    """
    today = datetime.date.today()
    try:
        month = int(request.GET.get('month', today.month))
    except (ValueError, TypeError):
        month = today.month

    try:
        year = int(request.GET.get('year', today.year))
    except (ValueError, TypeError):
        year = today.year

    status_filter = request.GET.get('status', 'ALL')
    search_q = request.GET.get('q', '').strip()

    qs = SalarySlip.objects.filter(month=month, year=year)
    if request.user.school:
        qs = qs.filter(school=request.user.school)

    if status_filter in [SalarySlipStatusChoices.GENERATED, SalarySlipStatusChoices.PAID, SalarySlipStatusChoices.CANCELLED]:
        qs = qs.filter(status=status_filter)

    if search_q:
        qs = qs.filter(
            Q(staff__user__first_name__icontains=search_q) |
            Q(staff__user__last_name__icontains=search_q) |
            Q(staff__employee_id__icontains=search_q) |
            Q(slip_number__icontains=search_q)
        )

    qs = qs.select_related('staff__user', 'staff__shift').order_by('staff__employee_id')

    # Aggregates
    all_month_slips = SalarySlip.objects.filter(month=month, year=year)
    if request.user.school:
        all_month_slips = all_month_slips.filter(school=request.user.school)

    total_gross = all_month_slips.aggregate(s=Sum('gross_salary'))['s'] or Decimal('0.00')
    total_deductions = all_month_slips.aggregate(s=Sum('total_deductions'))['s'] or Decimal('0.00')
    total_net = all_month_slips.aggregate(s=Sum('net_salary'))['s'] or Decimal('0.00')
    total_paid = all_month_slips.filter(status=SalarySlipStatusChoices.PAID).aggregate(s=Sum('net_salary'))['s'] or Decimal('0.00')
    pending_count = all_month_slips.filter(status=SalarySlipStatusChoices.GENERATED).count()
    paid_count = all_month_slips.filter(status=SalarySlipStatusChoices.PAID).count()

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    generate_form = PayrollGenerateForm(initial={'month': month, 'year': year})

    context = {
        'page_obj': page_obj,
        'month': month,
        'year': year,
        'status_filter': status_filter,
        'search_q': search_q,
        'total_gross': total_gross,
        'total_deductions': total_deductions,
        'total_net': total_net,
        'total_paid': total_paid,
        'pending_count': pending_count,
        'paid_count': paid_count,
        'total_slips': all_month_slips.count(),
        'generate_form': generate_form,
        'status_choices': SalarySlipStatusChoices.choices,
    }
    return render(request, 'staff/payroll_dashboard.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.ACCOUNTANT])
def payroll_generate_action(request):
    """
    Triggers automated monthly payroll run for all active staff members.
    Calculates absent days cuts, late cuts, unpaid leave cuts, and creates/updates SalarySlips.
    """
    if request.method == 'POST':
        form = PayrollGenerateForm(request.POST)
        if form.is_valid():
            month = int(form.cleaned_data['month'])
            year = int(form.cleaned_data['year'])

            school = request.user.school
            if not school and request.user.is_superuser:
                # If superuser without explicit school, pick active school from staff
                from academics.models import School
                school = School.objects.first()

            slips = generate_bulk_payroll(school=school, month=month, year=year, generated_by=request.user)
            messages.success(request, f"Successfully processed payroll for {len(slips)} staff members for {month}/{year}.")
            return redirect(f"/staff/payroll/?month={month}&year={year}")
        else:
            messages.error(request, "Invalid month or year selected.")
    return redirect('staff_payroll_dashboard')


@login_required
def salary_slip_detail_view(request, slip_id):
    """
    Detail view of an individual Salary Slip with comprehensive earnings and deductions itemization.
    Security: Admin/Accountant can view any slip within their school.
    Staff/Teacher can only view their own slip.
    """
    slip = get_object_or_404(SalarySlip, id=slip_id)

    # Object-level access control
    is_management = request.user.role in [RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.ACCOUNTANT] or request.user.is_superuser
    if not is_management:
        if not (hasattr(request.user, 'staff_profile') and slip.staff == request.user.staff_profile):
            return HttpResponseForbidden("You are not authorized to view this salary slip.")

    # Multi-tenant check
    if request.user.school and slip.school != request.user.school:
        return HttpResponseForbidden("Cross-school access forbidden.")

    pay_form = SalarySlipPaymentForm(initial={
        'payment_method': slip.payment_method,
        'transaction_reference': slip.transaction_reference or '',
        'remarks': slip.remarks or ''
    })

    context = {
        'slip': slip,
        'is_management': is_management,
        'pay_form': pay_form,
    }
    return render(request, 'staff/salary_slip_detail.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.ACCOUNTANT])
def salary_slip_pay_action(request, slip_id):
    """
    Disburses / marks a Salary Slip as PAID.
    """
    slip = get_object_or_404(SalarySlip, id=slip_id)

    if request.user.school and slip.school != request.user.school:
        return HttpResponseForbidden("Cross-school access forbidden.")

    if request.method == 'POST':
        form = SalarySlipPaymentForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data['payment_method']
            ref = form.cleaned_data['transaction_reference']
            remarks = form.cleaned_data['remarks']

            mark_salary_slip_paid(
                slip=slip,
                payment_method=method,
                transaction_reference=ref,
                disbursed_by=request.user,
                remarks=remarks
            )
            messages.success(request, f"Salary Slip {slip.slip_number} successfully marked as PAID.")
            return redirect('salary_slip_detail', slip_id=slip.id)
        else:
            messages.error(request, "Invalid payment details submitted.")
    return redirect('salary_slip_detail', slip_id=slip.id)


@login_required
def salary_slip_pdf_view(request, slip_id):
    """
    Generates and downloads the official ReportLab printable Salary Slip PDF.
    Security: Admin/Accountant can download any slip within school; Staff member can only download their own.
    """
    slip = get_object_or_404(SalarySlip, id=slip_id)

    is_management = request.user.role in [RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.ACCOUNTANT] or request.user.is_superuser
    if not is_management:
        if not (hasattr(request.user, 'staff_profile') and slip.staff == request.user.staff_profile):
            return HttpResponseForbidden("You are not authorized to download this salary slip.")

    if request.user.school and slip.school != request.user.school:
        return HttpResponseForbidden("Cross-school access forbidden.")

    pdf_bytes = generate_payslip_pdf(slip)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Payslip_{slip.slip_number}.pdf"'
    return response


