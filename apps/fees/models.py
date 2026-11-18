from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import uuid
import datetime

from accounts.models import TimeStampedModel, SchoolScopedModel
from students.models import StudentProfile


class FeeVoucherTypeChoices(models.TextChoices):
    MONTHLY = 'MONTHLY', 'Monthly Fee'
    ADMISSION = 'ADMISSION', 'Admission Fee'
    EXAM = 'EXAM', 'Examination Fee'
    TRANSPORT = 'TRANSPORT', 'Transport Fee'
    HOSTEL = 'HOSTEL', 'Hostel Fee'
    OTHER = 'OTHER', 'Other Charges'


class FeeVoucherStatusChoices(models.TextChoices):
    UNPAID = 'UNPAID', 'Unpaid'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'Partially Paid'
    PAID = 'PAID', 'Paid'
    OVERDUE = 'OVERDUE', 'Overdue'
    CANCELLED = 'CANCELLED', 'Cancelled'


class PaymentMethodChoices(models.TextChoices):
    CASH = 'CASH', 'Cash'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    ONLINE = 'ONLINE', 'Online Payment'
    CHEQUE = 'CHEQUE', 'Cheque'
    OTHER = 'OTHER', 'Other'


class FeeVoucher(TimeStampedModel):
    voucher_number = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='fee_vouchers')
    academic_session = models.CharField(max_length=20, default='2026-2027')
    voucher_type = models.CharField(max_length=20, choices=FeeVoucherTypeChoices.choices, default=FeeVoucherTypeChoices.MONTHLY)
    billing_month = models.CharField(max_length=50, help_text="e.g. August 2026")
    
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField()

    # Fee Overview & Period Totals
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Monthly recurring fee")
    total_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total fee amount for selected session/period")
    submitted_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total amount already paid/submitted")
    remaining_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Outstanding fee (Total Fee - Submitted Fee)")
    allow_advance_payment = models.BooleanField(default=False, help_text="Allow submitted fee to exceed total fee")

    # Fee Components
    tuition_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    admission_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    exam_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    transport_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    hostel_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    previous_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    late_fine = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    other_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Calculated Financial Fields
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount_remarks = models.CharField(max_length=150, blank=True, null=True, help_text="Scholarship / Financial Concession Details")
    
    total_payable = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Status & Audit
    status = models.CharField(max_length=20, choices=FeeVoucherStatusChoices.choices, default=FeeVoucherStatusChoices.UNPAID, db_index=True)
    remarks = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_vouchers')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Fee Voucher'
        verbose_name_plural = 'Fee Vouchers'

    def clean(self):
        from django.core.exceptions import ValidationError
        # Check negative amounts
        num_fields = [
            ('monthly_fee', self.monthly_fee),
            ('total_fee', self.total_fee),
            ('submitted_fee', self.submitted_fee),
            ('tuition_fee', self.tuition_fee),
            ('admission_fee', self.admission_fee),
            ('exam_fee', self.exam_fee),
            ('transport_fee', self.transport_fee),
            ('hostel_fee', self.hostel_fee),
            ('previous_balance', self.previous_balance),
            ('late_fine', self.late_fine),
            ('other_charges', self.other_charges),
            ('discount_amount', self.discount_amount),
        ]
        for field_name, val in num_fields:
            if val is not None and val < Decimal('0.00'):
                raise ValidationError({field_name: "Negative fee amounts are not allowed."})

        # Check Submitted Fee <= Total Fee unless advance payment enabled
        if not self.allow_advance_payment and self.submitted_fee > self.total_fee and self.total_fee > Decimal('0.00'):
            raise ValidationError({'submitted_fee': "Submitted Fee cannot be greater than Total Fee unless Advance Payment is enabled."})

    def save(self, *args, **kwargs):
        if not self.voucher_number:
            prefix = timezone.now().strftime('VOU-%Y%m-')
            rand_suffix = str(uuid.uuid4().int)[:4]
            self.voucher_number = f"{prefix}{rand_suffix}"

        # Sync monthly_fee and tuition_fee
        if self.monthly_fee > Decimal('0.00') and self.tuition_fee == Decimal('0.00'):
            self.tuition_fee = self.monthly_fee
        elif self.tuition_fee > Decimal('0.00') and self.monthly_fee == Decimal('0.00'):
            self.monthly_fee = self.tuition_fee

        # Calculate Remaining Fee = Total Fee - Submitted Fee
        rem = Decimal(self.total_fee or 0) - Decimal(self.submitted_fee or 0)
        self.remaining_fee = rem if self.allow_advance_payment else max(Decimal('0.00'), rem)

        # Subtotal sum of items before discount & fine
        monthly_base = max(Decimal(self.monthly_fee or 0), Decimal(self.tuition_fee or 0))
        self.subtotal = (
            monthly_base +
            Decimal(self.admission_fee or 0) +
            Decimal(self.exam_fee or 0) +
            Decimal(self.transport_fee or 0) +
            Decimal(self.hostel_fee or 0) +
            Decimal(self.other_charges or 0)
        )

        # Total Payable = Subtotal - Discount + Prev Balance + Fine
        payable = (
            self.subtotal -
            Decimal(self.discount_amount or 0) +
            Decimal(self.previous_balance or 0) +
            Decimal(self.late_fine or 0)
        )
        self.total_payable = max(Decimal('0.00'), payable)
        
        # Remaining balance
        self.remaining_balance = max(Decimal('0.00'), self.total_payable - Decimal(self.paid_amount or 0))

        # Auto Status Update
        due_dt = self.due_date
        if isinstance(due_dt, str):
            due_dt = datetime.date.fromisoformat(due_dt)

        if self.status != FeeVoucherStatusChoices.CANCELLED:
            if self.paid_amount >= self.total_payable and self.total_payable > Decimal('0.00'):
                self.status = FeeVoucherStatusChoices.PAID
                self.remaining_balance = Decimal('0.00')
            elif self.paid_amount > Decimal('0.00') and self.paid_amount < self.total_payable:
                self.status = FeeVoucherStatusChoices.PARTIALLY_PAID
            elif self.paid_amount == Decimal('0.00'):
                if due_dt and due_dt < datetime.date.today():
                    self.status = FeeVoucherStatusChoices.OVERDUE
                else:
                    self.status = FeeVoucherStatusChoices.UNPAID

        super().save(*args, **kwargs)

    def recalculate_and_save(self):
        payments_sum = self.payments.aggregate(total=models.Sum('amount_paid'))['total'] or Decimal('0.00')
        self.paid_amount = payments_sum
        self.save()

    def __str__(self):
        return f"{self.voucher_number} - {self.student.get_full_name()} ({self.billing_month}) - {self.get_status_display()}"


