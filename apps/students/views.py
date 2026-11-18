import json
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404, HttpResponseForbidden, FileResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rest_framework import viewsets, permissions

from accounts.models import User, RoleChoices, AuditLog
from accounts.permissions import role_required, IsAdminOrPrincipal, IsTeacherUser
from accounts.services import log_audit
from academics.models import ClassLevel, Section
from students.models import (
    StudentProfile, GuardianProfile, StudentDocument,
    StudentStatusChoices, AdmissionDraft, StudentDocumentType
)
from students.forms import (
    StudentAdmissionStep1Form, StudentAdmissionStep2Form,
    StudentAdmissionStep3Form, StudentAdmissionStep4Form,
    StudentEditForm
)
from students.services.student_service import (
    generate_admission_number_atomic, generate_roll_number_atomic,
    find_or_create_guardian, check_duplicate_student,
    process_and_compress_photo, generate_admission_letter_pdf,
    generate_leaving_certificate_pdf
)
from students.utils import generate_student_id_card_pdf
from students.services.bulk_import import import_students_csv
from students.serializers import StudentProfileSerializer, GuardianProfileSerializer


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def student_admission_view(request):
    """
    5-Step Admission Wizard with Draft saving, Duplicate Detection,
    Sibling Auto-linking, Section Capacity Check, and Document Uploads.
    """
    draft_id = request.GET.get('draft_id') or request.POST.get('draft_id')
    draft = None
    if draft_id:
        draft = AdmissionDraft.objects.filter(id=draft_id).first()

    step = int(request.POST.get('wizard_step', 1))
    
    # Session or Draft state dictionary
    wizard_data = request.session.get('admission_wizard_data', {})
    if draft and not wizard_data:
        wizard_data = draft.data

    step1_form = StudentAdmissionStep1Form(prefix='step1', data=wizard_data.get('step1') or None)
    step2_form = StudentAdmissionStep2Form(prefix='step2', data=wizard_data.get('step2') or None)
    step3_form = StudentAdmissionStep3Form(prefix='step3', data=wizard_data.get('step3') or None)
    step4_form = StudentAdmissionStep4Form(prefix='step4')

    duplicate_warnings = []

    if request.method == 'POST':
        action = request.POST.get('action', 'next')

        if action == 'save_draft':
            # Save whatever data is submitted so far into AdmissionDraft
            current_data = request.POST.dict()
            title = f"{current_data.get('step1-first_name', 'Draft')} {current_data.get('step1-last_name', '')}".strip() or "Untitled Admission"
            if not draft:
                draft = AdmissionDraft.objects.create(
                    school=request.user.school,
                    title=title,
                    step=step,
                    data=wizard_data,
                    created_by=request.user
                )
            else:
                draft.data = wizard_data
                draft.step = step
                draft.title = title
                draft.save()
            messages.info(request, f"Draft '{draft.title}' saved successfully.")
            return redirect(f"{request.path}?draft_id={draft.id}")

        if step == 1:
            step1_form = StudentAdmissionStep1Form(request.POST, request.FILES, prefix='step1')
            if step1_form.is_valid():
                s1_clean = dict(step1_form.cleaned_data)
                if 'photo' in s1_clean:
                    del s1_clean['photo']

                # Photo handling if uploaded
                if 'step1-photo' in request.FILES:
                    try:
                        compressed_io = process_and_compress_photo(request.FILES['step1-photo'])
                        temp_photo_path = default_storage.save(
                            f'temp_uploads/photo_{uuid.uuid4().hex}.webp',
                            ContentFile(compressed_io.getvalue())
                        )
                        wizard_data['temp_photo_path'] = temp_photo_path
                    except Exception as e:
                        messages.warning(request, f"Photo note: {str(e)}")

                if s1_clean.get('dob'):
                    s1_clean['dob'] = str(s1_clean['dob'])

                wizard_data['step1'] = s1_clean

                # Check duplicate B-Form
                bform = s1_clean.get('bform_number')
                is_dup, warn_msg, dup_obj = check_duplicate_student(bform_number=bform, school=request.user.school)
                if is_dup:
                    duplicate_warnings.append(warn_msg)

                request.session['admission_wizard_data'] = wizard_data
                step = 2

        elif step == 2:
            step2_form = StudentAdmissionStep2Form(request.POST, prefix='step2')
            if step2_form.is_valid():
                wizard_data['step2'] = step2_form.cleaned_data
                # Check duplicate by (name + DOB + guardian CNIC)
                s1_data = wizard_data.get('step1', {})
                full_name = f"{s1_data.get('first_name', '')} {s1_data.get('last_name', '')}".strip()
                dob = s1_data.get('dob')
                cnic = step2_form.cleaned_data.get('guardian_cnic')
                is_dup, warn_msg, _ = check_duplicate_student(
                    full_name=full_name,
                    dob=dob,
                    guardian_cnic=cnic,
                    school=request.user.school
                )
                if is_dup:
                    duplicate_warnings.append(warn_msg)

                # Check sibling auto-link possibility
                existing_guardian = GuardianProfile.objects.filter(cnic=cnic).first()
                if existing_guardian:
                    siblings = existing_guardian.students.all()
                    if siblings.exists():
                        sib_names = ", ".join([s.get_full_name() for s in siblings[:3]])
                        messages.info(request, f"Guardian CNIC matches existing record. Auto-linking siblings: {sib_names}.")

                request.session['admission_wizard_data'] = wizard_data
                step = 3

        elif step == 3:
            step3_form = StudentAdmissionStep3Form(request.POST, prefix='step3')
            if step3_form.is_valid():
                s_data = step3_form.cleaned_data
                wizard_data['step3'] = {
                    'class_level_id': s_data['class_level'].id,
                    'class_level_name': s_data['class_level'].name,
                    'section_id': s_data['section'].id,
                    'section_name': s_data['section'].name,
                    'admission_date': str(s_data['admission_date']),
                    'previous_school': s_data.get('previous_school', ''),
                    'previous_class': s_data.get('previous_class', ''),
                    'last_result': s_data.get('last_result', ''),
                }
                request.session['admission_wizard_data'] = wizard_data
                step = 4

        elif step == 4:
            step4_form = StudentAdmissionStep4Form(request.POST, request.FILES, prefix='step4')
            if step4_form.is_valid():
                files_data = wizard_data.get('step4_files', {})
                for doc_field in ['step4-bform_doc', 'step4-cnic_doc', 'step4-marksheet_doc', 'step4-transfer_doc']:
                    if doc_field in request.FILES:
                        up_file = request.FILES[doc_field]
                        temp_doc_path = default_storage.save(f'temp_uploads/doc_{uuid.uuid4().hex}_{up_file.name}', up_file)
                        files_data[doc_field] = {
                            'path': temp_doc_path,
                            'name': up_file.name,
                            'size': up_file.size
                        }
                wizard_data['step4_files'] = files_data
                request.session['admission_wizard_data'] = wizard_data
                step = 5  # Step 5 is Review + Submit

        elif step == 5 and action == 'submit':
            # Complete creation in atomic block
            try:
                with transaction.atomic():
                    s1 = wizard_data.get('step1', {})
                    s2 = wizard_data.get('step2', {})
                    s3 = wizard_data.get('step3', {})

                    class_obj = ClassLevel.objects.get(id=s3['class_level_id'])
                    section_obj = Section.objects.select_for_update().get(id=s3['section_id'])

                    if section_obj.is_full:
                        messages.error(request, f"Cannot complete admission: Section '{section_obj.name}' is already at full capacity.")
                        step = 3
                        return render(request, 'students/admission_wizard.html', locals())

                    # 1. Guardian find or create
                    guardian, _ = find_or_create_guardian(s2, school=request.user.school)

                    # 2. Sequential numbers
                    adm_no = generate_admission_number_atomic(school=request.user.school)
                    roll_no = generate_roll_number_atomic(class_obj, section_obj)

                    # 3. Create Student User account
                    username = f"std_{adm_no.lower().replace('-', '_')}"
                    student_user = User.objects.create_user(
                        username=username,
                        email=f"{username}@school.local",
                        password="Student123!",
                        first_name=s1['first_name'],
                        last_name=s1['last_name'],
                        role=RoleChoices.STUDENT,
                        school=request.user.school,
                        cnic_bform=s1['bform_number'],
                        address=s2.get('address', ''),
                        phone_number=s2.get('emergency_contact', ''),
                        must_change_password=True
                    )

                    # 4. Create Student Profile
                    student_profile = StudentProfile.objects.create(
                        user=student_user,
                        school=request.user.school,
                        admission_number=adm_no,
                        roll_number=roll_no,
                        class_level=class_obj,
                        section=section_obj,
                        guardian=guardian,
                        dob=s1.get('dob'),
                        gender=s1.get('gender', 'MALE'),
                        bform_number=s1.get('bform_number'),
                        religion=s1.get('religion', 'Islam'),
                        blood_group=s1.get('blood_group', ''),
                        nationality=s1.get('nationality', 'Pakistani'),
                        admission_date=s3.get('admission_date'),
                        previous_school=s3.get('previous_school', ''),
                        previous_class=s3.get('previous_class', ''),
                        last_result=s3.get('last_result', ''),
                        emergency_contact=s2.get('emergency_contact', ''),
                        address=s2.get('address', ''),
                        status=StudentStatusChoices.ACTIVE
                    )

                    # Attach photo if uploaded in step 1
                    photo_path = wizard_data.get('temp_photo_path')
                    if photo_path and default_storage.exists(photo_path):
                        with default_storage.open(photo_path, 'rb') as pf:
                            student_profile.photo.save(f"{adm_no.lower()}_photo.webp", pf, save=True)
                        default_storage.delete(photo_path)

                    # 5. Documents
                    files_data = wizard_data.get('step4_files', {})
                    for doc_field, doc_type in [
                        ('step4-bform_doc', StudentDocumentType.B_FORM),
                        ('step4-cnic_doc', StudentDocumentType.CNIC),
                        ('step4-marksheet_doc', StudentDocumentType.MARKSHEET),
                        ('step4-transfer_doc', StudentDocumentType.TRANSFER_CERTIFICATE),
                    ]:
                        if doc_field in files_data:
                            f_info = files_data[doc_field]
                            f_path = f_info['path']
                            if default_storage.exists(f_path):
                                with default_storage.open(f_path, 'rb') as df:
                                    s_doc = StudentDocument(
                                        school=request.user.school,
                                        student=student_profile,
                                        document_type=doc_type,
                                        title=doc_type.replace('_', ' ').title(),
                                        file_size=f_info['size']
                                    )
                                    s_doc.file.save(f_info['name'], df, save=True)
                                default_storage.delete(f_path)
                        elif doc_field in request.FILES:
                            uploaded = request.FILES[doc_field]
                            StudentDocument.objects.create(
                                school=request.user.school,
                                student=student_profile,
                                document_type=doc_type,
                                title=doc_type.replace('_', ' ').title(),
                                file=uploaded,
                                file_size=uploaded.size
                            )

                    # Log audit
                    log_audit(
                        user=request.user,
                        action="CREATE",
                        model_name="StudentProfile",
                        object_id=student_profile.id,
                        new_values={'admission_number': adm_no, 'name': student_profile.get_full_name(), 'class': class_obj.name},
                        request=request
                    )

                    # Clean up draft and session
                    if draft:
                        draft.delete()
                    if 'admission_wizard_data' in request.session:
                        del request.session['admission_wizard_data']

                    messages.success(request, f"Student '{student_profile.get_full_name()}' successfully admitted! Admission No: {adm_no}, Roll No: {roll_no}.")
                    return redirect('student_detail', student_id=student_profile.id)

            except Exception as e:
                messages.error(request, f"Failed to complete admission: {str(e)}")

    context = {
        'step': step,
        'step1_form': step1_form,
        'step2_form': step2_form,
        'step3_form': step3_form,
        'step4_form': step4_form,
        'wizard_data': wizard_data,
        'draft': draft,
        'duplicate_warnings': duplicate_warnings,
    }
    return render(request, 'students/admission_wizard.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def student_edit_view(request, student_id):
    """
    Student edit view with full AuditLog change history and status management.
    """
    student = get_object_or_404(StudentProfile.objects.select_related('user', 'class_level', 'section', 'guardian'), id=student_id)
    
    if request.method == 'POST':
        form = StudentEditForm(request.POST, instance=student)
        if form.is_valid():
            old_data = {
                'status': student.status,
                'class_level': student.class_level.name if student.class_level else '',
                'section': student.section.name if student.section else '',
                'roll_number': student.roll_number,
                'address': student.address,
                'first_name': student.user.first_name,
                'last_name': student.user.last_name,
            }

            updated_student = form.save(commit=False)
            
            # Update user model fields
            first_name = form.cleaned_data.get('first_name')
            last_name = form.cleaned_data.get('last_name')
            phone = form.cleaned_data.get('phone_number')
            student.user.first_name = first_name
            student.user.last_name = last_name
            student.user.phone_number = phone
            student.user.save()

            updated_student.save()

            new_data = {
                'status': updated_student.status,
                'class_level': updated_student.class_level.name if updated_student.class_level else '',
                'section': updated_student.section.name if updated_student.section else '',
                'roll_number': updated_student.roll_number,
                'address': updated_student.address,
                'first_name': first_name,
                'last_name': last_name,
            }

            # Record in AuditLog
            log_audit(
                user=request.user,
                action="UPDATE",
                model_name="StudentProfile",
                object_id=student.id,
                old_values=old_data,
                new_values=new_data,
                request=request
            )

            messages.success(request, f"Student profile for '{student.get_full_name()}' updated successfully.")
            return redirect('student_detail', student_id=student.id)
    else:
        form = StudentEditForm(instance=student)

    # Fetch recent audit logs for this student
    audit_logs = AuditLog.objects.filter(model_name="StudentProfile", object_id=str(student.id)).order_by('-timestamp')[:10]

    context = {
        'student': student,
        'form': form,
        'audit_logs': audit_logs,
    }
    return render(request, 'students/student_edit.html', context)


@login_required
def student_detail_view(request, student_id):
    """
    Detailed profile view for a student.
    Enforces RBAC & object-level ownership:
    - Student: only own profile.
    - Parent: only own wards.
    - Teacher/Admin/Accountant: school scoped.
    """
    student = get_object_or_404(
        StudentProfile.objects.select_related('user', 'class_level', 'section', 'guardian', 'school'),
        id=student_id
    )
    user = request.user

    # Object-level check
    if user.is_student and student.user != user:
        messages.error(request, "Permission denied. You can only view your own profile.")
        return redirect('dashboard_student')

    if user.is_parent:
        guardian = getattr(user, 'guardian_profile', None)
        if not guardian or not guardian.students.filter(id=student.id).exists():
            messages.error(request, "Permission denied. You can only view your own child's profile.")
            return redirect('dashboard_parent')

    documents = student.documents.filter(is_deleted=False)
    audit_logs = AuditLog.objects.filter(model_name="StudentProfile", object_id=str(student.id)).order_by('-timestamp')[:5]

    context = {
        'student': student,
        'documents': documents,
        'audit_logs': audit_logs,
    }
    return render(request, 'students/student_detail.html', context)


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.TEACHER, RoleChoices.ACCOUNTANT])
def student_list_view(request):
    """
    Paginated, searchable, and filtered student directory.
    """
    query = request.GET.get('q', '').strip()
    class_filter = request.GET.get('class_id')
    section_filter = request.GET.get('section_id')
    status_filter = request.GET.get('status')

    qs = StudentProfile.objects.select_related('user', 'class_level', 'section', 'guardian').all()

    if query:
        qs = qs.filter(
            user__first_name__icontains=query
        ) | qs.filter(
            user__last_name__icontains=query
        ) | qs.filter(
            admission_number__icontains=query
        ) | qs.filter(
            roll_number__icontains=query
        ) | qs.filter(
            bform_number__icontains=query
        )

    if class_filter:
        qs = qs.filter(class_level_id=class_filter)
    if section_filter:
        qs = qs.filter(section_id=section_filter)
    if status_filter:
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    classes = ClassLevel.objects.all()
    sections = Section.objects.all()

    context = {
        'page_obj': page_obj,
        'students': page_obj,
        'classes': classes,
        'sections': sections,
        'query': query,
        'class_filter': class_filter,
        'section_filter': section_filter,
        'status_filter': status_filter,
        'status_choices': StudentStatusChoices.choices,
    }
    return render(request, 'students/student_list.html', context)


