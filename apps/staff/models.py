import datetime
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from accounts.models import SchoolScopedModel, SchoolScopedManager, RoleChoices


class LateDeductionPolicyChoices(models.TextChoices):
    EVERY_3_LATES_1_DAY = '3_LATES_1_DAY', _('3 Lates = 1 Day Deduction')
    HALF_DAY_PER_2_LATES = '2_LATES_HALF_DAY', _('2 Lates = Half Day Deduction')
    NONE = 'NONE', _('No Automatic Late Deduction')


class SalarySlipStatusChoices(models.TextChoices):
    GENERATED = 'GENERATED', _('Generated')
    PAID = 'PAID', _('Paid')
    CANCELLED = 'CANCELLED', _('Cancelled')


class SalaryPaymentMethodChoices(models.TextChoices):
    BANK_TRANSFER = 'BANK_TRANSFER', _('Bank Transfer')
    CASH = 'CASH', _('Cash Payment')
    CHEQUE = 'CHEQUE', _('Cheque')


class EmploymentTypeChoices(models.TextChoices):
    PERMANENT = 'PERMANENT', _('Permanent')
    CONTRACT = 'CONTRACT', _('Contract')
    PART_TIME = 'PART_TIME', _('Part-time')


class StaffStatusChoices(models.TextChoices):
    ACTIVE = 'ACTIVE', _('Active')
    INACTIVE = 'INACTIVE', _('Inactive')
    ON_LEAVE = 'ON_LEAVE', _('On Leave')
    TERMINATED = 'TERMINATED', _('Terminated')


class AttendanceStatusChoices(models.TextChoices):
    PRESENT = 'PRESENT', _('Present')
    ABSENT = 'ABSENT', _('Absent')
    LATE = 'LATE', _('Late')
    LEAVE = 'LEAVE', _('Leave')
    HALF_DAY = 'HALF_DAY', _('Half-day')


class AttendanceMethodChoices(models.TextChoices):
    MANUAL = 'MANUAL', _('Manual Entry')
    QR = 'QR', _('QR Code Scan')
    GPS = 'GPS', _('GPS Geofence')


class LeaveStatusChoices(models.TextChoices):
    PENDING = 'PENDING', _('Pending')
    APPROVED = 'APPROVED', _('Approved')
    REJECTED = 'REJECTED', _('Rejected')


class StaffDocumentType(models.TextChoices):
    CNIC = 'CNIC', _('National ID / CNIC')
    DEGREE = 'DEGREE', _('Degree / Transcript')
    CONTRACT = 'CONTRACT', _('Employment Contract')
    EXPERIENCE = 'EXPERIENCE', _('Experience Letter')
    OTHER = 'OTHER', _('Other Document')


class ShiftTiming(SchoolScopedModel):
    name = models.CharField(max_length=100, help_text=_("e.g. Standard Morning Shift"))
    start_time = models.TimeField(default=datetime.time(8, 0))
    end_time = models.TimeField(default=datetime.time(14, 0))
    grace_minutes = models.PositiveIntegerField(default=15, help_text=_("Grace minutes after start time before marked Late"))
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')})"


class LeaveType(SchoolScopedModel):
    name = models.CharField(max_length=100, help_text=_("e.g. Casual Leave, Sick Leave, Annual Leave"))
    days_per_year = models.PositiveIntegerField(default=12, help_text=_("Total allowed quota per academic year"))
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.days_per_year} days/yr)"