class FeePayment(TimeStampedModel):
    voucher = models.ForeignKey(FeeVoucher, on_delete=models.CASCADE, related_name='payments')
    receipt_number = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PaymentMethodChoices.choices, default=PaymentMethodChoices.CASH)
    transaction_reference = models.CharField(max_length=100, blank=True, null=True, help_text="Cheque No / Bank Ref / Transaction ID")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='collected_payments')
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']
        verbose_name = 'Fee Payment'
        verbose_name_plural = 'Fee Payments'

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            prefix = timezone.now().strftime('REC-%Y%m-')
            rand_suffix = str(uuid.uuid4().int)[:4]
            self.receipt_number = f"{prefix}{rand_suffix}"
        
        super().save(*args, **kwargs)
        # Automatically recalculate voucher paid amount & update voucher status
        self.voucher.recalculate_and_save()

    def delete(self, *args, **kwargs):
        voucher = self.voucher
        super().delete(*args, **kwargs)
        voucher.recalculate_and_save()

    def __str__(self):
        return f"{self.receipt_number} - Rs. {self.amount_paid} ({self.voucher.voucher_number})"


# =====================================================================
# PART 1: STANDARDIZED MULTI-TENANT FEE SYSTEM (VIRTUAL / PLACEHOLDER)
# =====================================================================

