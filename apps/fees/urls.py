from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.fee_dashboard, name='fee_dashboard'),
    path('vouchers/', views.voucher_list, name='voucher_list'),
    path('vouchers/create/', views.voucher_create, name='voucher_create'),
    path('vouchers/<int:pk>/', views.voucher_detail, name='voucher_detail'),
    path('vouchers/<int:pk>/edit/', views.voucher_edit, name='voucher_edit'),
    path('vouchers/<int:pk>/pdf/', views.voucher_pdf, name='voucher_pdf'),
    path('vouchers/<int:pk>/print/', views.voucher_print, name='voucher_print'),
    path('vouchers/<int:pk>/pay/', views.record_payment, name='record_payment'),
    path('vouchers/<int:pk>/cancel/', views.voucher_cancel, name='voucher_cancel'),

    # Payment Receipt URLs
    path('receipts/<int:payment_id>/print/', views.receipt_print, name='receipt_print'),
    path('receipts/<int:payment_id>/pdf/', views.receipt_pdf, name='receipt_pdf'),

    # Helper API Endpoints
    path('api/student-info/<int:student_id>/', views.api_get_student_info, name='api_student_fee_info'),
    path('api/whatsapp-preview/<int:pk>/', views.api_whatsapp_preview, name='api_whatsapp_preview'),

    # Standardized Challan & Virtual Payment Routes (Part 1)
    path('challans/', views.challan_list, name='challan_list'),
    path('challans/create/', views.challan_create, name='challan_create'),
    path('challans/<int:pk>/', views.challan_detail, name='challan_detail'),
    path('challans/<int:pk>/pay-virtual/', views.challan_pay_virtual, name='challan_pay_virtual'),
    path('challans/<int:pk>/pdf/', views.challan_pdf, name='challan_pdf'),
    path('challans/payments/<int:payment_id>/reverse/', views.challan_reverse_payment, name='challan_reverse_payment'),
    path('my-status/', views.student_fee_portal, name='student_fee_portal'),
]