@login_required
def student_id_card_pdf_view(request, student_id):
    """
    Download student ID Card PDF with object-level permission check.
    """
    student = get_object_or_404(StudentProfile, id=student_id)
    user = request.user

    if user.is_student and student.user != user:
        return HttpResponseForbidden("Access denied")
    if user.is_parent:
        guardian = getattr(user, 'guardian_profile', None)
        if not guardian or not guardian.students.filter(id=student.id).exists():
            return HttpResponseForbidden("Access denied")

    pdf_data = generate_student_id_card_pdf(student)
    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="ID_Card_{student.admission_number}.pdf"'
    return response


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.TEACHER])
def student_admission_letter_pdf_view(request, student_id):
    """
    Serves official Admission Letter PDF.
    """
    student = get_object_or_404(StudentProfile, id=student_id)
    pdf_bytes = generate_admission_letter_pdf(student)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Admission_Letter_{student.admission_number}.pdf"'
    return response


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def student_leaving_cert_pdf_view(request, student_id):
    """
    Serves official School Leaving Certificate PDF.
    """
    student = get_object_or_404(StudentProfile, id=student_id)
    reason = request.GET.get('reason')
    pdf_bytes = generate_leaving_certificate_pdf(student, reason=reason)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Leaving_Certificate_{student.admission_number}.pdf"'
    return response


