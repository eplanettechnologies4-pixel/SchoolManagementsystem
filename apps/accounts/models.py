from django.contrib.auth.models import AbstractUser
from django.db import models


class RoleChoices(models.TextChoices):
    SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
    ADMIN = 'ADMIN', 'Admin / Principal'
    TEACHER = 'TEACHER', 'Teacher'
    ACCOUNTANT = 'ACCOUNTANT', 'Accountant'
    STUDENT = 'STUDENT', 'Student'
    PARENT = 'PARENT', 'Parent'


class TimeStampedModel(models.Model):
    """
    Abstract base model providing self-updating created_at and updated_at fields.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SchoolScopedQuerySet(models.QuerySet):
    """
    QuerySet providing multi-tenant school-scoped filtering and soft delete helper methods.
    """
    def active(self):
        return self.filter(is_deleted=False)

    def for_school(self, school):
        if not school:
            return self.active()
        return self.filter(school=school, is_deleted=False)

    def for_user(self, user):
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_superuser and not getattr(user, 'school_id', None):
            return self.active()
        user_school = getattr(user, 'school', None)
        if user_school:
            return self.filter(school=user_school, is_deleted=False)
        return self.active()

    def delete(self):
        return self.update(is_deleted=True)


class SchoolScopedManager(models.Manager.from_queryset(SchoolScopedQuerySet)):
    """
    Default manager ensuring queries are automatically filtered by active records.
    """
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def all_with_deleted(self):
        return super().get_queryset()


class SchoolScopedModel(TimeStampedModel):
    """
    Abstract base model for multi-tenant entities with automatic school scoping and soft delete.
    """
    school = models.ForeignKey(
        'academics.School',
        on_delete=models.CASCADE,
        related_name='%(app_label)s_%(class)s_set',
        null=True,
        blank=True
    )
    is_deleted = models.BooleanField(default=False, db_index=True)

    objects = SchoolScopedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.save(update_fields=['is_deleted', 'updated_at'])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)


class PermissionCategoryChoices(models.TextChoices):
    STUDENTS = 'STUDENTS', 'Student Information System (SIS)'
    ACADEMICS = 'ACADEMICS', 'Academics & Classroom'
    STAFF = 'STAFF', 'Faculty & Staff Management'
    FEES = 'FEES', 'Fee & Financial Management'
    REPORTS = 'REPORTS', 'Reports & Analytics'
    SETTINGS = 'SETTINGS', 'System & Role Management'


class AppPermission(models.Model):
    code = models.CharField(max_length=100, unique=True, db_index=True, help_text="e.g. students.view")
    name = models.CharField(max_length=150)
    category = models.CharField(
        max_length=50,
        choices=PermissionCategoryChoices.choices,
        default=PermissionCategoryChoices.STUDENTS
    )
    description = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['category', 'code']
        verbose_name = 'Application Permission'
        verbose_name_plural = 'Application Permissions'

    def __str__(self):
        return f"{self.name} ({self.code})"


class CustomRole(SchoolScopedModel):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, db_index=True)
    base_role = models.CharField(
        max_length=20,
        choices=RoleChoices.choices,
        default=RoleChoices.TEACHER,
        help_text="Underlying baseline role workflow."
    )
    description = models.TextField(blank=True, null=True)
    permissions = models.ManyToManyField(AppPermission, blank=True, related_name='roles')
    is_system_role = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'code'],
                name='unique_school_role_code'
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def users_count(self):
        return self.users.count()


class User(AbstractUser):
    """
    Custom User model extending Django AbstractUser with role-based access control,
    school multi-tenancy, dynamic custom roles, and forced password change flag.
    """
    school = models.ForeignKey(
        'academics.School',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )
    role = models.CharField(
        max_length=20,
        choices=RoleChoices.choices,
        default=RoleChoices.STUDENT,
        help_text="Role determining permissions and accessible modules across the SMS platform."
    )
    custom_role = models.ForeignKey(
        'accounts.CustomRole',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text="Custom dynamic role assigned by Super Admin."
    )
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    cnic_bform = models.CharField(max_length=30, blank=True, null=True, help_text="CNIC or B-Form number for identification.")
    address = models.TextField(blank=True, null=True)
    must_change_password = models.BooleanField(
        default=False,
        help_text="Flag enforcing user password change upon their first login."
    )
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def get_display_role_name(self):
        if self.custom_role:
            return self.custom_role.name
        return self.get_role_display()

    def __str__(self):
        full_name = self.get_full_name()
        display_role = self.get_display_role_name()
        if full_name:
            return f"{full_name} ({display_role})"
        return f"{self.username} ({display_role})"

    def has_app_permission(self, perm_code: str) -> bool:
        if self.is_superuser or self.is_super_admin:
            return True
        if self.custom_role:
            return self.custom_role.permissions.filter(code=perm_code).exists()
        return self.has_default_role_permission(perm_code)

    def has_default_role_permission(self, perm_code: str) -> bool:
        if self.role in [RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN]:
            return True
        if self.role == RoleChoices.TEACHER:
            return perm_code in [
                'students.view', 'academics.view', 'staff.attendance',
                'reports.view', 'academics.assignment'
            ]
        if self.role == RoleChoices.ACCOUNTANT:
            return perm_code in [
                'fees.view', 'fees.collect', 'fees.challans', 'staff.payroll',
                'reports.view', 'students.view'
            ]
        if self.role in [RoleChoices.STUDENT, RoleChoices.PARENT]:
            return perm_code in ['portal.view', 'fees.my_status']
        return False


    @property
    def is_super_admin(self):
        return self.role == RoleChoices.SUPER_ADMIN or self.is_superuser

    @property
    def is_admin_or_principal(self):
        return self.role in [RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN] or self.is_superuser

    @property
    def is_teacher(self):
        return self.role == RoleChoices.TEACHER

    @property
    def is_student(self):
        return self.role == RoleChoices.STUDENT

    @property
    def is_parent(self):
        return self.role == RoleChoices.PARENT

    @property
    def is_accountant(self):
        return self.role == RoleChoices.ACCOUNTANT


class AuditLog(models.Model):
    """
    Persistent audit trail tracking who changed what, timestamp, IP address, and old/new values.
    """
    school = models.ForeignKey(
        'academics.School',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=50, db_index=True)  # CREATE, UPDATE, DELETE, PAYMENT, REVERSAL, PROMOTION, ROLLBACK
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=100, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True, null=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'

    def __str__(self):
        user_name = self.user.username if self.user else 'System'
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {user_name} - {self.action} on {self.model_name} #{self.object_id}"


class NoticeTargetChoices(models.TextChoices):
    ALL = 'ALL', 'All Users'
    STUDENT = 'STUDENT', 'Students Only'
    PARENT = 'PARENT', 'Parents Only'
    TEACHER = 'TEACHER', 'Teachers Only'


class Notice(SchoolScopedModel):
    title = models.CharField(max_length=200)
    content = models.TextField()
    target_role = models.CharField(max_length=20, choices=NoticeTargetChoices.choices, default=NoticeTargetChoices.ALL)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='published_notices')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_target_role_display()})"


class NoticeRead(TimeStampedModel):
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name='reads')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notice_reads')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('notice', 'user')

    def __str__(self):
        return f"{self.user.username} read notice #{self.notice_id}"