class FeeCategory(SchoolScopedModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Fee Category'
        verbose_name_plural = 'Fee Categories'
        ordering = ['name']
        unique_together = ('school', 'name')

    def __str__(self):
        return self.name


class FeeStructure(SchoolScopedModel):
    class_level = models.ForeignKey('academics.ClassLevel', on_delete=models.CASCADE, related_name='fee_structures')
    academic_year = models.ForeignKey('academics.AcademicYear', on_delete=models.CASCADE, related_name='fee_structures')
    category = models.ForeignKey(FeeCategory, on_delete=models.CASCADE, related_name='structures')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        verbose_name = 'Fee Structure'
        verbose_name_plural = 'Fee Structures'
        ordering = ['class_level__numeric_order', 'category__name']
        unique_together = ('class_level', 'academic_year', 'category')

    def __str__(self):
        return f"{self.class_level.name} - {self.category.name}: Rs. {self.amount}"


class ChallanStatusChoices(models.TextChoices):
    UNPAID = 'Unpaid', 'Unpaid'
    PAID = 'Paid', 'Paid'
    PARTIAL = 'Partial', 'Partial'
    CANCELLED = 'Cancelled', 'Cancelled'


class Challan(SchoolScopedModel):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='challans')
    academic_year = models.ForeignKey('academics.AcademicYear', on_delete=models.SET_NULL, null=True, blank=True, related_name='challans')
    month = models.CharField(max_length=50, help_text="e.g. August 2026")
    year = models.PositiveIntegerField(default=2026)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=ChallanStatusChoices.choices, default=ChallanStatusChoices.UNPAID, db_index=True)
    due_date = models.DateField()
    challan_no = models.CharField(max_length=50, unique=True, db_index=True)
    remarks = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_challans')

    class Meta:
        verbose_name = 'Challan'
        verbose_name_plural = 'Challans'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.challan_no} - {self.student.get_full_name()} ({self.month} {self.year}) [{self.status}]"

    def recalculate_status(self):
        payments_sum = self.challan_payments.filter(is_deleted=False).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        self.paid_amount = Decimal(str(payments_sum))
        total_dec = Decimal(str(self.total or '0.00'))
        self.remaining_balance = max(Decimal('0.00'), total_dec - self.paid_amount)
        if self.status != ChallanStatusChoices.CANCELLED:
            if self.paid_amount >= total_dec and total_dec > Decimal('0.00'):
                self.status = ChallanStatusChoices.PAID
            elif self.paid_amount > Decimal('0.00') and self.paid_amount < total_dec:
                self.status = ChallanStatusChoices.PARTIAL
            elif self.paid_amount <= Decimal('0.00'):
                self.status = ChallanStatusChoices.UNPAID
        self.save(update_fields=['paid_amount', 'remaining_balance', 'status', 'updated_at'])


class PaymentMethod(models.TextChoices):
    CASH = 'Cash', 'Cash'
    BANK = 'Bank', 'Bank'
    VIRTUAL = 'Virtual', 'Virtual'


class Payment(SchoolScopedModel):
    """
    Immutable payment record. Modifying or deleting a payment raises a ValidationError.
    Mistakes must be corrected by recording a reversal payment entry.
    """
    challan = models.ForeignKey(Challan, on_delete=models.CASCADE, related_name='challan_payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.VIRTUAL)
    reference_no = models.CharField(max_length=100, unique=True, db_index=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_fee_payments')
    received_at = models.DateTimeField(default=timezone.now)
    is_virtual = models.BooleanField(default=True, help_text="Virtual / Simulated payment flag")
    is_reversal = models.BooleanField(default=False, help_text="True if this is a corrective reversal transaction")
    reversal_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reversal_entries')
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        ordering = ['-received_at']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.pk:
            orig = Payment.all_objects.filter(pk=self.pk).first()
            if orig:
                raise ValidationError("Payments are IMMUTABLE. Editing is prohibited; please record a reversal entry instead.")
        super().clean()

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        if self.pk:
            orig = Payment.all_objects.filter(pk=self.pk).first()
            if orig:
                raise ValidationError("Payments are IMMUTABLE. Editing is prohibited; please record a reversal entry instead.")
        super().save(*args, **kwargs)
        self.challan.recalculate_status()

    def delete(self, using=None, keep_parents=False):
        from django.core.exceptions import ValidationError
        raise ValidationError("Payments are IMMUTABLE. Deletion is prohibited; please record a reversal entry instead.")

