from django.db import transaction
from django.utils import timezone

from tms.models import Handover, Load
from tms.services.exceptions import ServiceError


def handover_to_tracking(load: Load, tracking_agent, from_agent, instructions=""):
    # VALIDATION: Collect all errors before raising
    errors = []

    # Status check
    if load.status != Load.Status.BOOKED:
        errors.append("Load must be in BOOKED status.")

    # Rate Confirmation required
    if not load.has_rate_confirmation():
        errors.append("Rate Confirmation document is required.")

    # Assignment checks
    if not load.carrier or not load.truck or not load.driver:
        errors.append("Carrier, Truck, and Driver must be assigned.")

    # Stops validation
    if not load.stops.exists():
        errors.append("At least 2 stops must be defined.")

    # APPT stops must have appointment windows
    if load.stops.exists():
        for stop in load.stops.all():
            if stop.appointment_type == "appt" and not (
                stop.appt_start or stop.appt_end
            ):
                errors.append(
                    f"Stop {stop.sequence} (APPT) requires appointment window."
                )
                break  # Only report first invalid stop

    # Raise all errors at once
    if errors:
        raise ServiceError("Cannot handover load: " + "; ".join(errors))

    # ALL VALIDATIONS PASSED - Execute handover
    with transaction.atomic():
        # Update load status and fields
        load.status = Load.Status.DISPATCHED
        load.tracking_agent = tracking_agent
        load.dispatched_at = timezone.now()
        load.save(
            update_fields=["status", "tracking_agent", "dispatched_at", "updated_at"]
        )

        # Create handover audit record
        Handover.objects.create(
            load=load,
            from_agent=from_agent,
            to_agent=tracking_agent,
            special_instructions=instructions,
        )
