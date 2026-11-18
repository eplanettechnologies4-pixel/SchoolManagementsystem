import pytest
import datetime
from django.utils import timezone
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounts.models import User, RoleChoices
from academics.models import School
from staff.models import (
    Staff, StaffAttendance, ShiftTiming, LeaveType,
    LeaveRequest, AttendanceStatusChoices, LeaveStatusChoices
)
from staff.services.attendance_service import (
    haversine_distance_meters, generate_employee_id_atomic,
    record_staff_check_in, record_staff_check_out
)
from staff.services.payroll_hooks import get_monthly_staff_attendance_summary


@pytest.fixture
def staff_setup(db):
    school = School.objects.create(
        name="Islamabad Model College",
        code="IMC-01",
        latitude=33.6844,
        longitude=73.0479,
        radius_meters=300
    )
    shift = ShiftTiming.objects.create(
        school=school,
        name="Morning Faculty Shift",
        start_time=datetime.time(8, 0),
        end_time=datetime.time(14, 0),
        grace_minutes=15
    )
    leave_type = LeaveType.objects.create(
        school=school,
        name="Casual Leave",
        days_per_year=12
    )

    admin_user = User.objects.create_user(
        username="admin_imc",
        role=RoleChoices.ADMIN,
        school=school,
        password="AdminPassword123!"
    )

    teacher_user = User.objects.create_user(
        username="teacher_asim",
        first_name="Asim",
        last_name="Raza",
        role=RoleChoices.TEACHER,
        school=school,
        password="TeacherPassword123!"
    )
    staff = Staff.objects.create(
        school=school,
        user=teacher_user,
        employee_id="EMP-2026-0001",
        designation="Senior Physics Teacher",
        department="Sciences",
        phone="+923001234567",
        cnic="35202-1234567-1",
        shift=shift
    )

    return {
        'school': school,
        'shift': shift,
        'leave_type': leave_type,
        'admin_user': admin_user,
        'teacher_user': teacher_user,
        'staff': staff
    }


@pytest.mark.django_db
def test_employee_id_atomic_generation(staff_setup):
    school = staff_setup['school']
    id1 = generate_employee_id_atomic(school=school, year=2026)
    # Since EMP-2026-0001 already exists in fixture:
    assert id1 == "EMP-2026-0002"


@pytest.mark.django_db
def test_haversine_distance_and_geofence(staff_setup):
    school = staff_setup['school']
    staff = staff_setup['staff']

    # Point very close (10 meters away)
    dist_near = haversine_distance_meters(school.latitude, school.longitude, 33.68445, 73.04795)
    assert dist_near < 50

    # Point far away (e.g. 5km away in Rawalpindi)
    dist_far = haversine_distance_meters(school.latitude, school.longitude, 33.6000, 73.0500)
    assert dist_far > 5000

    # Check-in within range
    att1, created1, out_of_range1 = record_staff_check_in(
        staff,
        lat=33.68445,
        lng=73.04795,
        now_dt=timezone.make_aware(datetime.datetime.combine(datetime.date.today(), datetime.time(8, 5)))
    )
    assert out_of_range1 is False
    assert att1.status == AttendanceStatusChoices.PRESENT
    assert att1.is_out_of_range is False


@pytest.mark.django_db
def test_late_arrival_detection(staff_setup):
    school = staff_setup['school']
    staff = staff_setup['staff']

    # Shift starts at 08:00 with 15 mins grace. Check in at 08:25 -> Should be LATE
    late_time = timezone.make_aware(datetime.datetime.combine(datetime.date.today(), datetime.time(8, 25)))
    att, created, out_of_range = record_staff_check_in(staff, lat=33.6844, lng=73.0479, now_dt=late_time)

    assert att.status == AttendanceStatusChoices.LATE


@pytest.mark.django_db
def test_check_out_and_payroll_summary(staff_setup):
    staff = staff_setup['staff']
    today = datetime.date.today()

    # Check-in at 8:10
    record_staff_check_in(
        staff,
        lat=33.6844,
        lng=73.0479,
        now_dt=timezone.make_aware(datetime.datetime.combine(today, datetime.time(8, 10)))
    )
    # Check-out at 14:05
    att = record_staff_check_out(
        staff,
        now_dt=timezone.make_aware(datetime.datetime.combine(today, datetime.time(14, 5)))
    )

    assert att.check_out is not None
    assert att.check_out == datetime.time(14, 5)

    # Payroll hook summary
    summary = get_monthly_staff_attendance_summary(staff, today.month, today.year)
    assert summary['present_days'] == 1
    assert summary['payable_effective_days'] == 1


@pytest.mark.django_db
def test_mark_absent_management_command(staff_setup):
    school = staff_setup['school']
    staff = staff_setup['staff']
    today = datetime.date.today()

    # Verify no attendance marked yet today
    StaffAttendance.objects.filter(staff=staff, date=today).delete()

    # Run management command
    call_command('mark_absent_staff', date=today.strftime('%Y-%m-%d'))

    # Verify staff auto-marked ABSENT
    att = StaffAttendance.objects.filter(staff=staff, date=today).first()
    assert att is not None
    assert att.status == AttendanceStatusChoices.ABSENT


@pytest.mark.django_db
def test_leave_workflow_and_balance(staff_setup):
    staff = staff_setup['staff']
    leave_type = staff_setup['leave_type']
    admin_user = staff_setup['admin_user']
    teacher_user = staff_setup['teacher_user']

    # 1. Staff applies for leave
    client = Client()
    client.force_login(teacher_user)
    apply_url = reverse('staff_leave_apply')
    res = client.post(apply_url, {
        'leave_type': leave_type.id,
        'from_date': (datetime.date.today() + datetime.timedelta(days=2)).strftime('%Y-%m-%d'),
        'to_date': (datetime.date.today() + datetime.timedelta(days=4)).strftime('%Y-%m-%d'),
        'reason': 'Family wedding event in Lahore'
    })
    assert res.status_code == 302

    leave_req = LeaveRequest.objects.filter(staff=staff).first()
    assert leave_req is not None
    assert leave_req.status == LeaveStatusChoices.PENDING
    assert leave_req.total_days == 3

    # 2. Admin reviews and approves leave
    client.force_login(admin_user)
    review_url = reverse('staff_leave_review', args=[leave_req.id])
    res2 = client.post(review_url, {
        'status': 'APPROVED',
        'review_comments': 'Approved by administration.'
    })
    assert res2.status_code == 302

    leave_req.refresh_from_db()
    assert leave_req.status == LeaveStatusChoices.APPROVED
    assert leave_req.approved_by == admin_user

