import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sms_core.settings')
django.setup()

from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from accounts.models import User, RoleChoices
from students.models import StudentProfile, GuardianProfile
from academics.models import ClassLevel, Section
from fees.models import FeeVoucher, FeePayment, FeeVoucherStatusChoices, FeeVoucherTypeChoices, PaymentMethodChoices
from fees.utils import generate_voucher_pdf, generate_receipt_pdf, build_whatsapp_message, format_whatsapp_phone_number

def run_tests():
    print("=== STARTING FEE MANAGEMENT E2E VERIFICATION TEST ===")
    
    # 1. Verify Phone Number Formatting & Validation
    print("\n1. Testing Phone Number Formatting & WhatsApp Helpers...")
    ok, formatted, err = format_whatsapp_phone_number("03001234567")
    assert ok and formatted == "923001234567", f"Expected 923001234567, got {formatted}"
    print(f"   [PASS] Local Pakistani number 03001234567 -> {formatted}")

    ok, formatted, err = format_whatsapp_phone_number("+92 301 8765432")
    assert ok and formatted == "923018765432", f"Expected 923018765432, got {formatted}"
    print(f"   [PASS] Formatted +92 301 8765432 -> {formatted}")

    # 2. Get demo student
    student = StudentProfile.objects.select_related('guardian', 'class_level', 'section').first()
    assert student is not None, "Demo student required in DB."
    
    # Ensure guardian has valid phone number for testing
    if not student.guardian:
        parent_user = User.objects.filter(role=RoleChoices.PARENT).first()
        guardian = GuardianProfile.objects.create(
            user=parent_user,
            first_name="Muhammad",
            last_name="Smith",
            relation="Father",
            phone="03001234567"
        )
        student.guardian = guardian
        student.save()
    else:
        student.guardian.phone = "03001234567"
        student.guardian.save()

    print(f"\n2. Creating Fee Voucher for Student: {student.get_full_name()} ({student.admission_number})...")
    
    # 3. Create Fee Voucher with auto calculations
    voucher = FeeVoucher.objects.create(
        student=student,
        academic_session="2026-2027",
        voucher_type=FeeVoucherTypeChoices.MONTHLY,
        billing_month="August 2026",
        issue_date=timezone.now().date(),
        due_date=timezone.now().date() + timedelta(days=10),
        tuition_fee=Decimal('8500.00'),
        exam_fee=Decimal('1500.00'),
        transport_fee=Decimal('2000.00'),
        previous_balance=Decimal('1000.00'),
        late_fine=Decimal('0.00'),
        discount_amount=Decimal('1000.00'),
        discount_remarks="10% Merit Concession"
    )

    print(f"   Generated Voucher #: {voucher.voucher_number}")
    print(f"   Subtotal: Rs. {voucher.subtotal}")
    print(f"   Total Payable: Rs. {voucher.total_payable}")
    print(f"   Initial Status: {voucher.status}")

    assert voucher.subtotal == Decimal('12000.00'), f"Expected Subtotal 12000, got {voucher.subtotal}"
    assert voucher.total_payable == Decimal('12000.00'), f"Expected Total Payable 12000 (12000 - 1000 + 1000), got {voucher.total_payable}"
    assert voucher.status == FeeVoucherStatusChoices.UNPAID, f"Expected UNPAID status, got {voucher.status}"
    print("   [PASS] Subtotal, Discount, Prev Balance, Total Payable & Status auto-calculated correctly!")

    # 4. WhatsApp Message Builder Test
    print("\n3. Testing WhatsApp Notification Builder...")
    wa_info = build_whatsapp_message(voucher)
    assert wa_info['is_valid'] is True, f"WhatsApp phone validation failed: {wa_info['error']}"
    assert "Rs. 12,000.00" in wa_info['message_text'], "Amount missing in WhatsApp text."
    assert "https://wa.me/923001234567" in wa_info['whatsapp_url'], "wa.me link generation failed."
    print("   [PASS] Structured WhatsApp message & click-to-chat URL built successfully!")
    print(f"   Preview:\n{wa_info['message_text']}\n")

    # 5. ReportLab PDF Generation Test (3-Copy Voucher)
    print("4. Testing ReportLab 3-Copy Fee Voucher PDF Generation...")
    pdf_data = generate_voucher_pdf(voucher)
    assert len(pdf_data) > 1000, "Voucher PDF generation returned empty or small payload."
    print(f"   [PASS] Fee Voucher PDF generated! Payload size: {len(pdf_data)} bytes.")

    # 6. Record Partial Payment
    print("\n5. Testing Partial Payment Recording...")
    accountant_user = User.objects.filter(role=RoleChoices.ACCOUNTANT).first() or User.objects.first()
    payment1 = FeePayment.objects.create(
        voucher=voucher,
        amount_paid=Decimal('5000.00'),
        payment_date=timezone.now().date(),
        payment_method=PaymentMethodChoices.CASH,
        received_by=accountant_user,
        notes="Partial cash payment received at counter"
    )
    
    # Reload voucher from DB to verify signal/recalculate
    voucher.refresh_from_db()
    print(f"   Recorded Payment Receipt #: {payment1.receipt_number}")
    print(f"   Voucher Paid Amount: Rs. {voucher.paid_amount}")
    print(f"   Voucher Remaining Balance: Rs. {voucher.remaining_balance}")
    print(f"   Updated Status: {voucher.status}")

    assert voucher.paid_amount == Decimal('5000.00')
    assert voucher.remaining_balance == Decimal('7000.00')
    assert voucher.status == FeeVoucherStatusChoices.PARTIALLY_PAID, f"Expected PARTIALLY_PAID, got {voucher.status}"
    print("   [PASS] Voucher status automatically transitioned to PARTIALLY_PAID!")

    # 7. Record Remaining Balance Payment
    print("\n6. Testing Remaining Payment Recording & Voucher Clearance...")
    payment2 = FeePayment.objects.create(
        voucher=voucher,
        amount_paid=Decimal('7000.00'),
        payment_date=timezone.now().date(),
        payment_method=PaymentMethodChoices.BANK_TRANSFER,
        transaction_reference="ABL-9482018",
        received_by=accountant_user,
        notes="Bank transfer balance cleared"
    )
    
    voucher.refresh_from_db()
    print(f"   Recorded Payment Receipt #: {payment2.receipt_number}")
    print(f"   Voucher Paid Amount: Rs. {voucher.paid_amount}")
    print(f"   Voucher Remaining Balance: Rs. {voucher.remaining_balance}")
    print(f"   Updated Status: {voucher.status}")

    assert voucher.paid_amount == Decimal('12000.00')
    assert voucher.remaining_balance == Decimal('0.00')
    assert voucher.status == FeeVoucherStatusChoices.PAID, f"Expected PAID, got {voucher.status}"
    print("   [PASS] Voucher status automatically transitioned to PAID!")

    # 8. ReportLab Receipt PDF Test
    print("\n7. Testing ReportLab Receipt PDF Generation...")
    receipt_pdf_data = generate_receipt_pdf(payment2)
    assert len(receipt_pdf_data) > 1000
    print(f"   [PASS] Official Payment Receipt PDF generated! Payload size: {len(receipt_pdf_data)} bytes.")

    print("\n=== ALL FEE VOUCHER SYSTEM VERIFICATION TESTS PASSED PERFECTLY! ===")

if __name__ == '__main__':
    run_tests()
