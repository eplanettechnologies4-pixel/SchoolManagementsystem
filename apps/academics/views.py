from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from rest_framework import viewsets, permissions
from academics.models import (
    School, AcademicYear, ClassCategory, ClassLevel, Section, Subject, CurriculumPDF,
    SubjectTeacherAssignment, ClassSubjectAssignment
)
from academics.forms import CurriculumPDFForm, SubjectForm
from academics.serializers import (
    SchoolSerializer, AcademicYearSerializer, ClassLevelSerializer,
    SectionSerializer, SubjectSerializer, SubjectTeacherAssignmentSerializer
)
from academics.services.promotion_service import preview_promotion, execute_promotion, rollback_promotion
from academics.services.class_export_import import export_class_list_pdf, export_class_list_excel, import_classes_csv
from accounts.models import User, RoleChoices
from accounts.permissions import role_required, IsAdminOrPrincipal
from accounts.services import log_audit
from django.http import HttpResponse, JsonResponse

DEFAULT_CATEGORIES_SEED = [
    ("Pre-Primary (Early Years)", "PRE_PRI", 1, "Play Group, Nursery, Prep"),
    ("Primary Wing", "PRIMARY", 2, "Class 1 to Class 5"),
    ("Middle Wing", "MIDDLE", 3, "Class 6 to Class 8"),
    ("Secondary Wing (SSC / Matric)", "SECONDARY", 4, "Class 9 & Class 10"),
    ("Higher Secondary (HSSC / Inter)", "HSSC", 5, "Class 11 & Class 12"),
]

DEFAULT_CLASSES_SEED = [
    ("Play Group (PG)", "PG", 1, "PRE_PRI"),
    ("Nursery", "NUR", 2, "PRE_PRI"),
    ("Prep", "PREP", 3, "PRE_PRI"),
    ("Class 1", "C1", 4, "PRIMARY"),
    ("Class 2", "C2", 5, "PRIMARY"),
    ("Class 3", "C3", 6, "PRIMARY"),
    ("Class 4", "C4", 7, "PRIMARY"),
    ("Class 5", "C5", 8, "PRIMARY"),
    ("Class 6", "C6", 9, "MIDDLE"),
    ("Class 7", "C7", 10, "MIDDLE"),
    ("Class 8", "C8", 11, "MIDDLE"),
    ("Class 9", "C9", 12, "SECONDARY"),
    ("Class 10", "C10", 13, "SECONDARY"),
]

