import datetime
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.db.models import Sum, Q, Count
from django.utils import timezone

from .models import (
    FeeVoucher, FeePayment, FeeVoucherStatusChoices, FeeVoucherTypeChoices,
    Challan, Payment, FeeCategory, FeeStructure, ChallanStatusChoices, PaymentMethod
)
from .forms import FeeVoucherForm, FeePaymentForm, ChallanForm, VirtualPaymentForm
from .utils import generate_voucher_pdf, generate_receipt_pdf, build_whatsapp_message, format_whatsapp_phone_number
from .services.payment_gateway import VirtualGateway
from .services.fee_service import generate_challan_number, generate_challan_pdf, get_accountant_dashboard_metrics
from accounts.services import log_audit
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from students.models import StudentProfile
from academics.models import ClassLevel, Section


def is_staff_or_accountant(user):
    return user.is_authenticated and (user.is_admin_or_principal or user.is_accountant)


@login_required
def fee_dashboard(request):
    if not is_staff_or_accountant(request.user):
        messages.error(request, "Access denied. Fee Management is restricted to Admin & Accountant staff.")
        return redirect('dashboard_router')

    today = timezone.now().date()
    
    active_vouchers = FeeVoucher.objects.exclude(status=FeeVoucherStatusChoices.CANCELLED)

    total_vouchers = active_vouchers.count()
    total_fee_generated = active_vouchers.aggregate(total=Sum('total_payable'))['total'] or Decimal('0.00')
    total_collected = active_vouchers.aggregate(total=Sum('paid_amount'))['total'] or Decimal('0.00')
    total_pending = active_vouchers.filter(status__in=[FeeVoucherStatusChoices.UNPAID, FeeVoucherStatusChoices.PARTIALLY_PAID]).aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0.00')
    total_overdue = active_vouchers.filter(status=FeeVoucherStatusChoices.OVERDUE).aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0.00')

    today_collection = FeePayment.objects.filter(payment_date=today).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    # Chart 1: Paid vs Unpaid Status Counts
    paid_count = active_vouchers.filter(status=FeeVoucherStatusChoices.PAID).count()
    unpaid_count = active_vouchers.filter(status=FeeVoucherStatusChoices.UNPAID).count()
    partial_count = active_vouchers.filter(status=FeeVoucherStatusChoices.PARTIALLY_PAID).count()
    overdue_count = active_vouchers.filter(status=FeeVoucherStatusChoices.OVERDUE).count()

    # Chart 2: Class-wise Fee Collection
    class_stats = ClassLevel.objects.annotate(
        generated=Sum('students__fee_vouchers__total_payable', filter=~Q(students__fee_vouchers__status=FeeVoucherStatusChoices.CANCELLED)),
        collected=Sum('students__fee_vouchers__paid_amount', filter=~Q(students__fee_vouchers__status=FeeVoucherStatusChoices.CANCELLED))
    )
    class_labels = [c.name for c in class_stats]
    class_generated = [float(c.generated or 0) for c in class_stats]
    class_collected = [float(c.collected or 0) for c in class_stats]

    recent_payments = FeePayment.objects.select_related('voucher__student', 'received_by')[:8]
    recent_vouchers = FeeVoucher.objects.select_related('student__class_level', 'student__section')[:8]

    context = {
        'total_vouchers': total_vouchers,
        'total_fee_generated': total_fee_generated,
        'total_collected': total_collected,
        'total_pending': total_pending,
        'total_overdue': total_overdue,
        'today_collection': today_collection,

        'status_counts': {
            'paid': paid_count,
            'unpaid': unpaid_count,
            'partially_paid': partial_count,
            'overdue': overdue_count
        },
        'class_chart': {
            'labels': class_labels,
            'generated': class_generated,
            'collected': class_collected
        },
        'recent_payments': recent_payments,
        'recent_vouchers': recent_vouchers
    }
    return render(request, 'fees/fee_dashboard.html', context)


