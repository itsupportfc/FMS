from django.db import transaction

from tms.models import Load
from tms.services.exceptions import ServiceError


def start_transit(load: Load):
    """
    Transition: DISPATCHED → IN_TRANSIT

    V1 minimal service. No timestamp updates, no tracking agent checks.
    """
    if load.status != Load.Status.DISPATCHED:
        raise ServiceError("Load must be in DISPATCHED status.")

    if not load.has_rate_confirmation():
        raise ServiceError("Rate Confirmation document is required.")

    with transaction.atomic():
        load.status = Load.Status.IN_TRANSIT
        load.save(update_fields=["status", "updated_at"])
