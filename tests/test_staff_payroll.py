import pytest
import datetime
from decimal import Decimal
from django.test import Client
from django.urls import reverse

from accounts.models import User, RoleChoices
from academics.models import School
from staff.models import (
    Staff, StaffAttendance, ShiftTiming, LeaveType, LeaveRequest,
    AttendanceStatusChoices, LeaveStatusChoices, LateDeductionPolicyChoices,
    SalarySlip, SalarySlipStatusChoices, SalaryPaymentMethodChoices
)
from staff.services.payroll_service import (
    calculate_staff_monthly_salary, generate_bulk_payroll,
    mark_salary_slip_paid, generate_payslip_pdf, generate_salary_slip_number
)


@pytest.fixture
def payroll_setup(db):
    school = School.objects.create(
        name="Lahore Grammar School",
        code="LGS-01",
        latitude=31.5204,
        longitude=74.3587,
        radius_meters=300
    )
    leave_type = LeaveType.objects.create(
        school=school,
        name="Casual Leave",
        days_per_year=3
    )
    admin_user = User.objects.create_user(
        username="payroll_admin",
        role=RoleChoices.ADMIN,
        school=school,
        password="AdminPassword123!"
    )
    accountant_user = User.objects.create_user(
        username="payroll_accountant",
        role=RoleChoices.ACCOUNTANT,
        school=school,
        password="AccPassword123!"
    )
    teacher_user1 = User.objects.create_user(
        username="teacher_tariq",
        first_name="Tariq",
        last_name="Mahmood",
        role=RoleChoices.TEACHER,
        school=school,
        password="TeacherPassword123!"
    )
    staff1 = Staff.objects.create(
        school=school,
        user=teacher_user1,
        employee_id="EMP-2026-001",
        designation="Senior Physics Lecturer",
        department="Sciences",
        phone="+923001234567",
        basic_salary=Decimal('60000.00'),
        allowances=Decimal('5000.00'),
        late_deduction_policy=LateDeductionPolicyChoices.EVERY_3_LATES_1_DAY,
        bank_name="Meezan Bank",
        bank_account_number="PK12MEZN0000123456"
    )

    teacher_user2 = User.objects.create_user(
        username="teacher_fatima",
        first_name="Fatima",
        last_name="Noor",
        role=RoleChoices.TEACHER,
        school=school,
        password="TeacherPassword123!"
    )
    staff2 = Staff.objects.create(
        school=school,
        user=teacher_user2,
        employee_id="EMP-2026-002",
        designation="Mathematics Teacher",
        department="Sciences",
        phone="+923007654321",
        basic_salary=Decimal('45000.00'),
        allowances=Decimal('3000.00'),
        late_deduction_policy=LateDeductionPolicyChoices.HALF_DAY_PER_2_LATES,
        bank_name="Habib Bank Ltd",
        bank_account_number="PK99HABB0000987654"
    )

    return {
        'school': school,
        'leave_type': leave_type,
        'admin_user': admin_user,
        'accountant_user': accountant_user,
        'teacher_user1': teacher_user1,
        'staff1': staff1,
        'teacher_user2': teacher_user2,
        'staff2': staff2,
    }


@pytest.mark.django_db
def test_absent_days_deduction(payroll_setup):
    """
    Staff with 60,000 basic salary in November (30 days) has a daily rate of 2,000.
    3 absent days should deduct 6,000 PKR.
    Gross = 60,000 + 5,000 = 65,000. Net = 59,000.
    """
    staff1 = payroll_setup['staff1']

    # Record 3 absent days in Nov 2026
    for day in range(1, 4):
        StaffAttendance.objects.create(
            school=staff1.school,
            staff=staff1,
            date=datetime.date(2026, 11, day),
            status=AttendanceStatusChoices.ABSENT
        )

    # 10 present days
    for day in range(4, 14):
        StaffAttendance.objects.create(
            school=staff1.school,
            staff=staff1,
            date=datetime.date(2026, 11, day),
            status=AttendanceStatusChoices.PRESENT
        )

    slip = calculate_staff_monthly_salary(staff=staff1, month=11, year=2026)

    assert slip.total_days == 30
    assert slip.absent_days == 3
    assert slip.absent_deduction == Decimal('6000.00')
    assert slip.gross_salary == Decimal('65000.00')
    assert slip.net_salary == Decimal('59000.00')
    assert slip.status == SalarySlipStatusChoices.GENERATED


@pytest.mark.django_db
def test_late_deduction_policies(payroll_setup):
    """
    Test 3 Lates = 1 Day Cut policy vs 2 Lates = Half Day Cut policy.
    Staff 1 (3_LATES_1_DAY, daily rate 2,000):
      7 lates -> 7 // 3 = 2 cut days = 4,000 PKR cut.
    Staff 2 (2_LATES_HALF_DAY, daily rate 1,500):
      5 lates -> 5 // 2 = 2 half-days = 1 full day = 1,500 PKR cut.
    """
    staff1 = payroll_setup['staff1']
    staff2 = payroll_setup['staff2']

    # Staff 1: 7 lates in Nov 2026
    for day in range(1, 8):
        StaffAttendance.objects.create(
            school=staff1.school,
            staff=staff1,
            date=datetime.date(2026, 11, day),
            status=AttendanceStatusChoices.LATE
        )

    slip1 = calculate_staff_monthly_salary(staff=staff1, month=11, year=2026)
    assert slip1.late_count == 7
    # 7 // 3 = 2 days * 2000 = 4000
    assert slip1.late_deduction == Decimal('4000.00')

    # Staff 2: 5 lates in Nov 2026
    for day in range(1, 6):
        StaffAttendance.objects.create(
            school=staff2.school,
            staff=staff2,
            date=datetime.date(2026, 11, day),
            status=AttendanceStatusChoices.LATE
        )

    slip2 = calculate_staff_monthly_salary(staff=staff2, month=11, year=2026)
    assert slip2.late_count == 5
    # daily rate = 45000 / 30 = 1500. 5 // 2 = 2 half-days = 1500 cut
    assert slip2.late_deduction == Decimal('1500.00')