class Staff(SchoolScopedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_profile'
    )
    employee_id = models.CharField(max_length=50, unique=True, db_index=True)
    designation = models.CharField(max_length=100, help_text=_("e.g. Senior Teacher, Head of Science, Accountant"))
    department = models.CharField(max_length=100, blank=True, null=True, help_text=_("e.g. Sciences, Arts, Administration"))
    qualification = models.CharField(max_length=200, blank=True, null=True, help_text=_("e.g. M.Sc Physics, B.Ed"))
    joining_date = models.DateField(default=datetime.date.today)
    phone = models.CharField(max_length=30, help_text=_("e.g. +923001234567"))
    cnic = models.CharField(max_length=30, blank=True, null=True, db_index=True, help_text=_("Format: 35202-1234567-1"))
    address = models.TextField(blank=True, null=True)
    photo = models.ImageField(upload_to='staff_photos/', blank=True, null=True)
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentTypeChoices.choices,
        default=EmploymentTypeChoices.PERMANENT
    )
    status = models.CharField(
        max_length=20,
        choices=StaffStatusChoices.choices,
        default=StaffStatusChoices.ACTIVE
    )
    emergency_contact = models.CharField(max_length=30, blank=True, null=True)
    shift = models.ForeignKey(ShiftTiming, on_delete=models.SET_NULL, null=True, blank=True, related_name='staff_members')

    # Salary & Compensation Structure
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('50000.00'), help_text=_("Monthly base salary in PKR"))
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text=_("Monthly allowances in PKR"))
    late_deduction_policy = models.CharField(
        max_length=30,
        choices=LateDeductionPolicyChoices.choices,
        default=LateDeductionPolicyChoices.EVERY_3_LATES_1_DAY,
        help_text=_("Policy for deducting salary based on late arrivals")
    )
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        ordering = ['employee_id']
        verbose_name = _('Staff Member')
        verbose_name_plural = _('Staff Members')

    def get_full_name(self):
        return self.user.get_full_name() or self.user.username

    def __str__(self):
        return f"{self.get_full_name()} ({self.employee_id}) - {self.designation}"


class StaffDocument(SchoolScopedModel):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=StaffDocumentType.choices, default=StaffDocumentType.OTHER)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='staff_documents/private/')
    file_size = models.PositiveIntegerField(default=0, help_text=_("File size in bytes"))

    def __str__(self):
        return f"{self.title} - {self.staff.get_full_name()}"


class StaffAttendance(SchoolScopedModel):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='attendances')
    date = models.DateField(default=datetime.date.today, db_index=True)
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=AttendanceStatusChoices.choices,
        default=AttendanceStatusChoices.PRESENT
    )
    method = models.CharField(
        max_length=20,
        choices=AttendanceMethodChoices.choices,
        default=AttendanceMethodChoices.GPS
    )
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True, help_text=_("Calculated distance from school in meters"))
    is_out_of_range = models.BooleanField(default=False, help_text=_("True if outside allowed school radius"))
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_staff_attendances'
    )
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-date', 'staff__employee_id']
        constraints = [
            models.UniqueConstraint(
                fields=['staff', 'date'],
                name='unique_staff_daily_attendance'
            )
        ]

    def __str__(self):
        return f"{self.staff.get_full_name()} - {self.date}: {self.get_status_display()}"


class LeaveRequest(SchoolScopedModel):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='requests')
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=LeaveStatusChoices.choices,
        default=LeaveStatusChoices.PENDING
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_staff_leaves'
    )
    review_comments = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def total_days(self):
        if self.from_date and self.to_date:
            return (self.to_date - self.from_date).days + 1
        return 0

    def __str__(self):
        return f"{self.staff.get_full_name()} ({self.leave_type.name}) : {self.from_date} to {self.to_date} - {self.status}"


class SalarySlip(SchoolScopedModel):
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='salary_slips')
    slip_number = models.CharField(max_length=50, unique=True, db_index=True)
    month = models.PositiveIntegerField(help_text=_("1 to 12"))
    year = models.PositiveIntegerField(help_text=_("e.g. 2026"))

    # Attendance and working days metrics
    total_days = models.PositiveIntegerField(default=30)
    present_days = models.PositiveIntegerField(default=0)
    absent_days = models.PositiveIntegerField(default=0)
    leave_days = models.PositiveIntegerField(default=0)
    unpaid_leave_days = models.PositiveIntegerField(default=0)
    late_count = models.PositiveIntegerField(default=0)
    half_day_count = models.PositiveIntegerField(default=0)

    # Earnings
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Deductions
    absent_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    leave_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    late_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Net payable
    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Status & Payment
    status = models.CharField(
        max_length=20,
        choices=SalarySlipStatusChoices.choices,
        default=SalarySlipStatusChoices.GENERATED
    )
    payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(
        max_length=30,
        choices=SalaryPaymentMethodChoices.choices,
        default=SalaryPaymentMethodChoices.BANK_TRANSFER
    )
    transaction_reference = models.CharField(max_length=100, blank=True, null=True)
    disbursed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disbursed_salary_slips'
    )
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-year', '-month', 'staff__employee_id']
        constraints = [
            models.UniqueConstraint(
                fields=['staff', 'month', 'year'],
                name='unique_staff_monthly_salary_slip'
            )
        ]

    def __str__(self):
        return f"{self.slip_number} - {self.staff.get_full_name()} ({self.month}/{self.year}) : PKR {self.net_salary}"


