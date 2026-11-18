import uuid
import datetime
from django.db import models
from django.conf import settings
from accounts.models import TimeStampedModel, RoleChoices, SchoolScopedModel, SchoolScopedManager
from academics.models import ClassLevel, Section


class StudentStatusChoices(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    INACTIVE = 'INACTIVE', 'Inactive'
    GRADUATED = 'GRADUATED', 'Graduated'
    TRANSFERRED = 'TRANSFERRED', 'Transferred'
    STRUCK_OFF = 'STRUCK_OFF', 'Struck-off'


class GenderChoices(models.TextChoices):
    MALE = 'MALE', 'Male'
    FEMALE = 'FEMALE', 'Female'
    OTHER = 'OTHER', 'Other'


class GuardianProfile(SchoolScopedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        limit_choices_to={'role': RoleChoices.PARENT},
        related_name='guardian_profile'
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    father_name = models.CharField(max_length=100, blank=True, null=True)
    mother_name = models.CharField(max_length=100, blank=True, null=True)
    relation = models.CharField(max_length=50, help_text="Father, Mother, Legal Guardian")
    cnic = models.CharField(max_length=30, blank=True, null=True, db_index=True, help_text="Format: 35202-1234567-1")
    occupation = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=30, help_text="Format: +923001234567")
    whatsapp_number = models.CharField(max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    emergency_contact = models.CharField(max_length=30, blank=True, null=True)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.get_full_name()} ({self.relation})"

    @property
    def students(self):
        return self.wards.filter(is_deleted=False)


class StudentProfile(SchoolScopedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': RoleChoices.STUDENT},
        related_name='student_profile'
    )
    admission_number = models.CharField(max_length=50, unique=True, db_index=True)
    roll_number = models.CharField(max_length=50, db_index=True)
    class_level = models.ForeignKey(ClassLevel, on_delete=models.PROTECT, related_name='students')
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='students')
    guardian = models.ForeignKey(GuardianProfile, on_delete=models.SET_NULL, blank=True, null=True, related_name='wards')
    
    dob = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GenderChoices.choices, default=GenderChoices.MALE)
    bform_number = models.CharField(max_length=30, blank=True, null=True, db_index=True, help_text="Format: 35202-1234567-1")
    religion = models.CharField(max_length=50, default="Islam", blank=True, null=True)
    blood_group = models.CharField(max_length=10, blank=True, null=True)
    nationality = models.CharField(max_length=50, default="Pakistani")
    admission_date = models.DateField(default=datetime.date.today)
    photo = models.ImageField(upload_to='student_photos/', blank=True, null=True)
    emergency_contact = models.CharField(max_length=30, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    previous_school = models.CharField(max_length=200, blank=True, null=True)
    previous_class = models.CharField(max_length=100, blank=True, null=True)
    last_result = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(max_length=20, choices=StudentStatusChoices.choices, default=StudentStatusChoices.ACTIVE, db_index=True)

    class Meta:
        ordering = ['class_level__numeric_order', 'section__name', 'roll_number']
        unique_together = ('class_level', 'section', 'roll_number')

    def get_full_name(self):
        return self.user.get_full_name() or self.user.username

    def __str__(self):
        return f"{self.admission_number} - {self.get_full_name()} ({self.class_level.name} {self.section.name})"


class StudentDocumentType(models.TextChoices):
    B_FORM = 'B_FORM', 'B-Form / Birth Certificate'
    GUARDIAN_CNIC = 'GUARDIAN_CNIC', 'Guardian CNIC Copy'
    MARKSHEET = 'MARKSHEET', 'Previous Marksheet'
    TRANSFER_CERT = 'TRANSFER_CERT', 'School Leaving / Transfer Certificate'
    OTHER = 'OTHER', 'Other Document'


class StudentDocument(SchoolScopedModel):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=50, choices=StudentDocumentType.choices, default=StudentDocumentType.OTHER)
    title = models.CharField(max_length=150, help_text="e.g. Birth Certificate, CNIC/B-Form, Previous Marksheet")
    file = models.FileField(upload_to='student_documents/private/')
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")

    def __str__(self):
        return f"{self.title} - {self.student.get_full_name()}"


class AdmissionDraft(SchoolScopedModel):
    """
    Stores incomplete admission wizard submissions as drafts.
    """
    draft_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    step = models.PositiveIntegerField(default=1)
    data = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admission_drafts')

    def __str__(self):
        return f"Draft #{self.draft_id} (Step {self.step}) by {self.created_by.username}"


class StudentLeaveStatusChoices(models.TextChoices):
    PENDING = 'PENDING', 'Pending Approval'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'


class StudentLeaveRequest(SchoolScopedModel):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='leave_requests')
    guardian = models.ForeignKey(GuardianProfile, on_delete=models.CASCADE, related_name='student_leaves')
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=StudentLeaveStatusChoices.choices, default=StudentLeaveStatusChoices.PENDING)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_student_leaves')
    remarks = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def total_days(self):
        if self.from_date and self.to_date:
            return (self.to_date - self.from_date).days + 1
        return 0

    def __str__(self):
        return f"Leave for {self.student.get_full_name()} ({self.from_date} to {self.to_date}): {self.status}"

