from django.urls import path
from staff.views import (
    staff_dashboard_view, staff_check_in_action, staff_check_out_action,
    staff_tracking_dashboard, staff_list_view, staff_create_view,
    staff_detail_view, staff_leave_apply_view, staff_leave_review_view,
    staff_attendance_pdf_view, staff_attendance_excel_view,
    payroll_dashboard_view, payroll_generate_action, salary_slip_detail_view,
    salary_slip_pay_action, salary_slip_pdf_view
)

urlpatterns = [
    path('', staff_list_view, name='staff_index'),
    path('dashboard/', staff_dashboard_view, name='staff_dashboard'),
    path('tracking/', staff_tracking_dashboard, name='staff_tracking_dashboard'),
    path('directory/', staff_list_view, name='staff_list'),
    path('create/', staff_create_view, name='staff_create'),
    path('<int:staff_id>/', staff_detail_view, name='staff_detail'),
    path('check-in/', staff_check_in_action, name='staff_check_in'),
    path('check-out/', staff_check_out_action, name='staff_check_out'),
    path('leave/apply/', staff_leave_apply_view, name='staff_leave_apply'),
    path('leave/<int:leave_id>/review/', staff_leave_review_view, name='staff_leave_review'),
    path('reports/pdf/', staff_attendance_pdf_view, name='staff_attendance_pdf'),
    path('reports/excel/', staff_attendance_excel_view, name='staff_attendance_excel'),

    # Payroll, Deductions & Salary Slips
    path('payroll/', payroll_dashboard_view, name='staff_payroll_dashboard'),
    path('payroll/generate/', payroll_generate_action, name='payroll_generate_action'),
    path('payroll/<int:slip_id>/', salary_slip_detail_view, name='salary_slip_detail'),
    path('payroll/<int:slip_id>/pay/', salary_slip_pay_action, name='salary_slip_pay'),
    path('payroll/<int:slip_id>/pdf/', salary_slip_pdf_view, name='salary_slip_pdf'),
]


