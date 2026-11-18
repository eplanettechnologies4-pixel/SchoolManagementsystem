from django.shortcuts import redirect
from django.urls import reverse


class RoleRoutingMiddleware:
    """
    Middleware to handle role-based routing and ensure users land on their respective dashboards.
    Also enforces forced password change on first login.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Forced password change check
            if getattr(request.user, 'must_change_password', False):
                allowed_prefixes = ['/change-password/', '/logout/', '/static/', '/media/']
                if not any(request.path.startswith(p) for p in allowed_prefixes):
                    return redirect('change_password')

            # If user visits root '/', redirect to role dashboard
            if request.path == '/':
                role = getattr(request.user, 'role', 'STUDENT')
                return self._redirect_for_role(role)
        
        response = self.get_response(request)
        return response

    def _redirect_for_role(self, role):
        if role in ['SUPER_ADMIN', 'ADMIN']:
            return redirect('dashboard_admin')
        elif role == 'TEACHER':
            return redirect('staff_dashboard')
        elif role == 'STUDENT':
            return redirect('dashboard_student')
        elif role == 'PARENT':
            return redirect('dashboard_parent')
        elif role == 'ACCOUNTANT':
            return redirect('dashboard_accountant')
        return redirect('dashboard_admin')