@pytest.mark.django_db
def test_unpaid_leave_deduction_exceeding_quota(payroll_setup):
    """
    Annual leave quota is 3 days.
    Staff member takes 5 days approved leave in November 2026.
    2 days exceed allowed quota -> 2 unpaid days deducted.
    """
    staff1 = payroll_setup['staff1']
    leave_type = payroll_setup['leave_type']

    LeaveRequest.objects.create(
        school=staff1.school,
        staff=staff1,
        leave_type=leave_type,
        from_date=datetime.date(2026, 11, 10),
        to_date=datetime.date(2026, 11, 14),  # 5 days
        status=LeaveStatusChoices.APPROVED
    )

    slip = calculate_staff_monthly_salary(staff=staff1, month=11, year=2026)

    assert slip.unpaid_leave_days == 2
    # 2 days * 2000 = 4000
    assert slip.leave_deduction == Decimal('4000.00')
    assert slip.net_salary == Decimal('65000.00') - Decimal('4000.00')


@pytest.mark.django_db
def test_bulk_payroll_generation(payroll_setup):
    """
    Bulk generation runs for all active staff in the school.
    """
    school = payroll_setup['school']
    slips = generate_bulk_payroll(school=school, month=11, year=2026)

    assert len(slips) == 2
    for slip in slips:
        assert slip.slip_number.startswith("PAY-202611-")
        assert slip.month == 11
        assert slip.year == 2026
        assert slip.status == SalarySlipStatusChoices.GENERATED


@pytest.mark.django_db
def test_reportlab_payslip_pdf_generation(payroll_setup):
    """
    Tests that ReportLab generates a valid PDF with correct binary headers.
    """
    staff1 = payroll_setup['staff1']
    slip = calculate_staff_monthly_salary(staff=staff1, month=11, year=2026)

    pdf_bytes = generate_payslip_pdf(slip)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b'%PDF')
    assert len(pdf_bytes) > 1000


@pytest.mark.django_db
def test_salary_slip_mark_paid(payroll_setup):
    """
    Tests marking salary slip as PAID with audit log and reference.
    """
    staff1 = payroll_setup['staff1']
    accountant = payroll_setup['accountant_user']
    slip = calculate_staff_monthly_salary(staff=staff1, month=11, year=2026)

    paid_slip = mark_salary_slip_paid(
        slip=slip,
        payment_method=SalaryPaymentMethodChoices.BANK_TRANSFER,
        transaction_reference="HBL-TXN-987654",
        disbursed_by=accountant,
        remarks="Approved and disbursed via RTGS"
    )

    assert paid_slip.status == SalarySlipStatusChoices.PAID
    assert paid_slip.payment_date == datetime.date.today()
    assert paid_slip.transaction_reference == "HBL-TXN-987654"
    assert paid_slip.disbursed_by == accountant


@pytest.mark.django_db
def test_salary_slip_permission_isolation(payroll_setup):
    """
    Role & Object ownership security:
    - Teacher 1 CAN view their own slip (200).
    - Teacher 1 CANNOT view or download Teacher 2's slip (403).
    - Admin CAN view and generate payroll (200).
    """
    client = Client()
    staff1 = payroll_setup['staff1']
    staff2 = payroll_setup['staff2']
    teacher1_user = payroll_setup['teacher_user1']
    admin_user = payroll_setup['admin_user']

    slip1 = calculate_staff_monthly_salary(staff=staff1, month=11, year=2026)
    slip2 = calculate_staff_monthly_salary(staff=staff2, month=11, year=2026)

    # 1. Teacher 1 logged in
    client.force_login(teacher1_user)

    # Own slip -> 200
    res_own = client.get(reverse('salary_slip_detail', kwargs={'slip_id': slip1.id}))
    assert res_own.status_code == 200

    # Own PDF -> 200
    res_own_pdf = client.get(reverse('salary_slip_pdf', kwargs={'slip_id': slip1.id}))
    assert res_own_pdf.status_code == 200
    assert res_own_pdf['Content-Type'] == 'application/pdf'

    # Other teacher's slip -> 403 Forbidden
    res_other = client.get(reverse('salary_slip_detail', kwargs={'slip_id': slip2.id}))
    assert res_other.status_code == 403

    # Other teacher's PDF -> 403 Forbidden
    res_other_pdf = client.get(reverse('salary_slip_pdf', kwargs={'slip_id': slip2.id}))
    assert res_other_pdf.status_code == 403

    # Teacher cannot view payroll admin dashboard -> 403 Forbidden
    res_dash = client.get(reverse('staff_payroll_dashboard'))
    assert res_dash.status_code == 403

    # 2. Admin logged in
    client.force_login(admin_user)

    # Admin can view dashboard -> 200
    res_admin_dash = client.get(reverse('staff_payroll_dashboard'))
    assert res_admin_dash.status_code == 200

    # Admin can view any teacher's slip -> 200
    res_admin_slip2 = client.get(reverse('salary_slip_detail', kwargs={'slip_id': slip2.id}))
    assert res_admin_slip2.status_code == 200

