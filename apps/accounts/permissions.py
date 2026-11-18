from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from rest_framework.permissions import BasePermission
from accounts.models import RoleChoices

class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_super_admin)

class IsAdminOrPrincipal(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin_or_principal)

class IsTeacherUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_teacher or request.user.is_admin_or_principal))

class IsStudentUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_student or request.user.is_admin_or_principal))

class IsParentUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_parent or request.user.is_admin_or_principal))

class IsAccountantUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_accountant or request.user.is_admin_or_principal))


def role_required(allowed_roles):
    """
    Decorator for Django function-based views to enforce role access.
    Supports built-in roles as well as custom roles via their base_role.
    Usage: @role_required(['ADMIN', 'SUPER_ADMIN', 'TEACHER'])
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.is_superuser or request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            if getattr(request.user, 'custom_role', None) and request.user.custom_role.base_role in allowed_roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to access this module.")
        return _wrapped_view
    return decorator


def permission_required(perm_code):
    """
    Decorator enforcing granular application permissions.
    Usage: @permission_required('students.create')
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.has_app_permission(perm_code):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(f"Permission '{perm_code}' required to access this resource.")
        return _wrapped_view
    return decorator

