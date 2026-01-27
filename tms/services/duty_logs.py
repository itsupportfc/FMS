# from turtle import up

# from django.core.exceptions import ValidationError
# from django.db import transaction

# from tms.models import DutyLog


# @transaction.atomic
# def create_duty_log(*, log: DutyLog):
#     """
#     Centralized duty log creation logic.
#     """
#     previous = (
#         DutyLog.objects.filter(driver=log.driver, end_time__isnull=True)
#         .order_by("-start_time")
#         .first()
#     )

#     if previous:
#         if previous.start_time >= log.start_time:
#             raise ValidationError(
#                 "New duty log start time must be after the previous log's start time."
#             )
#         # Close the previous log
#         previous.end_time = log.start_time
#         previous.save(update_fields=["end_time"])

#     # enforce team-driver driving exclusivity
#     if log.status == DutyLog.DutyStatus.DRIVING and log.truck:
#         overlapping = DutyLog.objects.filter(
#             truck=log.truck, status=DutyLog.DutyStatus.DRIVING, end_time__isnull=True
#         ).exclude(driver=log.driver)

#         if overlapping.exists():
#             raise ValidationError(
#                 "Another driver is already logged as driving this truck."
#             )

#     # Save the new log
#     log.full_clean()
#     log.save() 

#     return log
