import datetime
from staff.models import Staff, StaffAttendance, AttendanceStatusChoices


def get_monthly_staff_attendance_summary(staff: Staff, month: int, year: int) -> dict:
    """
    Payroll Hook: Aggregates attendance metrics for monthly payroll preparation.
    Does not calculate monetary payroll amounts now.
    """
    start_date = datetime.date(year, month, 1)
    if month == 12:
        end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    atts = StaffAttendance.objects.filter(
        staff=staff,
        date__gte=start_date,
        date__lte=end_date
    )

    present_count = atts.filter(status=AttendanceStatusChoices.PRESENT).count()
    late_count = atts.filter(status=AttendanceStatusChoices.LATE).count()
    leave_count = atts.filter(status=AttendanceStatusChoices.LEAVE).count()
    half_day_count = atts.filter(status=AttendanceStatusChoices.HALF_DAY).count()
    absent_count = atts.filter(status=AttendanceStatusChoices.ABSENT).count()

    return {
        'staff_id': staff.id,
        'employee_id': staff.employee_id,
        'full_name': staff.get_full_name(),
        'month': month,
        'year': year,
        'total_calendar_days': end_date.day,
        'present_days': present_count,
        'late_days': late_count,
        'leave_days': leave_count,
        'half_days': half_day_count,
        'absent_days': absent_count,
        'payable_effective_days': present_count + late_count + (0.5 * half_day_count),
    }