@login_required
def student_document_download(request, doc_id):
    """
    Permission-checked view to serve private student documents.
    """
    doc = get_object_or_404(StudentDocument, id=doc_id, is_deleted=False)
    student = doc.student
    user = request.user

    # Object-level check: Admin/Staff or the student or the student's guardian
    is_staff = user.is_superuser or user.role in [RoleChoices.ADMIN, RoleChoices.TEACHER, RoleChoices.ACCOUNTANT]
    is_own = user.is_student and student.user == user
    is_guardian = False
    if user.is_parent:
        guardian = getattr(user, 'guardian_profile', None)
        if guardian and guardian.students.filter(id=student.id).exists():
            is_guardian = True

    if not (is_staff or is_own or is_guardian):
        return HttpResponseForbidden("You do not have permission to access this document.")

    if not doc.file or not doc.file.storage.exists(doc.file.name):
        raise Http404("Document file not found on server.")

    return FileResponse(doc.file.open('rb'), as_attachment=False, filename=doc.file.name.split('/')[-1])


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def student_import_csv_view(request):
    """
    Bulk import students via CSV with detailed validation report.
    """
    report = None
    if request.method == 'POST' and 'csv_file' in request.FILES:
        csv_file = request.FILES['csv_file']
        report = import_students_csv(csv_file, school=request.user.school, created_by=request.user)
        if report['success_count'] > 0:
            messages.success(request, f"Successfully imported {report['success_count']} students.")
        if report['errors']:
            messages.warning(request, f"{len(report['errors'])} rows could not be imported. Review the error report below.")

    return render(request, 'students/student_import_csv.html', {'report': report})


# --- DRF API ViewSets ---

class StudentProfileViewSet(viewsets.ModelViewSet):
    queryset = StudentProfile.objects.all()
    serializer_class = StudentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_student:
            return StudentProfile.objects.filter(user=user)
        if user.is_parent:
            guardian = getattr(user, 'guardian_profile', None)
            if guardian:
                return guardian.students.all()
            return StudentProfile.objects.none()
        return StudentProfile.objects.all()


class GuardianProfileViewSet(viewsets.ModelViewSet):
    queryset = GuardianProfile.objects.all()
    serializer_class = GuardianProfileSerializer
    permission_classes = [IsAdminOrPrincipal]
