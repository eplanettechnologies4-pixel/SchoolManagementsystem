from django.urls import path, include
from rest_framework.routers import DefaultRouter
from accounts.views import (
    root_redirect_view, CustomLoginView, custom_logout_view, change_password_view,
    dashboard_router, dashboard_admin, dashboard_teacher, dashboard_student,
    dashboard_parent, dashboard_accountant, profile_view, reports_hub_view,
    role_list_view, role_create_view, role_detail_view, role_delete_view,
    role_user_assignment_view, UserViewSet
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user-api')

urlpatterns = [
    path('', root_redirect_view, name='root_redirect'),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', custom_logout_view, name='logout'),
    path('change-password/', change_password_view, name='change_password'),
    path('dashboard/', dashboard_router, name='dashboard_router'),
    path('dashboard/admin/', dashboard_admin, name='dashboard_admin'),
    path('dashboard/teacher/', dashboard_teacher, name='dashboard_teacher'),
    path('dashboard/student/', dashboard_student, name='dashboard_student'),
    path('dashboard/parent/', dashboard_parent, name='dashboard_parent'),
    path('dashboard/accountant/', dashboard_accountant, name='dashboard_accountant'),
    path('reports/', reports_hub_view, name='reports_hub'),
    path('profile/', profile_view, name='profile'),

    # Super Admin Dynamic Roles & RBAC
    path('roles/', role_list_view, name='role_list'),
    path('roles/create/', role_create_view, name='role_create'),
    path('roles/<int:role_id>/', role_detail_view, name='role_detail'),
    path('roles/<int:role_id>/delete/', role_delete_view, name='role_delete'),
    path('roles/users/', role_user_assignment_view, name='role_user_assignment'),

    path('api/', include(router.urls)),
]