@login_required
def voucher_list(request):
    if not is_staff_or_accountant(request.user):
        # Parents & Students view their own list
        if request.user.is_student and hasattr(request.user, 'student_profile'):
            vouchers = FeeVoucher.objects.filter(student=request.user.student_profile)
            return render(request, 'fees/student_voucher_list.html', {'vouchers': vouchers})
        elif request.user.is_parent and hasattr(request.user, 'guardian_profile'):
            vouchers = FeeVoucher.objects.filter(student__guardian=request.user.guardian_profile)
            return render(request, 'fees/student_voucher_list.html', {'vouchers': vouchers})
        else:
            messages.error(request, "Access denied.")
            return redirect('dashboard_router')

    vouchers = FeeVoucher.objects.select_related('student__user', 'student__class_level', 'student__section', 'student__guardian').all()

    # Search & Filter Logic
    q = request.GET.get('q', '').strip()
    if q:
        vouchers = vouchers.filter(
            Q(voucher_number__icontains=q) |
            Q(student__admission_number__icontains=q) |
            Q(student__user__first_name__icontains=q) |
            Q(student__user__last_name__icontains=q) |
            Q(student__user__username__icontains=q)
        )

    class_id = request.GET.get('class_id')
    if class_id:
        vouchers = vouchers.filter(student__class_level_id=class_id)

    status_filter = request.GET.get('status')
    if status_filter:
        vouchers = vouchers.filter(status=status_filter)

    month_filter = request.GET.get('month')
    if month_filter:
        vouchers = vouchers.filter(billing_month__icontains=month_filter)

    sort = request.GET.get('sort', '-created_at')
    if sort in ['created_at', '-created_at', 'due_date', '-due_date', 'total_payable', '-total_payable']:
        vouchers = vouchers.order_by(sort)

    classes = ClassLevel.objects.all()

    context = {
        'vouchers': vouchers,
        'classes': classes,
        'search_query': q,
        'selected_class': class_id,
        'selected_status': status_filter,
        'selected_month': month_filter,
        'selected_sort': sort,
        'status_choices': FeeVoucherStatusChoices.choices
    }
    return render(request, 'fees/voucher_list.html', context)


@login_required
def voucher_create(request):
    if not is_staff_or_accountant(request.user):
        messages.error(request, "Permission denied.")
        return redirect('dashboard_router')

    if request.method == 'POST':
        form = FeeVoucherForm(request.POST)
        if form.is_valid():
            voucher = form.save(commit=False)
            voucher.created_by = request.user
            voucher.save()
            messages.success(request, f"Fee Voucher #{voucher.voucher_number} generated successfully!")
            return redirect('voucher_detail', pk=voucher.pk)
        else:
            messages.error(request, "Failed to create voucher. Please fix form errors below.")
    else:
        # Pre-select student if passed via GET parameter
        initial_data = {
            'academic_session': '2026-2027',
            'issue_date': timezone.now().date(),
            'due_date': timezone.now().date() + datetime.timedelta(days=10),
            'billing_month': timezone.now().strftime('%B %Y')
        }
        student_id = request.GET.get('student_id')
        if student_id:
            initial_data['student'] = student_id
        form = FeeVoucherForm(initial=initial_data)

    students = StudentProfile.objects.select_related('user', 'class_level', 'section', 'guardian').all()
    context = {
        'form': form,
        'students': students,
        'is_create': True
    }
    return render(request, 'fees/voucher_form.html', context)


@login_required
def voucher_edit(request, pk):
    if not is_staff_or_accountant(request.user):
        messages.error(request, "Permission denied.")
        return redirect('dashboard_router')

    voucher = get_object_or_404(FeeVoucher, pk=pk)

    if request.method == 'POST':
        form = FeeVoucherForm(request.POST, instance=voucher)
        if form.is_valid():
            voucher = form.save()
            messages.success(request, f"Fee Voucher #{voucher.voucher_number} updated successfully!")
            return redirect('voucher_detail', pk=voucher.pk)
        else:
            messages.error(request, "Form errors occurred.")
    else:
        form = FeeVoucherForm(instance=voucher)

    students = StudentProfile.objects.select_related('user', 'class_level', 'section').all()
    context = {
        'form': form,
        'voucher': voucher,
        'students': students,
        'is_create': False
    }
    return render(request, 'fees/voucher_form.html', context)


