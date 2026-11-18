from django.urls import path, include
from rest_framework.routers import DefaultRouter
from academics import views

router = DefaultRouter()
router.register(r'schools', views.SchoolViewSet, basename='school-api')
router.register(r'academic-years', views.AcademicYearViewSet, basename='academicyear-api')
router.register(r'classes', views.ClassLevelViewSet, basename='classlevel-api')
router.register(r'sections', views.SectionViewSet, basename='section-api')
router.register(r'subjects', views.SubjectViewSet, basename='subject-api')
router.register(r'assignments', views.SubjectTeacherAssignmentViewSet, basename='assignment-api')

urlpatterns = [
    # Classes Management
    path('classes/', views.class_list_view, name='class_list'),
    path('classes/<int:pk>/', views.class_detail_view, name='class_detail'),
    path('classes/<int:pk>/toggle/', views.class_toggle_status_view, name='class_toggle_status'),
    path('classes/<int:pk>/delete/', views.class_delete_view, name='class_delete'),
    path('classes/<int:pk>/export-pdf/', views.class_export_pdf_view, name='class_export_pdf'),
    path('classes/<int:pk>/export-excel/', views.class_export_excel_view, name='class_export_excel'),
    path('classes/import-csv/', views.class_import_csv_view, name='class_import_csv'),
    path('classes/promote/', views.class_promote_view, name='class_promote'),
    path('classes/promote/rollback/', views.class_promote_rollback_view, name='class_promote_rollback'),

    # Subjects & Curriculum PDF Management
    path('subjects/', views.subject_list_view, name='subject_list'),
    path('subjects/save/', views.subject_create_or_edit_view, name='subject_save'),
    path('subjects/pdf/upload/', views.curriculum_pdf_upload_view, name='curriculum_pdf_upload'),
    path('subjects/pdf/<int:pk>/delete/', views.curriculum_pdf_delete_view, name='curriculum_pdf_delete'),
    path('subjects/<int:pk>/toggle/', views.subject_toggle_status_view, name='subject_toggle_status'),
    path('subjects/<int:pk>/assign-teacher/', views.subject_assign_teacher_view, name='subject_assign_teacher'),
    path('subjects/<int:pk>/delete/', views.subject_delete_view, name='subject_delete'),

    # Legacy Teacher Assignments view
    path('assignments/', views.subject_assignment_view, name='subject_assignments'),

    path('api/', include(router.urls)),
]
