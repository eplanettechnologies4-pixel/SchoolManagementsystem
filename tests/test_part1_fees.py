import datetime
import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import Client

from accounts.models import User, RoleChoices
from academics.models import School, AcademicYear, ClassLevel, Section
from students.models import StudentProfile, GuardianProfile
from fees.models import (
    FeeCategory, FeeStructure, Challan, Payment,
    ChallanStatusChoices, PaymentMethod
)
from fees.services.payment_gateway import VirtualGateway
from fees.services.fee_service import generate_challan_number, generate_challan_pdf, get_accountant_dashboard_metrics


@pytest.fixture
def setup_fee_data(db):
    school = School.objects.create(name='Test Apex School', code='TEST-01', address='Addr', phone='123', email='s@test.com')
    acad_year = AcademicYear.objects.create(school=school, name='2026-2027', start_date=datetime.date(2026, 8, 1), end_date=datetime.date(2027, 6, 30), is_current=True)
    class_10 = ClassLevel.objects.create(school=school, name='Grade 10', code='G10', numeric_order=10)
    section_a = Section.objects.create(class_level=class_10, name='Section A', capacity=30)

    # Users
    accountant = User.objects.create_user(username='acc_test', password='Password123!', role=RoleChoices.ACCOUNTANT, school=school)
    student_user = User.objects.create_user(username='stu_test', password='Password123!', role=RoleChoices.STUDENT, school=school)
    student_user_other = User.objects.create_user(username='stu_other', password='Password123!', role=RoleChoices.STUDENT, school=school)
    parent_user = User.objects.create_user(username='par_test', password='Password123!', role=RoleChoices.PARENT, school=school)

    guardian = GuardianProfile.objects.create(user=parent_user, first_name='Father', last_name='Smith', relation='Father', phone='03001234567')
    student = StudentProfile.objects.create(
        user=student_user,
        admission_number='ADM-2026-9001',
        roll_number='G10A-01',
        class_level=class_10,
        section=section_a,
        guardian=guardian
    )
    student_other = StudentProfile.objects.create(
        user=student_user_other,
        admission_number='ADM-2026-9002',
        roll_number='G10A-02',
        class_level=class_10,
        section=section_a
    )

    return {
        'school': school,
        'acad_year': acad_year,
        'class_10': class_10,
        'section_a': section_a,
        'accountant': accountant,
        'student_user': student_user,
        'student_user_other': student_user_other,
        'parent_user': parent_user,
        'student': student,
        'student_other': student_other,
    }


@pytest.mark.django_db
def test_challan_generation_and_uniqueness(setup_fee_data):
    data = setup_fee_data
    chl_no_1 = generate_challan_number(2026)
    chl_1 = Challan.objects.create(
        school=data['school'],
        student=data['student'],
        academic_year=data['acad_year'],
        month='August',
        year=2026,
        total=Decimal('5000.00'),
        due_date=datetime.date(2026, 8, 25),
        challan_no=chl_no_1
    )
    assert chl_1.challan_no.startswith('CHL-2026-')
    assert chl_1.status == ChallanStatusChoices.UNPAID

    chl_no_2 = generate_challan_number(2026)
    assert chl_no_2 != chl_no_1


@pytest.mark.django_db
def test_virtual_gateway_payment_and_immutability(setup_fee_data):
    data = setup_fee_data
    challan = Challan.objects.create(
        school=data['school'],
        student=data['student'],
        month='September',
        year=2026,
        total=Decimal('6000.00'),
        due_date=datetime.date(2026, 9, 25),
        challan_no=generate_challan_number(2026)
    )

    gateway = VirtualGateway()
    # Process partial virtual payment
    payment = gateway.process_payment(challan=challan, amount=Decimal('2000.00'), received_by=data['accountant'])
    assert payment.is_virtual is True
    assert payment.method == PaymentMethod.VIRTUAL
    assert payment.reference_no.startswith('VIR-')

    challan.refresh_from_db()
    assert challan.paid_amount == Decimal('2000.00')
    assert challan.remaining_balance == Decimal('4000.00')
    assert challan.status == ChallanStatusChoices.PARTIAL

    # Process remaining payment
    payment2 = gateway.process_payment(challan=challan, amount=Decimal('4000.00'), received_by=data['accountant'])
    challan.refresh_from_db()
    assert challan.paid_amount == Decimal('6000.00')
    assert challan.remaining_balance == Decimal('0.00')
    assert challan.status == ChallanStatusChoices.PAID

    # Test Payment Immutability (no edit allowed)
    with pytest.raises(ValidationError):
        payment.amount = Decimal('9999.00')
        payment.save()

    # Test Payment Immutability (no delete allowed)
    with pytest.raises(ValidationError):
        payment.delete()


