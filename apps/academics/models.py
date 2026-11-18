from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from accounts.models import TimeStampedModel, RoleChoices, SchoolScopedManager, SchoolScopedModel

class School(TimeStampedModel):
    """
    Root model for Multi-Tenancy SMS deployments.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField()
    phone = models.CharField(max_length=30)
    email = models.EmailField()
    logo = models.ImageField(upload_to='school_logos/', blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    # GPS Coordinates & Geofencing for Staff Check-in / Tracking
    latitude = models.DecimalField(max_digits=9, decimal_places=6, default=33.6844, help_text="Latitude for GPS check-in")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, default=73.0479, help_text="Longitude for GPS check-in")
    radius_meters = models.PositiveIntegerField(default=500, help_text="Allowed radius for geofenced check-in")
    is_deleted = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

class AcademicYear(TimeStampedModel):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='academic_years')
    name = models.CharField(max_length=50, help_text="e.g. 2026-2027")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['school'],
                condition=models.Q(is_current=True),
                name='unique_active_academic_year_per_school'
            )
        ]

    def clean(self):
        super().clean()
        if self.is_current and self.school_id:
            qs = AcademicYear.objects.filter(school=self.school, is_current=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            # If another active year exists, auto-deactivate others in save()

    def save(self, *args, **kwargs):
        if self.is_current and self.school_id:
            AcademicYear.objects.filter(school=self.school, is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} {'(Current)' if self.is_current else ''}"

class ClassCategory(TimeStampedModel):
    """
    Academic Level / Wing Category:
    e.g. Pre-Primary (PG, Nursery, Prep), Primary (Classes 1-5),
    Middle (Classes 6-8), Secondary / SSC (Classes 9-10), Higher Secondary / College (11-12)
    """
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='class_categories', null=True, blank=True)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30)
    numeric_order = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = SchoolScopedManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['numeric_order', 'name']
        verbose_name = 'Class Category'
        verbose_name_plural = 'Class Categories'

    def __str__(self):
        return self.name

class ClassLevel(TimeStampedModel):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='classes')
    category = models.ForeignKey(
        ClassCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='classes',
        help_text="Academic wing / category"
    )
    name = models.CharField(max_length=100, help_text="e.g. Grade 10 or Class 9")
    code = models.CharField(max_length=20, help_text="e.g. G10")
    numeric_order = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True, null=True, help_text="Curriculum or stream details")
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = SchoolScopedManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['numeric_order', 'name']
        unique_together = ('school', 'code')

    def __str__(self):
        return f"{self.name} {'(Inactive)' if not self.is_active else ''}"

    @property
    def total_students_count(self):
        return self.students.filter(is_deleted=False, status='ACTIVE').count()

    @property
    def total_sections_count(self):
        return self.sections.filter(is_deleted=False, is_active=True).count()

class Section(TimeStampedModel):
    class_level = models.ForeignKey(ClassLevel, on_delete=models.CASCADE, related_name='sections')
    name = models.CharField(max_length=50, help_text="e.g. Section A")
    room_number = models.CharField(max_length=50, blank=True, null=True)
    capacity = models.PositiveIntegerField(default=40)
    class_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        limit_choices_to={'role': RoleChoices.TEACHER},
        related_name='managed_sections'
    )
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = SchoolScopedManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['class_level__numeric_order', 'name']
        unique_together = ('class_level', 'name')

    def __str__(self):
        return f"{self.class_level.name} - {self.name}"

    @property
    def current_enrollment_count(self):
        return self.students.filter(is_deleted=False, status='ACTIVE').count()

    @property
    def enrollment_display(self):
        return f"{self.current_enrollment_count}/{self.capacity} filled"

    @property
    def is_full(self):
        return self.current_enrollment_count >= self.capacity

    def clean(self):
        super().clean()
        if self.pk:
            enrolled = self.students.filter(is_deleted=False, status='ACTIVE').count()
            if enrolled > self.capacity:
                raise ValidationError(f"Section capacity ({self.capacity}) cannot be less than currently enrolled students ({enrolled}).")

class Subject(TimeStampedModel):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='all_subjects', null=True, blank=True)
    class_level = models.ForeignKey(ClassLevel, on_delete=models.CASCADE, related_name='subjects')
    section = models.ForeignKey(
        Section,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='section_subjects'
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30)
    is_optional = models.BooleanField(default=False, help_text="Optional/Elective subject")
    credit_hours = models.PositiveIntegerField(default=3)
    is_elective = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    assigned_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        limit_choices_to={'role': RoleChoices.TEACHER},
        related_name='assigned_subjects'
    )

    objects = SchoolScopedManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['class_level', 'name']
        unique_together = ('class_level', 'code')

    def save(self, *args, **kwargs):
        if not self.school_id and self.class_level_id:
            self.school = self.class_level.school
        super().save(*args, **kwargs)

    def __str__(self):
        teacher_str = f" ({self.assigned_teacher.get_full_name() or self.assigned_teacher.username})" if self.assigned_teacher else ""
        return f"{self.name} [{self.code}] - {self.class_level.name}{teacher_str}"

class ClassSubjectAssignment(TimeStampedModel):
    """
    Standardized Class-Section-Subject-Teacher assignment.
    Enforces uniqueness per (section, subject).
    """
    class_level = models.ForeignKey(ClassLevel, on_delete=models.CASCADE, related_name='class_subject_assignments')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, null=True, blank=True, related_name='section_subject_assignments')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='assigned_teachers_list')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': RoleChoices.TEACHER},
        related_name='class_assigned_subjects'
    )
    periods_per_week = models.PositiveIntegerField(default=5, help_text="Allocated teaching periods per week")
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = SchoolScopedManager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = 'Class Subject Assignment'
        verbose_name_plural = 'Class Subject Assignments'
        unique_together = ('section', 'subject')

    def __str__(self):
        sec_name = self.section.name if self.section else "All Sections"
        return f"{self.subject.name} ({sec_name}) -> {self.teacher.get_full_name() or self.teacher.username} ({self.periods_per_week} periods/wk)"


class CurriculumPDF(TimeStampedModel):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='curriculum_pdfs')
    title = models.CharField(max_length=200, help_text="e.g. Official Subject List & Curriculum 2026-2027")
    pdf_file = models.FileField(upload_to='curriculum_pdfs/')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='uploaded_curriculums'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")
    is_active = models.BooleanField(default=True)
    version_notes = models.CharField(max_length=255, blank=True, null=True, help_text="Optional version notes")

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title} ({'Active' if self.is_active else 'Archived'})"

class SubjectTeacherAssignment(TimeStampedModel):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='teacher_assignments')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='subject_assignments')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': RoleChoices.TEACHER},
        related_name='subject_assignments'
    )
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='assignments')

    class Meta:
        unique_together = ('subject', 'section', 'academic_year')

    def __str__(self):
        return f"{self.subject.name} - {self.section} ({self.teacher.get_full_name() or self.teacher.username})"