def ensure_default_classes(school):
    """
    Seeds default school categories and classes (PG to Class 10) if they don't exist yet.
    """
    if not school:
        return

    cat_map = {}
    for name, code, order, desc in DEFAULT_CATEGORIES_SEED:
        cat, _ = ClassCategory.objects.get_or_create(
            school=school,
            code=code,
            defaults={'name': name, 'numeric_order': order, 'description': desc, 'is_active': True}
        )
        cat_map[code] = cat

    for item in DEFAULT_CLASSES_SEED:
        name = item[0]
        code = item[1]
        order = item[2]
        cat_code = item[3] if len(item) > 3 else None
        cat_obj = cat_map.get(cat_code)

        cls, created = ClassLevel.objects.get_or_create(
            school=school,
            code=code,
            defaults={'name': name, 'numeric_order': order, 'category': cat_obj, 'is_active': True}
        )
        if not created and not cls.category and cat_obj:
            cls.category = cat_obj
            cls.save(update_fields=['category'])

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def class_list_view(request):
    """
    Management view for all School Classes (PG to Class 10), Wings/Categories, and Sections.
    """
    school = School.objects.first()
    if school:
        ensure_default_classes(school)

    if request.method == 'POST':
        action = request.POST.get('action')
        next_url = request.POST.get('next')

        if action == 'create_category':
            name = request.POST.get('name')
            code = request.POST.get('code')
            order = request.POST.get('numeric_order', 1)
            desc = request.POST.get('description', '')
            if school and name and code:
                ClassCategory.objects.create(
                    school=school,
                    name=name,
                    code=code.upper(),
                    numeric_order=order,
                    description=desc
                )
                messages.success(request, f'Class Category "{name}" created successfully!')
            else:
                messages.error(request, 'Category name and code are required.')
            return redirect(next_url or 'class_list')

        elif action == 'create_class':
            name = request.POST.get('name')
            code = request.POST.get('code')
            numeric_order = request.POST.get('numeric_order', 1)
            category_id = request.POST.get('category')
            category = ClassCategory.objects.filter(id=category_id).first() if category_id else None
            description = request.POST.get('description', '')

            if school and name and code:
                ClassLevel.objects.create(
                    school=school,
                    name=name,
                    code=code.upper(),
                    category=category,
                    numeric_order=numeric_order,
                    description=description
                )
                messages.success(request, f'Class "{name}" created successfully!')
            else:
                messages.error(request, 'Failed to create class. Name and code are required.')
            return redirect(next_url or 'class_list')

        elif action == 'edit_class':
            class_id = request.POST.get('class_id')
            class_obj = get_object_or_404(ClassLevel, id=class_id)
            class_obj.name = request.POST.get('name', class_obj.name)
            class_obj.code = request.POST.get('code', class_obj.code).upper()
            class_obj.numeric_order = request.POST.get('numeric_order', class_obj.numeric_order)
            category_id = request.POST.get('category')
            if category_id:
                class_obj.category = ClassCategory.objects.filter(id=category_id).first()
            class_obj.save()
            messages.success(request, f'Class "{class_obj.name}" updated successfully!')
            return redirect(next_url or 'class_list')

        elif action == 'create_section':
            class_id = request.POST.get('class_level')
            name = request.POST.get('name')
            room = request.POST.get('room_number')
            capacity = request.POST.get('capacity', 40)
            teacher_id = request.POST.get('class_teacher')

            class_obj = get_object_or_404(ClassLevel, id=class_id)
            teacher = User.objects.filter(id=teacher_id, role=RoleChoices.TEACHER).first() if teacher_id else None

            Section.objects.create(
                class_level=class_obj,
                name=name,
                room_number=room,
                capacity=capacity,
                class_teacher=teacher
            )
            messages.success(request, f'Section "{name}" added to {class_obj.name}!')
            return redirect(next_url or 'class_list')

    classes = ClassLevel.objects.select_related('category').prefetch_related('sections', 'subjects').all()
    categories = ClassCategory.objects.filter(is_deleted=False, is_active=True).prefetch_related('classes')
    teachers = User.objects.filter(role=RoleChoices.TEACHER, is_active=True)

    context = {
        'classes': classes,
        'categories': categories,
        'teachers': teachers,
    }
    return render(request, 'academics/class_list.html', context)

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def class_toggle_status_view(request, pk):
    class_obj = get_object_or_404(ClassLevel, pk=pk)
    class_obj.is_active = not class_obj.is_active
    class_obj.save()
    status_str = "activated" if class_obj.is_active else "deactivated"
    messages.success(request, f'Class "{class_obj.name}" has been {status_str}.')
    return redirect('class_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def class_delete_view(request, pk):
    class_obj = get_object_or_404(ClassLevel, pk=pk)
    name = class_obj.name
    class_obj.delete()
    messages.success(request, f'Class "{name}" deleted successfully.')
    return redirect('class_list')

# --- SUBJECTS & CURRICULUM MANAGEMENT ---

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def subject_list_view(request):
    """
    Dedicated Subjects management page with Curriculum PDF upload/versioning and Subject directory.
    """
    school = School.objects.first()
    classes = ClassLevel.objects.filter(is_active=True).all()
    sections = Section.objects.select_related('class_level').all()
    teachers = User.objects.filter(role=RoleChoices.TEACHER, is_active=True)

    search_query = request.GET.get('q', '').strip()
    selected_class = request.GET.get('class_id', '')
    selected_status = request.GET.get('status', '')

    subjects = Subject.objects.select_related('class_level', 'section', 'assigned_teacher').all()

    if search_query:
        subjects = subjects.filter(name__icontains=search_query) | subjects.filter(code__icontains=search_query)
    if selected_class:
        subjects = subjects.filter(class_level_id=selected_class)
    if selected_status:
        is_act = (selected_status == 'active')
        subjects = subjects.filter(is_active=is_act)

    # Active curriculum PDF and history
    curriculum_pdfs = CurriculumPDF.objects.filter(school=school).select_related('uploaded_by') if school else []
    active_pdf = curriculum_pdfs.filter(is_active=True).first() if school else None
    pdf_history = curriculum_pdfs.filter(is_active=False) if school else []

    pdf_form = CurriculumPDFForm()
    subject_form = SubjectForm()

    context = {
        'subjects': subjects,
        'classes': classes,
        'sections': sections,
        'teachers': teachers,
        'active_pdf': active_pdf,
        'pdf_history': pdf_history,
        'pdf_form': pdf_form,
        'subject_form': subject_form,
        'search_query': search_query,
        'selected_class': selected_class,
        'selected_status': selected_status,
    }
    return render(request, 'academics/subject_list.html', context)

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def curriculum_pdf_upload_view(request):
    """
    Handles official Subject/Curriculum PDF upload with file validation and versioning.
    """
    if request.method == 'POST':
        school = School.objects.first()
        if not school:
            messages.error(request, "School environment not configured.")
            return redirect('subject_list')

        form = CurriculumPDFForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                # Archive previous active PDFs to maintain version history
                CurriculumPDF.objects.filter(school=school, is_active=True).update(is_active=False)

                pdf_obj = form.save(commit=False)
                pdf_obj.school = school
                pdf_obj.uploaded_by = request.user
                pdf_obj.file_size = request.FILES['pdf_file'].size
                pdf_obj.is_active = True
                pdf_obj.save()

            messages.success(request, f'Official Curriculum PDF "{pdf_obj.title}" uploaded successfully!')
        else:
            for field, errs in form.errors.items():
                messages.error(request, f"Upload error ({field}): {errs[0]}")

    return redirect('subject_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def curriculum_pdf_delete_view(request, pk):
    pdf_obj = get_object_or_404(CurriculumPDF, pk=pk)
    title = pdf_obj.title
    was_active = pdf_obj.is_active
    school = pdf_obj.school
    pdf_obj.delete()

    # If active was deleted, promote latest remaining PDF as active
    if was_active:
        latest = CurriculumPDF.objects.filter(school=school).first()
        if latest:
            latest.is_active = True
            latest.save()

    messages.success(request, f'Curriculum PDF "{title}" deleted successfully.')
    return redirect('subject_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def subject_create_or_edit_view(request):
    if request.method == 'POST':
        subject_id = request.POST.get('subject_id')
        if subject_id:
            subject_obj = get_object_or_404(Subject, id=subject_id)
            form = SubjectForm(request.POST, instance=subject_obj)
            verb = "updated"
        else:
            form = SubjectForm(request.POST)
            verb = "created"

        if form.is_valid():
            subject = form.save()
            messages.success(request, f'Subject "{subject.name}" [{subject.code}] {verb} successfully!')
        else:
            for field, errs in form.errors.items():
                messages.error(request, f"Subject form error ({field}): {errs[0]}")

    return redirect('subject_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def subject_toggle_status_view(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    subject.is_active = not subject.is_active
    subject.save()
    status_str = "activated" if subject.is_active else "deactivated"
    messages.success(request, f'Subject "{subject.name}" has been {status_str}.')
    return redirect('subject_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def subject_assign_teacher_view(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    if request.method == 'POST':
        teacher_id = request.POST.get('teacher_id')
        if teacher_id:
            teacher = get_object_or_404(User, id=teacher_id, role=RoleChoices.TEACHER)
            subject.assigned_teacher = teacher
            messages.success(request, f'Assigned {teacher.get_full_name() or teacher.username} to {subject.name}!')
        else:
            subject.assigned_teacher = None
            messages.info(request, f'Removed teacher assignment for {subject.name}.')
        subject.save()
    return redirect('subject_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def subject_delete_view(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    name = subject.name
    subject.delete()
    messages.success(request, f'Subject "{name}" deleted successfully.')
    return redirect('subject_list')

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def subject_assignment_view(request):
    """
    Interface to assign subjects to teachers per section and academic year.
    """
    if request.method == 'POST':
        subject_id = request.POST.get('subject')
        section_id = request.POST.get('section')
        teacher_id = request.POST.get('teacher')
        
        subject = get_object_or_404(Subject, id=subject_id)
        section = get_object_or_404(Section, id=section_id)
        teacher = get_object_or_404(User, id=teacher_id, role=RoleChoices.TEACHER)
        academic_year = AcademicYear.objects.filter(is_current=True).first()

        if academic_year:
            SubjectTeacherAssignment.objects.update_or_create(
                subject=subject,
                section=section,
                academic_year=academic_year,
                defaults={'teacher': teacher}
            )
            messages.success(request, f'Assigned {subject.name} ({section}) to {teacher.get_full_name() or teacher.username}!')
        else:
            messages.error(request, 'No active academic year found!')
        return redirect('subject_assignments')

    assignments = SubjectTeacherAssignment.objects.select_related('subject', 'section', 'teacher', 'academic_year').all()
    subjects = Subject.objects.select_related('class_level').all()
    sections = Section.objects.select_related('class_level').all()
    teachers = User.objects.filter(role=RoleChoices.TEACHER, is_active=True)

    # Calculate workload per teacher (periods per week, max 25)
    MAX_PERIODS_PER_WEEK = 25
    teacher_workloads = {}
    for t in teachers:
        assigned_count = SubjectTeacherAssignment.objects.filter(teacher=t).count()
        periods = assigned_count * 5  # Standard 5 periods per subject
        teacher_workloads[t.id] = {
            'periods': periods,
            'is_overloaded': periods > MAX_PERIODS_PER_WEEK,
            'max_periods': MAX_PERIODS_PER_WEEK
        }

    context = {
        'assignments': assignments,
        'subjects': subjects,
        'sections': sections,
        'teachers': teachers,
        'teacher_workloads': teacher_workloads,
    }
    return render(request, 'academics/subject_assignments.html', context)


# =====================================================================
# CLASS DETAILS, PROMOTION, EXPORT & IMPORT VIEWS (PART 2)
# =====================================================================

@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.TEACHER])
def class_detail_view(request, pk):
    """
    Detailed class overview displaying student roster with enrollment status,
    subjects with assigned teachers, timetable placeholder, and attendance placeholder.
    """
    class_level = get_object_or_404(ClassLevel.objects.prefetch_related('sections', 'subjects'), pk=pk)
    sections = class_level.sections.filter(is_deleted=False).select_related('class_teacher')
    students = class_level.students.filter(is_deleted=False).select_related('user', 'section', 'guardian').order_by('section__name', 'roll_number')
    subjects = class_level.subjects.filter(is_deleted=False).select_related('assigned_teacher')

    return render(request, 'academics/class_detail.html', {
        'class_level': class_level,
        'sections': sections,
        'students': students,
        'subjects': subjects,
        'total_students': students.count(),
    })


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def class_promote_view(request):
    """
    Student promotion wizard:
    Preview active students in Class X, select destination Class X+1 and target section,
    optionally skip/hold-back individual students, and execute promotion with audit log.
    """
    classes = ClassLevel.objects.filter(is_active=True, is_deleted=False).order_by('numeric_order')
    from_class_id = request.GET.get('from_class_id') or request.POST.get('from_class_id')
    to_class_id = request.GET.get('to_class_id') or request.POST.get('to_class_id')

    preview_data = None
    if from_class_id and to_class_id:
        try:
            preview_data = preview_promotion(from_class_id, to_class_id)
        except Exception as e:
            messages.error(request, f"Error generating preview: {str(e)}")

    if request.method == 'POST' and request.POST.get('action') == 'execute_promotion':
        target_section_id = request.POST.get('target_section_id')
        hold_back_ids = request.POST.getlist('hold_back_ids')

        if not target_section_id:
            messages.error(request, "Please select a target destination section.")
        else:
            try:
                result = execute_promotion(
                    from_class_id=from_class_id,
                    to_class_id=to_class_id,
                    target_section_id=target_section_id,
                    hold_back_ids=hold_back_ids,
                    user=request.user,
                    request=request
                )
                messages.success(
                    request,
                    f"Successfully promoted {result['promoted_count']} students to {result['to_class'].name} - {result['target_section'].name}! "
                    f"({result['held_back_count']} held back). Audit Log ID: #{result['audit_log_id']}"
                )
                return redirect('class_promote')
            except Exception as e:
                messages.error(request, f"Promotion execution failed: {str(e)}")

    # Fetch recent promotions from AuditLog for rollback option
    recent_promotions = request.user.school.audit_logs.filter(action='PROMOTION').order_by('-timestamp')[:10] if getattr(request.user, 'school', None) else []

    return render(request, 'academics/class_promote.html', {
        'classes': classes,
        'from_class_id': from_class_id,
        'to_class_id': to_class_id,
        'preview': preview_data,
        'recent_promotions': recent_promotions,
    })


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def class_promote_rollback_view(request):
    """
    Rolls back a promotion session using the AuditLog record.
    """
    if request.method == 'POST':
        audit_log_id = request.POST.get('audit_log_id')
        try:
            res = rollback_promotion(audit_log_id, user=request.user, request=request)
            messages.info(request, f"Successfully rolled back promotion! Reverted {res['reverted_count']} students to their previous classes.")
        except Exception as e:
            messages.error(request, f"Rollback failed: {str(e)}")

    return redirect('class_promote')


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.TEACHER])
def class_export_pdf_view(request, pk):
    """
    Exports a clean printable PDF of student directory for a class.
    """
    class_level = get_object_or_404(ClassLevel, pk=pk)
    pdf_bytes = export_class_list_pdf(class_level)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{class_level.code}_Students.pdf"'
    return response


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN, RoleChoices.TEACHER])
def class_export_excel_view(request, pk):
    """
    Exports an Excel .xlsx sheet of student roster for a class.
    """
    class_level = get_object_or_404(ClassLevel, pk=pk)
    excel_bytes = export_class_list_excel(class_level)
    response = HttpResponse(excel_bytes, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{class_level.code}_Students.xlsx"'
    return response


@login_required
@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ADMIN])
def class_import_csv_view(request):
    """
    Bulk import of classes and sections via CSV with instant validation reporting.
    """
    school = getattr(request.user, 'school', None) or School.objects.first()
    report = None

    if request.method == 'POST' and request.FILES.get('csv_file'):
        file_obj = request.FILES['csv_file']
        report = import_classes_csv(file_obj, school=school, user=request.user, request=request)
        if report['errors']:
            messages.warning(request, f"Import finished with {len(report['errors'])} errors/notices.")
        else:
            messages.success(request, f"Import complete! {report['classes_created']} classes and {report['sections_created']} sections added.")

    return render(request, 'academics/class_import_csv.html', {
        'report': report
    })


# --- DRF API ViewSets ---

class SchoolViewSet(viewsets.ModelViewSet):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = [IsAdminOrPrincipal]

class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer
    permission_classes = [IsAdminOrPrincipal]

class ClassLevelViewSet(viewsets.ModelViewSet):
    queryset = ClassLevel.objects.all()
    serializer_class = ClassLevelSerializer
    permission_classes = [permissions.IsAuthenticated]

class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.all()
    serializer_class = SectionSerializer
    permission_classes = [permissions.IsAuthenticated]

class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    permission_classes = [permissions.IsAuthenticated]

class SubjectTeacherAssignmentViewSet(viewsets.ModelViewSet):
    queryset = SubjectTeacherAssignment.objects.all()
    serializer_class = SubjectTeacherAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]
