import os
import sys
import io
import django
from django.core.files.uploadedfile import SimpleUploadedFile

# Setup Django Environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'apps'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sms_core.settings')
django.setup()

from django.test import Client
from django.urls import reverse
from accounts.models import User, RoleChoices
from academics.models import School, ClassLevel, Section, Subject, CurriculumPDF

def run_tests():
    print("--- STARTING ACADEMICS UPGRADE E2E VERIFICATION SUITE ---")
    client = Client()

    # 1. Authenticate as Principal/Admin
    admin_user = User.objects.filter(role=RoleChoices.ADMIN).first()
    if not admin_user:
        admin_user = User.objects.filter(role=RoleChoices.SUPER_ADMIN).first()
    
    assert admin_user is not None, "Admin user required for test"
    client.force_login(admin_user)
    print(f"1. Authenticated as: {admin_user.username} ({admin_user.get_role_display()})")

    # 2. Check Classes Page and Default Classes Seeding
    classes_url = reverse('class_list')
    res = client.get(classes_url)
    assert res.status_code == 200, f"Class list expected 200, got {res.status_code}"
    print("2. [PASS] GET /academics/classes/ returned HTTP 200 OK")

    # Verify seed classes exist
    seed_codes = ["PG", "NUR", "PREP", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"]
    existing_codes = set(ClassLevel.objects.values_list('code', flat=True))
    for sc in seed_codes:
        assert sc in existing_codes, f"Expected seed class {sc} not found in database"
    print(f"   [PASS] Verified default classes PG through Class 10 present (Total classes: {ClassLevel.objects.count()})")

    # 3. Test Class Status Toggle
    c9 = ClassLevel.objects.filter(code='C9').first()
    assert c9 is not None
    toggle_url = reverse('class_toggle_status', kwargs={'pk': c9.pk})
    res = client.post(toggle_url)
    assert res.status_code == 302
    c9.refresh_from_db()
    assert c9.is_active is False
    print("3. [PASS] Class status toggle (Activate/Deactivate) verified")
    # Restore active
    client.post(toggle_url)

    # 4. Check Subjects Directory Page
    subjects_url = reverse('subject_list')
    res = client.get(subjects_url)
    assert res.status_code == 200, f"Subject list expected 200, got {res.status_code}"
    print("4. [PASS] GET /academics/subjects/ returned HTTP 200 OK")

    # 5. Test Curriculum PDF Upload & Versioning
    pdf_content = b"%PDF-1.4 %--- Fake PDF Content for Test ---%"
    uploaded_pdf = SimpleUploadedFile("Official_Syllabus_2026.pdf", pdf_content, content_type="application/pdf")
    
    upload_url = reverse('curriculum_pdf_upload')
    res = client.post(upload_url, {
        'title': 'Official Curriculum 2026-2027',
        'pdf_file': uploaded_pdf,
        'version_notes': 'Initial release'
    })
    assert res.status_code == 302
    
    active_pdf = CurriculumPDF.objects.filter(is_active=True).first()
    assert active_pdf is not None
    assert active_pdf.title == 'Official Curriculum 2026-2027'
    print(f"5. [PASS] Curriculum PDF uploaded: '{active_pdf.title}' (Size: {active_pdf.file_size} bytes)")

    # Upload v2 PDF to test versioning
    uploaded_pdf_v2 = SimpleUploadedFile("Official_Syllabus_2027_v2.pdf", pdf_content, content_type="application/pdf")
    client.post(upload_url, {
        'title': 'Revised Curriculum v2',
        'pdf_file': uploaded_pdf_v2,
        'version_notes': 'Revised syllabus'
    })
    active_pdf_v2 = CurriculumPDF.objects.filter(is_active=True).first()
    assert active_pdf_v2.title == 'Revised Curriculum v2'
    old_pdf = CurriculumPDF.objects.filter(pk=active_pdf.pk).first()
    assert old_pdf.is_active is False
    print("   [PASS] Curriculum PDF versioning verified (Previous version archived, new version set active)")

    # 6. Test Subject Creation, Teacher Assignment & Actions
    Subject.objects.filter(code='CS-10').delete()
    teacher_user = User.objects.filter(role=RoleChoices.TEACHER, is_active=True).first()
    c10 = ClassLevel.objects.filter(code='C10').first()
    
    save_subj_url = reverse('subject_save')
    res = client.post(save_subj_url, {
        'class_level': c10.id,
        'name': 'Advanced Computer Science',
        'code': 'CS-10',
        'assigned_teacher': teacher_user.id if teacher_user else '',
        'is_elective': 'on',
        'is_active': 'on'
    })
    assert res.status_code == 302
    
    cs_subj = Subject.objects.filter(code='CS-10').first()
    assert cs_subj is not None
    assert cs_subj.name == 'Advanced Computer Science'
    assert cs_subj.is_active is True
    print(f"6. [PASS] Subject '{cs_subj.name}' [{cs_subj.code}] created and assigned successfully")

    # 7. Test Subject Status Toggle
    sub_toggle_url = reverse('subject_toggle_status', kwargs={'pk': cs_subj.pk})
    client.post(sub_toggle_url)
    cs_subj.refresh_from_db()
    assert cs_subj.is_active is False
    print("7. [PASS] Subject status toggle (Active/Inactive) verified")

    print("\n=======================================================")
    print("ALL ACADEMICS MODULE E2E TESTS PASSED PERFECTLY!")
    print("=======================================================")

if __name__ == '__main__':
    run_tests()
