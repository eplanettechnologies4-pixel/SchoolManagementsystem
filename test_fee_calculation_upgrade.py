import os
import sys
import django
from decimal import Decimal

# Setup Django Environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sms_core.settings')
django.setup()

from django.test import Client
from django.urls import reverse
from accounts.models import User, RoleChoices
from students.models import StudentProfile
from fees.models import FeeVoucher, FeeVoucherStatusChoices
from fees.forms import FeeVoucherForm

def run_tests():
    print("--- STARTING FEE VOUCHER CALCULATION UPGRADE E2E SUITE ---")
    client = Client()

    # 1. Authenticate as Admin / Accountant
    admin_user = User.objects.filter(role=RoleChoices.ADMIN).first()
    if not admin_user:
        admin_user = User.objects.filter(role=RoleChoices.SUPER_ADMIN).first()

    assert admin_user is not None, "Admin user required for test"
    client.force_login(admin_user)
    print(f"1. Authenticated as: {admin_user.username} ({admin_user.get_role_display()})")

    # 2. Verify GET Create Fee Voucher Form page
    create_url = reverse('voucher_create')
    res = client.get(create_url)
    assert res.status_code == 200, f"Voucher create expected 200, got {res.status_code}"
    print("2. [PASS] GET /fees/vouchers/create/ returned HTTP 200 OK")

    # 3. Verify Model Calculation Logic
    student = StudentProfile.objects.first()
    assert student is not None, "At least one student required"

    import datetime
    voucher = FeeVoucher.objects.create(
        student=student,
        academic_session="2026-2027",
        billing_month="September 2026",
        issue_date=datetime.date(2026, 9, 1),
        due_date=datetime.date(2026, 9, 10),
        monthly_fee=Decimal('5000.00'),
        total_fee=Decimal('60000.00'),
        submitted_fee=Decimal('20000.00'),
        admission_fee=Decimal('1000.00'),
        exam_fee=Decimal('500.00'),
        transport_fee=Decimal('1500.00'),
        hostel_fee=Decimal('0.00'),
        other_charges=Decimal('200.00'),
        previous_balance=Decimal('800.00'),
        late_fine=Decimal('100.00'),
        discount_amount=Decimal('500.00'),
        created_by=admin_user
    )

    # Formula Assertions
    expected_remaining_fee = Decimal('40000.00')  # 60000 - 20000
    assert voucher.remaining_fee == expected_remaining_fee, f"Expected Remaining Fee {expected_remaining_fee}, got {voucher.remaining_fee}"
    print(f"3. [PASS] Remaining Fee = Total Fee (60,000) - Submitted Fee (20,000) = Rs. {voucher.remaining_fee:,.2f}")

    expected_subtotal = Decimal('5000.00') + Decimal('1000.00') + Decimal('500.00') + Decimal('1500.00') + Decimal('0.00') + Decimal('200.00') # = 8200.00
    assert voucher.subtotal == expected_subtotal, f"Expected Subtotal {expected_subtotal}, got {voucher.subtotal}"
    print(f"   [PASS] Subtotal = Monthly + Admission + Exam + Transport + Hostel + Other = Rs. {voucher.subtotal:,.2f}")

    expected_payable = expected_subtotal - Decimal('500.00') + Decimal('800.00') + Decimal('100.00') # = 8600.00
    assert voucher.total_payable == expected_payable, f"Expected Total Payable {expected_payable}, got {voucher.total_payable}"
    print(f"   [PASS] Final Payable = Subtotal - Discount + Arrears + Fine = Rs. {voucher.total_payable:,.2f}")

    # 4. Form Validation Tests (Submitted > Total without advance payment)
    invalid_form_data = {
        'student': student.id,
        'academic_session': '2026-2027',
        'voucher_type': 'MONTHLY',
        'billing_month': 'September 2026',
        'issue_date': '2026-09-01',
        'due_date': '2026-09-10',
        'monthly_fee': '5000.00',
        'total_fee': '10000.00',
        'submitted_fee': '15000.00', # 15000 > 10000
        'allow_advance_payment': False,
        'tuition_fee': '5000.00',
        'admission_fee': '0.00',
        'exam_fee': '0.00',
        'transport_fee': '0.00',
        'hostel_fee': '0.00',
        'previous_balance': '0.00',
        'late_fine': '0.00',
        'other_charges': '0.00',
        'discount_amount': '0.00'
    }

    form = FeeVoucherForm(data=invalid_form_data)
    assert not form.is_valid()
    assert 'submitted_fee' in form.errors
    print("4. [PASS] Form validation correctly rejected Submitted Fee > Total Fee when Advance Payment is disabled")

    # 5. Form Validation Tests (Submitted > Total with advance payment enabled)
    invalid_form_data['allow_advance_payment'] = True
    form_valid = FeeVoucherForm(data=invalid_form_data)
    assert form_valid.is_valid(), f"Form should be valid when advance payment enabled. Errors: {form_valid.errors}"
    print("5. [PASS] Form validation allowed Submitted Fee > Total Fee when Advance Payment is enabled")

    # 6. Form Validation Tests (Negative Amount rejection)
    negative_form_data = invalid_form_data.copy()
    negative_form_data['exam_fee'] = '-100.00'
    form_neg = FeeVoucherForm(data=negative_form_data)
    assert not form_neg.is_valid()
    assert 'exam_fee' in form_neg.errors
    print("6. [PASS] Form validation correctly rejected negative amount (-100.00)")

    # 7. Verify Printable 3-Part Fee Voucher View
    print_url = reverse('voucher_print', kwargs={'pk': voucher.pk})
    res_print = client.get(print_url)
    assert res_print.status_code == 200, f"Expected 200 OK for voucher print, got {res_print.status_code}"
    content_str = res_print.content.decode('utf-8')
    assert 'Bank Copy' in content_str
    assert 'School Copy' in content_str
    assert 'Student / Parent Copy' in content_str
    assert content_str.count('---') == 6  # 3 copies each with --- Badge ---
    print("7. [PASS] Printable Fee Voucher verified: Exactly 3 copies (Bank Copy, School Copy, Student / Parent Copy)")

    print("\n=======================================================")
    print("ALL FEE VOUCHER CALCULATION E2E TESTS PASSED PERFECTLY!")
    print("=======================================================")

if __name__ == '__main__':
    run_tests()
