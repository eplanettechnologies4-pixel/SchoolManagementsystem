import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from staff.models import Staff, StaffAttendance, AttendanceStatusChoices, AttendanceMethodChoices, LeaveRequest, LeaveStatusChoices


class Command(BaseCommand):
    help = "Auto-marks active staff without check-in as Absent at the end of the day."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD), default is today')

    def handle(self, *args, **options):
        date_str = options.get('date')
        if date_str:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = timezone.localtime(timezone.now()).date()

        self.stdout.write(f"Processing staff attendance closure for: {target_date}")

        active_staff = Staff.objects.filter(status='ACTIVE', is_deleted=False)
        marked_count = 0
        leave_count = 0

        for staff in active_staff:
            att = StaffAttendance.objects.filter(staff=staff, date=target_date).first()
            if not att:
                # Check if staff has an approved leave for this date
                on_leave = LeaveRequest.objects.filter(
                    staff=staff,
                    status=LeaveStatusChoices.APPROVED,
                    from_date__lte=target_date,
                    to_date__gte=target_date,
                    is_deleted=False
                ).exists()

                status = AttendanceStatusChoices.LEAVE if on_leave else AttendanceStatusChoices.ABSENT
                StaffAttendance.objects.create(
                    school=staff.school,
                    staff=staff,
                    date=target_date,
                    status=status,
                    method=AttendanceMethodChoices.MANUAL,
                    notes="Auto-marked by end-of-day scheduler"
                )
                if on_leave:
                    leave_count += 1
                else:
                    marked_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Successfully marked {marked_count} staff as ABSENT, {leave_count} as ON LEAVE for {target_date}."
        ))

