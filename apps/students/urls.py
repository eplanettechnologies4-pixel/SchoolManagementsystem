from django.urls import path, include
from rest_framework.routers import DefaultRouter
from students.views import (
    student_admission_view, student_list_view, student_detail_view,
    student_edit_view, student_id_card_pdf_view,
    student_admission_letter_pdf_view, student_leaving_cert_pdf_view,
    student_document_download, student_import_csv_view,
    StudentProfileViewSet, GuardianProfileViewSet
)

router = DefaultRouter()
router.register(r'students', StudentProfileViewSet, basename='student-api')
router.register(r'guardians', GuardianProfileViewSet, basename='guardian-api')

urlpatterns = [
    path('', student_list_view, name='student_list'),
    path('admission/', student_admission_view, name='student_admission'),
    path('import-csv/', student_import_csv_view, name='student_import_csv'),
    path('<int:student_id>/', student_detail_view, name='student_detail'),
    path('<int:student_id>/edit/', student_edit_view, name='student_edit'),
    path('<int:student_id>/id-card/', student_id_card_pdf_view, name='student_id_card_pdf'),
    path('<int:student_id>/admission-letter/', student_admission_letter_pdf_view, name='student_admission_letter_pdf'),
    path('<int:student_id>/leaving-certificate/', student_leaving_cert_pdf_view, name='student_leaving_certificate_pdf'),
    path('documents/<int:doc_id>/download/', student_document_download, name='student_document_download'),
    path('api/', include(router.urls)),
]