@login_required
def voucher_detail(request, pk):
    voucher = get_object_or_404(FeeVoucher.objects.select_related('student__user', 'student__class_level', 'student__section', 'student__guardian'), pk=pk)
    
    # Security check for student / parent
    if request.user.is_student and hasattr(request.user, 'student_profile') and voucher.student != request.user.student_profile:
        messages.error(request, "Access denied to this voucher.")
        return redirect('dashboard_router')
    elif request.user.is_parent and hasattr(request.user, 'guardian_profile') and voucher.student.guardian != request.user.guardian_profile:
        messages.error(request, "Access denied to this voucher.")
        return redirect('dashboard_router')

    payments = voucher.payments.select_related('received_by').all()
    wa_data = build_whatsapp_message(voucher, request)

    context = {
        'voucher': voucher,
        'payments': payments,
        'wa_data': wa_data
    }
    return render(request, 'fees/voucher_detail.html', context)


@login_required
def voucher_pdf(request, pk):
    voucher = get_object_or_404(FeeVoucher, pk=pk)
    pdf_bytes = generate_voucher_pdf(voucher)
    
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Fee_Voucher_{voucher.voucher_number}.pdf"'
    return response


@login_required
def voucher_print(request, pk):
    voucher = get_object_or_404(FeeVoucher.objects.select_related('student__user', 'student__class_level', 'student__section', 'student__guardian'), pk=pk)
    copies = ["Bank Copy", "School Copy", "Student / Parent Copy"]
    context = {
        'voucher': voucher,
        'copies': copies
    }
    return render(request, 'fees/voucher_print.html', context)


@login_required
def record_payment(request, pk):
    if not is_staff_or_accountant(request.user):
        messages.error(request, "Permission denied.")
        return redirect('dashboard_router')

    voucher = get_object_or_404(FeeVoucher, pk=pk)

    if voucher.status == FeeVoucherStatusChoices.PAID:
        messages.warning(request, f"Voucher #{voucher.voucher_number} is already fully paid.")
        return redirect('voucher_detail', pk=voucher.pk)

    if request.method == 'POST':
        form = FeePaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.voucher = voucher
            payment.received_by = request.user
            payment.save()
            messages.success(request, f"Payment of Rs. {payment.amount_paid:,.2f} recorded! Receipt #{payment.receipt_number} generated.")
            return redirect('voucher_detail', pk=voucher.pk)
        else:
            messages.error(request, "Please check payment input values.")
    else:
        # Pre-fill amount with remaining balance
        initial = {
            'amount_paid': voucher.remaining_balance,
            'payment_date': timezone.now().date(),
        }
        form = FeePaymentForm(initial=initial)

    context = {
        'form': form,
        'voucher': voucher
    }
    return render(request, 'fees/record_payment.html', context)


@login_required
def receipt_print(request, payment_id):
    payment = get_object_or_404(FeePayment.objects.select_related('voucher__student__user', 'voucher__student__class_level', 'received_by'), pk=payment_id)
    return render(request, 'fees/receipt_print.html', {'payment': payment})


@login_required
def receipt_pdf(request, payment_id):
    payment = get_object_or_404(FeePayment, pk=payment_id)
    pdf_bytes = generate_receipt_pdf(payment)
    
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Fee_Receipt_{payment.receipt_number}.pdf"'
    return response


@login_required
def voucher_cancel(request, pk):
    if not is_staff_or_accountant(request.user):
        messages.error(request, "Permission denied.")
        return redirect('dashboard_router')

    voucher = get_object_or_404(FeeVoucher, pk=pk)
    if request.method == 'POST':
        voucher.status = FeeVoucherStatusChoices.CANCELLED
        voucher.save()
        messages.info(request, f"Voucher #{voucher.voucher_number} cancelled.")
        return redirect('voucher_detail', pk=voucher.pk)

    return render(request, 'fees/voucher_confirm_cancel.html', {'voucher': voucher})


