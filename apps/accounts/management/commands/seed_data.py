import datetime
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User, RoleChoices, Notice, NoticeTargetChoices
from academics.models import School, AcademicYear, ClassLevel, Section, Subject, ClassSubjectAssignment
from students.models import StudentProfile, GuardianProfile, StudentStatusChoices
from staff.models import Staff, ShiftTiming, LeaveType, EmploymentTypeChoices, StaffStatusChoices
from fees.models import FeeCategory, FeeStructure, Challan, ChallanStatusChoices, Payment, PaymentMethod


class Command(BaseCommand):
    help = 'Seeds initial demo data including school, classes, demo users, staff profiles, challans, and notices.'

    def handle(self, *args, **options):
        # Security Guard: Only run in DEBUG mode
        if not settings.DEBUG:
            raise CommandError("Security Guard: seed_data can only be executed when DEBUG=True.")

        self.stdout.write(self.style.SUCCESS('Starting secure SMS demo data seeding...'))

        with transaction.atomic():
            # 1. School Root
            school, _ = School.objects.get_or_create(
                code='APEX-01',
                defaults={
                    'name': 'E-Planet Educational Portal',
                    'address': 'Building 42, Education Boulevard, Sector H-9, Islamabad',
                    'phone': '+92 (51) 111-273-900',
                    'email': 'info@eplanet.edu.pk',
                    'website': 'https://eplanet.edu.pk',
                    'latitude': 33.6844,
                    'longitude': 73.0479,
                    'radius_meters': 500
                }
            )

            # 2. Academic Year
            academic_year, _ = AcademicYear.objects.get_or_create(
                school=school,
                name='2026-2027',
                defaults={
                    'start_date': datetime.date(2026, 8, 1),
                    'end_date': datetime.date(2027, 6, 30),
                    'is_current': True
                }
            )

            # 3. Super Admin & Principal
            super_admin, _ = User.objects.get_or_create(
                username='admin',
                defaults={
                    'email': 'admin@eplanet.edu',
                    'first_name': 'System',
                    'last_name': 'Administrator',
                    'role': RoleChoices.SUPER_ADMIN,
                    'school': school,
                    'is_staff': True,
                    'is_superuser': True
                }
            )
            super_admin.set_password('AdminSecure2026!')
            super_admin.save()

            principal, _ = User.objects.get_or_create(
                username='principal',
                defaults={
                    'email': 'principal@eplanet.edu',
                    'first_name': 'Dr. Robert',
                    'last_name': 'Vance',
                    'role': RoleChoices.ADMIN,
                    'school': school,
                    'is_staff': True
                }
            )
            principal.set_password('PrincipalSecure2026!')
            principal.save()

            # 4. Shifts and Leave Types for Staff
            shift, _ = ShiftTiming.objects.get_or_create(
                school=school,
                name='Standard Morning Faculty Shift',
                defaults={
                    'start_time': datetime.time(8, 0),
                    'end_time': datetime.time(14, 0),
                    'grace_minutes': 15
                }
            )
            leave_type_casual, _ = LeaveType.objects.get_or_create(
                school=school,
                name='Casual Leave',
                defaults={'days_per_year': 12}
            )
            leave_type_sick, _ = LeaveType.objects.get_or_create(
                school=school,
                name='Medical / Sick Leave',
                defaults={'days_per_year': 10}
            )

            # 5. Faculty Staff
            teacher_math_user, _ = User.objects.get_or_create(
                username='teacher_math',
                defaults={
                    'email': 'math@eplanet.edu',
                    'first_name': 'Alan',
                    'last_name': 'Turing',
                    'role': RoleChoices.TEACHER,
                    'school': school,
                    'phone_number': '+923001112233'
                }
            )
            teacher_math_user.set_password('TeacherSecure2026!')
            teacher_math_user.save()

            staff_math, _ = Staff.objects.get_or_create(
                user=teacher_math_user,
                defaults={
                    'school': school,
                    'employee_id': 'EMP-2026-0001',
                    'designation': 'Senior Mathematics Teacher',
                    'department': 'Mathematics',
                    'qualification': 'M.Phil Pure Mathematics',
                    'phone': '+923001112233',
                    'cnic': '35202-1111111-1',
                    'shift': shift,
                    'employment_type': EmploymentTypeChoices.PERMANENT,
                    'status': StaffStatusChoices.ACTIVE
                }
            )

            teacher_sci_user, _ = User.objects.get_or_create(
                username='teacher_science',
                defaults={
                    'email': 'science@eplanet.edu',
                    'first_name': 'Marie',
                    'last_name': 'Curie',
                    'role': RoleChoices.TEACHER,
                    'school': school,
                    'phone_number': '+923004445566'
                }
            )
            teacher_sci_user.set_password('TeacherSecure2026!')
            teacher_sci_user.save()

            staff_sci, _ = Staff.objects.get_or_create(
                user=teacher_sci_user,
                defaults={
                    'school': school,
                    'employee_id': 'EMP-2026-0002',
                    'designation': 'Senior Physics Lecturer',
                    'department': 'Sciences',
                    'qualification': 'Ph.D Physics',
                    'phone': '+923004445566',
                    'cnic': '35202-2222222-2',
                    'shift': shift,
                    'employment_type': EmploymentTypeChoices.PERMANENT,
                    'status': StaffStatusChoices.ACTIVE
                }
            )

            # 6. Accountant
            accountant_user, _ = User.objects.get_or_create(
                username='accountant',
                defaults={
                    'email': 'finance@eplanet.edu',
                    'first_name': 'Charles',
                    'last_name': 'Schwab',
                    'role': RoleChoices.ACCOUNTANT,
                    'school': school,
                    'phone_number': '+923007778899'
                }
            )
            accountant_user.set_password('AccountantSecure2026!')
            accountant_user.save()

            # 7. Classes & Sections with Capacity
            classes_config = [
                ('Grade 8', 'G8', 8),
                ('Grade 9', 'G9', 9),
                ('Grade 10', 'G10', 10),
            ]
            for name, code, order in classes_config:
                cls_obj, _ = ClassLevel.objects.get_or_create(
                    school=school,
                    code=code,
                    defaults={'name': name, 'numeric_order': order}
                )

                sec_a, _ = Section.objects.get_or_create(
                    class_level=cls_obj,
                    name='Section A',
                    defaults={'room_number': f'Room 10{order}', 'capacity': 35}
                )

                # Subject & Assignments
                math_sub, _ = Subject.objects.get_or_create(
                    class_level=cls_obj,
                    code=f'MATH-{code}',
                    defaults={'name': 'Mathematics', 'credit_hours': 4, 'school': school}
                )
                ClassSubjectAssignment.objects.get_or_create(
                    class_level=cls_obj,
                    section=sec_a,
                    subject=math_sub,
                    defaults={'teacher': teacher_math_user, 'periods_per_week': 6}
                )

            # 8. Parent User & Guardian
            parent_user, _ = User.objects.get_or_create(
                username='parent_smith',
                defaults={
                    'email': 'smith.family@eplanet.edu',
                    'first_name': 'John',
                    'last_name': 'Smith Sr.',
                    'role': RoleChoices.PARENT,
                    'school': school,
                    'phone_number': '+923219876543',
                    'must_change_password': True
                }
            )
            parent_user.set_password('ParentSecure2026!')
            parent_user.save()

            guardian_profile, _ = GuardianProfile.objects.get_or_create(
                cnic='42101-1234567-1',
                defaults={
                    'school': school,
                    'user': parent_user,
                    'first_name': 'John',
                    'last_name': 'Smith Sr.',
                    'relation': 'Father',
                    'occupation': 'Senior Architect',
                    'phone': '+923219876543',
                    'email': 'smith.family@eplanet.edu',
                    'address': 'House 14, Street 9, F-8/3, Islamabad'
                }
            )

            # 9. Student
            g10_obj = ClassLevel.objects.get(school=school, code='G10')
            g10_sec = Section.objects.get(class_level=g10_obj, name='Section A')

            student_user, _ = User.objects.get_or_create(
                username='student_john',
                defaults={
                    'email': 'john.jr@eplanet.edu',
                    'first_name': 'John',
                    'last_name': 'Smith Jr.',
                    'role': RoleChoices.STUDENT,
                    'school': school,
                    'cnic_bform': '42101-7654321-1',
                    'must_change_password': True
                }
            )
            student_user.set_password('StudentSecure2026!')
            student_user.save()

            student, _ = StudentProfile.objects.get_or_create(
                user=student_user,
                defaults={
                    'school': school,
                    'admission_number': 'ADM-2026-0001',
                    'roll_number': 'C10A-01',
                    'class_level': g10_obj,
                    'section': g10_sec,
                    'guardian': guardian_profile,
                    'dob': datetime.date(2010, 5, 14),
                    'gender': 'MALE',
                    'bform_number': '42101-7654321-1',
                    'religion': 'Islam',
                    'blood_group': 'O+',
                    'emergency_contact': '+923219876543',
                    'address': 'House 14, Street 9, F-8/3, Islamabad',
                    'status': StudentStatusChoices.ACTIVE
                }
            )

            # 10. Fee Category, Structure & Virtual Challan
            fee_cat, _ = FeeCategory.objects.get_or_create(
                school=school,
                name='Monthly Tuition Fee'
            )
            FeeStructure.objects.get_or_create(
                school=school,
                class_level=g10_obj,
                academic_year=academic_year,
                category=fee_cat,
                defaults={'amount': 12000.00}
            )
            from decimal import Decimal
            challan, _ = Challan.objects.get_or_create(
                challan_no='CHL-2026-0001',
                defaults={
                    'school': school,
                    'student': student,
                    'academic_year': academic_year,
                    'month': 'August',
                    'year': 2026,
                    'due_date': datetime.date.today() + datetime.timedelta(days=10),
                    'total': Decimal('12000.00'),
                    'status': ChallanStatusChoices.PAID
                }
            )
            Payment.objects.get_or_create(
                reference_no='VIR-202603-0001',
                defaults={
                    'school': school,
                    'challan': challan,
                    'amount': Decimal('12000.00'),
                    'method': PaymentMethod.VIRTUAL,
                    'received_by': accountant_user,
                    'is_virtual': True,
                    'notes': 'Seeded virtual demonstration payment'
                }
            )

            # 11. School Notices
            Notice.objects.get_or_create(
                school=school,
                title='Annual Sports Gala & Athletics Championship 2026',
                defaults={
                    'content': 'We are pleased to announce the Annual Inter-House Sports Gala starting next week.',
                    'target_role': NoticeTargetChoices.ALL,
                    'created_by': super_admin
                }
            )
            Notice.objects.get_or_create(
                school=school,
                title='Mid-Term Academic Progress Reports',
                defaults={
                    'content': 'Parent-Teacher conference and report card distribution scheduled for Saturday.',
                    'target_role': NoticeTargetChoices.PARENT,
                    'created_by': super_admin
                }
            )

        self.stdout.write(self.style.SUCCESS('Successfully seeded complete SMS demo data!'))
