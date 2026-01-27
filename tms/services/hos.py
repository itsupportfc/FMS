# from datetime import timedelta
# from itertools import cycle

# from django.utils import timezone

# from tms.models import DutyLog


# class HOSCalculator:
#     """Hours of Service (HOS) calculation utilities."""

#     DRIVING_LIMIT = timedelta(hours=11)
#     DUTY_LIMIT = timedelta(hours=14)
#     BREAK_REQUIRED_AFTER = timedelta(hours=8)
#     BREAK_DURATION = timedelta(minutes=30)

#     def __init__(self, driver):
#         self.driver = driver
#         self.now = timezone.now()

#     def _logs_since(self, since_time):
#         return DutyLog.objects.filter(
#             driver=self.driver, start_time__gte=since_time, end_time__isnull=False
#         )

#     def driving_today(self):
#         """Calculate total driving time for the current day."""
#         start = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
#         logs = self._logs_since(start).filter(status=DutyLog.DutyStatus.DRIVING)
#         return sum((l.duration for l in logs if l.duration), timedelta())

#     def cycle_on_duty(self):
#         """Calculate total on-duty time for the current HOS cycle."""
#         days = 8 if self.driver.hos_cycle == "70_8" else 7
#         start = self.now - timedelta(days=days)

#         logs = self._logs_since(start).filter(
#             status__in=[
#                 DutyLog.DutyStatus.DRIVING,
#                 DutyLog.DutyStatus.ON_DUTY_NOT_DRIVING,
#             ]
#         )
#         return sum((l.duration for l in logs if l.duration), timedelta())

#     def last_break_end(self):
#         """Get the end time of the last qualifying break."""
#         logs = DutyLog.objects.filter(
#             driver=self.driver,
#             status__in=[
#                 DutyLog.DutyStatus.OFF_DUTY,
#                 DutyLog.DutyStatus.SLEEPER_BERTH,
#             ],
#             end_time__isnull=False,
#         ).order_by("-end_time")

#         for log in logs:
#             if log.duration and log.duration >= self.BREAK_DURATION:
#                 return log.end_time

#         return None

#     def summary(self):
#         driving = self.driving_today()
#         cycle_used = self.cycle_on_duty()
#         cycle_limit = (
#             timedelta(hours=70)
#             if self.driver.hos_cycle == "70_8"
#             else timedelta(hours=60)
#         )

#         last_break = self.last_break_end()

#         # Only require break if driver has actually driven
#         # If no driving time, no break required
#         break_required = False
#         if driving > timedelta():
#             # Driver has driven, check if break is needed
#             if not last_break:
#                 # No break taken yet, check if 8 hours passed since first drive
#                 break_required = driving >= self.BREAK_REQUIRED_AFTER
#             else:
#                 # Break was taken, check if 8 hours passed since last break
#                 break_required = self.now - last_break >= self.BREAK_REQUIRED_AFTER

#         warnings = []
#         if driving >= timedelta(hours=9):
#             warnings.append("Approaching 11-hour driving limit.")
#         if cycle_used >= cycle_limit - timedelta(hours=10):
#             warnings.append("Approaching cycle limit.")
#         if break_required:
#             warnings.append("30-minute break required.")

#         return {
#             "driving_today": driving,
#             "driving_remaining": max(self.DRIVING_LIMIT - driving, timedelta()),
#             "cycle_remaining": max(cycle_limit - cycle_used, timedelta()),
#             "break_required": break_required,
#             "warnings": warnings,
#         }