@login_required
def api_get_student_info(request, student_id):
    student = get_object_or_404(StudentProfile.objects.select_related('class_level', 'section', 'guardian'), pk=student_id)
    
    # Calculate previous unpaid balance
    prev_unpaid = FeeVoucher.objects.filter(
        student=student,
        status__in=[FeeVoucherStatusChoices.UNPAID, FeeVoucherStatusChoices.PARTIALLY_PAID, FeeVoucherStatusChoices.OVERDUE]
    ).aggregate(total=Sum('remaining_balance'))['total'] or 0.0

    guardian_name = student.guardian.get_full_name() if student.guardian else "N/A"
    guardian_phone = student.guardian.phone if student.guardian else "N/A"

    return JsonResponse({
        'success': True,
        'student_id': student.id,
        'name': student.get_full_name(),
        'admission_number': student.admission_number,
        'class_name': student.class_level.name,
        'section_name': student.section.name,
        'guardian_name': guardian_name,
        'guardian_phone': guardian_phone,
        'previous_balance': float(prev_unpaid)
    })


@login_required
def api_whatsapp_preview(request, pk):
    voucher = get_object_or_404(FeeVoucher, pk=pk)
    wa_data = build_whatsapp_message(voucher, request)
    return JsonResponse(wa_data)


# =====================================================================
# STANDARDIZED CHALLAN & VIRTUAL PAYMENT VIEWS (PART 1)
# =====================================================================

@login_required
def challan_list(request):
    """
    List of fee challans with role-based filtering, search, class filter, and pagination.
    """
    user = request.user
    qs = Challan.objects.select_related('student__user', 'student__class_level', 'student__section', 'school').all()

    # RBAC filtering
    if user.is_student:
        qs = qs.filter(student__user=user)
    elif user.is_parent:
        qs = qs.filter(student__guardian__user=user)
    elif not (user.is_admin_or_principal or user.is_accountant):
        raise PermissionDenied("You do not have permission to view fee challans.")

    # Search query
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(challan_no__icontains=q) |
            Q(student__admission_number__icontains=q) |
            Q(student__user__first_name__icontains=q) |
            Q(student__user__last_name__icontains=q) |
            Q(student__user__username__icontains=q)
        )

    # Status filter
    status = request.GET.get('status', '').strip()
    if status:
        qs = qs.filter(status=status)

    # Class filter
    class_id = request.GET.get('class_id', '').strip()
    if class_id:
        qs = qs.filter(student__class_level_id=class_id)

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    classes = ClassLevel.objects.filter(is_active=True)

    return render(request, 'fees/challan_list.html', {
        'page_obj': page_obj,
        'query': q,
        'status_filter': status,
        'class_id': class_id,
        'classes': classes,
        'status_choices': ChallanStatusChoices.choices,
    })


@login_required
def challan_create(request):
    """
    Accountant / Admin view to create a new Challan.
    Uses race-condition safe challan number generation.
    """
    if not is_staff_or_accountant(request.user):
        raise PermissionDenied("Only accountants and administrators can issue challans.")

    school = getattr(request.user, 'school', None)
    if request.method == 'POST':
        form = ChallanForm(request.POST, school=school)
        if form.is_valid():
            challan = form.save(commit=False)
            challan.school = school or getattr(challan.student.class_level, 'school', None)
            challan.created_by = request.user
            challan.challan_no = generate_challan_number(challan.year)
            challan.remaining_balance = challan.total
            challan.status = ChallanStatusChoices.UNPAID
            challan.save()

            log_audit(
                user=request.user,
                action='CREATE',
                instance=challan,
                changes={'challan_no': challan.challan_no, 'total': float(challan.total)},
                request=request
            )

            messages.success(request, f"Challan #{challan.challan_no} created successfully for {challan.student.get_full_name()}!")
            return redirect('challan_detail', pk=challan.pk)
    else:
        form = ChallanForm(school=school)

    return render(request, 'fees/challan_form.html', {
        'form': form,
        'is_create': True
    })


