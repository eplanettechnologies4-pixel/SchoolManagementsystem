from django.db import transaction
from django.core.exceptions import ValidationError
from accounts.models import AuditLog
from accounts.services import log_audit
from academics.models import ClassLevel, Section
from students.models import StudentProfile


def preview_promotion(from_class_id, to_class_id):
    """
    Returns preview data for moving students from from_class to to_class:
    active students, destination class sections, and their remaining capacities.
    """
    from_class = ClassLevel.objects.get(pk=from_class_id)
    to_class = ClassLevel.objects.get(pk=to_class_id)

    students = StudentProfile.objects.filter(
        class_level=from_class,
        is_deleted=False,
        status='ACTIVE'
    ).select_related('user', 'section').order_by('roll_number')

    sections = Section.objects.filter(
        class_level=to_class,
        is_active=True,
        is_deleted=False
    )
    section_capacities = []
    for sec in sections:
        enrolled = sec.current_enrollment_count
        avail = max(0, sec.capacity - enrolled)
        section_capacities.append({
            'section': sec,
            'enrolled': enrolled,
            'capacity': sec.capacity,
            'available': avail,
            'is_full': avail == 0
        })

    return {
        'from_class': from_class,
        'to_class': to_class,
        'students': students,
        'total_students': students.count(),
        'section_capacities': section_capacities,
    }


@transaction.atomic
def execute_promotion(from_class_id, to_class_id, target_section_id, hold_back_ids=None, user=None, request=None):
    """
    Bulk promotes active students from from_class to to_class/target_section.
    Supports skipping/holding back students.
    Records snapshot into AuditLog for full rollback capability.
    """
    hold_back_ids = set(str(sid) for sid in (hold_back_ids or []))
    from_class = ClassLevel.objects.get(pk=from_class_id)
    to_class = ClassLevel.objects.get(pk=to_class_id)
    target_section = Section.objects.select_for_update().get(pk=target_section_id)

    students_to_promote = StudentProfile.objects.select_for_update().filter(
        class_level=from_class,
        is_deleted=False,
        status='ACTIVE'
    ).exclude(id__in=hold_back_ids)

    count_to_promote = students_to_promote.count()
    avail = target_section.capacity - target_section.current_enrollment_count
    if count_to_promote > avail:
        raise ValidationError(
            f"Target Section '{target_section.name}' only has {avail} available seats, "
            f"but {count_to_promote} students were selected for promotion."
        )

    promoted_records = []
    for student in students_to_promote:
        promoted_records.append({
            'student_id': student.id,
            'admission_number': student.admission_number,
            'student_name': student.get_full_name(),
            'prev_class_id': from_class.id,
            'prev_class_name': from_class.name,
            'prev_section_id': student.section_id,
            'prev_section_name': student.section.name if student.section else '',
            'prev_roll_number': student.roll_number,
        })
        student.class_level = to_class
        student.section = target_section
        student.save(update_fields=['class_level', 'section', 'updated_at'])

    audit_entry = log_audit(
        user=user,
        action='PROMOTION',
        instance=from_class,
        changes={
            'from_class_id': from_class.id,
            'from_class_name': from_class.name,
            'to_class_id': to_class.id,
            'to_class_name': to_class.name,
            'target_section_id': target_section.id,
            'target_section_name': target_section.name,
            'promoted_count': len(promoted_records),
            'promoted_records': promoted_records,
            'held_back_ids': list(hold_back_ids),
        },
        request=request
    )

    return {
        'promoted_count': len(promoted_records),
        'held_back_count': len(hold_back_ids),
        'audit_log_id': audit_entry.id,
        'from_class': from_class,
        'to_class': to_class,
        'target_section': target_section,
    }


@transaction.atomic
def rollback_promotion(audit_log_id, user=None, request=None):
    """
    Reverts a student promotion session back to its exact prior class and section states.
    Uses recorded AuditLog snapshot.
    """
    audit = AuditLog.objects.select_for_update().get(pk=audit_log_id, action='PROMOTION')
    changes = audit.changes
    promoted_records = changes.get('promoted_records', [])

    if not promoted_records:
        raise ValidationError("Audit log does not contain any promotion records to rollback.")

    reverted_count = 0
    for rec in promoted_records:
        student = StudentProfile.objects.filter(pk=rec['student_id']).first()
        if student:
            student.class_level_id = rec['prev_class_id']
            student.section_id = rec['prev_section_id']
            if 'prev_roll_number' in rec and rec['prev_roll_number']:
                student.roll_number = rec['prev_roll_number']
            student.save(update_fields=['class_level', 'section', 'roll_number', 'updated_at'])
            reverted_count += 1

    # Mark original audit as rolled back
    changes['rolled_back'] = True
    changes['rolled_back_by'] = user.username if user else 'System'
    audit.save(update_fields=['changes'])

    log_audit(
        user=user,
        action='ROLLBACK',
        instance=audit,
        changes={
            'rolled_back_promotion_audit_id': audit_log_id,
            'reverted_student_count': reverted_count
        },
        request=request
    )

    return {
        'reverted_count': reverted_count,
        'original_audit_id': audit_log_id
    }