@pytest.mark.django_db
def test_payment_reversal(setup_fee_data):
    data = setup_fee_data
    challan = Challan.objects.create(
        school=data['school'],
        student=data['student'],
        month='October',
        year=2026,
        total=Decimal('5000.00'),
        due_date=datetime.date(2026, 10, 25),
        challan_no=generate_challan_number(2026)
    )

    gateway = VirtualGateway()
    payment = gateway.process_payment(challan=challan, amount=Decimal('5000.00'), received_by=data['accountant'])
    challan.refresh_from_db()
    assert challan.status == ChallanStatusChoices.PAID

    # Reverse payment
    reversal = gateway.reverse_payment(payment=payment, reason="Incorrect bank slip recorded", user=data['accountant'])
    assert reversal.is_reversal is True
    assert reversal.amount == Decimal('-5000.00')

    challan.refresh_from_db()
    assert challan.paid_amount == Decimal('0.00')
    assert challan.remaining_balance == Decimal('5000.00')
    assert challan.status == ChallanStatusChoices.UNPAID


@pytest.mark.django_db
def test_challan_pdf_generation_with_qr(setup_fee_data):
    data = setup_fee_data
    challan = Challan.objects.create(
        school=data['school'],
        student=data['student'],
        month='November',
        year=2026,
        total=Decimal('4500.00'),
        due_date=datetime.date(2026, 11, 20),
        challan_no=generate_challan_number(2026)
    )

    pdf_bytes = generate_challan_pdf(challan)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert b'%PDF' in pdf_bytes


@pytest.mark.django_db
def test_rbac_object_level_permissions(setup_fee_data):
    data = setup_fee_data
    challan_student1 = Challan.objects.create(
        school=data['school'],
        student=data['student'],
        month='November',
        year=2026,
        total=Decimal('3000.00'),
        due_date=datetime.date(2026, 11, 20),
        challan_no=generate_challan_number(2026)
    )

    c = Client()

    # 1. Student 1 views own challan -> OK (200)
    c.force_login(data['student_user'])
    resp = c.get(f'/fees/challans/{challan_student1.id}/')
    assert resp.status_code == 200

    # 2. Student 2 tries to view Student 1's challan -> 403 Forbidden
    c.force_login(data['student_user_other'])
    resp = c.get(f'/fees/challans/{challan_student1.id}/')
    assert resp.status_code == 403

    # 3. Parent views ward's challan -> OK (200)
    c.force_login(data['parent_user'])
    resp = c.get(f'/fees/challans/{challan_student1.id}/')
    assert resp.status_code == 200

    # 4. Student tries to trigger virtual payment -> 403 Forbidden
    c.force_login(data['student_user'])
    resp = c.post(f'/fees/challans/{challan_student1.id}/pay-virtual/', {'amount': '1000.00'})
    assert resp.status_code == 403

    # 5. Accountant triggers virtual payment -> Redirects (302) with success
    c.force_login(data['accountant'])
    resp = c.post(f'/fees/challans/{challan_student1.id}/pay-virtual/', {'amount': '1000.00'})
    assert resp.status_code == 302
    challan_student1.refresh_from_db()
    assert challan_student1.paid_amount == Decimal('1000.00')