@login_required
def challan_detail(request, pk):
    """
    Challan detail view. Enforces object-level ownership check.
    Allows accountants to trigger a Virtual Simulated Payment.
    """
    challan = get_object_or_404(
        Challan.objects.select_related('student__user', 'student__guardian', 'student__class_level', 'student__section', 'school'),
        pk=pk
    )

    # Object-level ownership check
    user = request.user
    if user.is_student and challan.student.user != user:
        raise PermissionDenied("You can only view your own challans.")
    elif user.is_parent and (not challan.student.guardian or challan.student.guardian.user != user):
        raise PermissionDenied("You can only view challans belonging to your wards.")
    elif not (user.is_admin_or_principal or user.is_accountant or user.is_student or user.is_parent):
        raise PermissionDenied("Permission denied.")

    payments = challan.challan_payments.select_related('received_by').all().order_by('-received_at')
    payment_form = VirtualPaymentForm(initial={'amount': challan.remaining_balance})

    return render(request, 'fees/challan_detail.html', {
        'challan': challan,
        'payments': payments,
        'payment_form': payment_form,
        'is_accountant': is_staff_or_accountant(user),
    })


@login_required
def challan_pay_virtual(request, pk):
    """
    Simulated Virtual Payment processor for accountants.
    Calls VirtualGateway to mark challan as paid (TEST ONLY).
    """
    if not is_staff_or_accountant(request.user):
        raise PermissionDenied("Only accountants can mark virtual payments.")

    challan = get_object_or_404(Challan, pk=pk)

    if request.method == 'POST':
        form = VirtualPaymentForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            notes = form.cleaned_data['notes']
            try:
                gateway = VirtualGateway()
                payment = gateway.process_payment(
                    challan=challan,
                    amount=amount,
                    received_by=request.user,
                    notes=notes,
                    request=request
                )
                messages.success(request, f"Virtual payment of Rs. {amount} successfully recorded (Ref: {payment.reference_no}) [TEST MODE].")
            except Exception as e:
                messages.error(request, f"Virtual payment failed: {str(e)}")
        else:
            messages.error(request, "Invalid payment details submitted.")

    return redirect('challan_detail', pk=challan.pk)


@login_required
def challan_reverse_payment(request, payment_id):
    """
    Creates an immutable reversal entry for a mistaken payment.
    """
    if not is_staff_or_accountant(request.user):
        raise PermissionDenied("Only accountants can reverse payments.")

    payment = get_object_or_404(Payment.objects.select_related('challan'), pk=payment_id)
    challan = payment.challan

    if request.method == 'POST':
        reason = request.POST.get('reason', 'Administrative payment reversal').strip()
        try:
            gateway = VirtualGateway()
            reversal = gateway.reverse_payment(
                payment=payment,
                reason=reason,
                user=request.user,
                request=request
            )
            messages.info(request, f"Payment #{payment.reference_no} reversed successfully via reversal entry #{reversal.reference_no}.")
        except Exception as e:
            messages.error(request, f"Reversal failed: {str(e)}")

    return redirect('challan_detail', pk=challan.pk)


@login_required
def challan_pdf(request, pk):
    """
    Generates and downloads the ReportLab PDF for a Challan with embedded QR code.
    Enforces object-level ownership check.
    """
    challan = get_object_or_404(
        Challan.objects.select_related('student__user', 'student__guardian', 'student__class_level', 'student__section', 'school'),
        pk=pk
    )

    user = request.user
    if user.is_student and challan.student.user != user:
        raise PermissionDenied("Access denied.")
    elif user.is_parent and (not challan.student.guardian or challan.student.guardian.user != user):
        raise PermissionDenied("Access denied.")
    elif not (user.is_admin_or_principal or user.is_accountant or user.is_student or user.is_parent):
        raise PermissionDenied("Access denied.")

    pdf_bytes = generate_challan_pdf(challan)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Challan_{challan.challan_no}.pdf"'
    return response


@login_required
def student_fee_portal(request):
    """
    Student / Parent fee overview.
    Displays read-only fee status with explicit notice: "Pay at school / coming soon".
    Strictly forbids direct online payments.
    """
    user = request.user
    if user.is_student:
        student = getattr(user, 'student_profile', None)
        students = [student] if student else []
    elif user.is_parent:
        guardian = getattr(user, 'guardian_profile', None)
        students = list(guardian.wards.all()) if guardian else []
    else:
        messages.info(request, "Redirected to Fee Dashboard.")
        return redirect('fee_dashboard')

    challans = Challan.objects.filter(student__in=students).select_related('student__user', 'student__class_level', 'student__section').order_by('-due_date')

    return render(request, 'fees/student_fee_portal.html', {
        'students': students,
        'challans': challans,
    })

