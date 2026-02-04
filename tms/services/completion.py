from django.db import transaction
from django.utils import timezone

from tms.models import Load
from tms.services.exceptions import ServiceError


@transaction.atomic
def complete_load(load: Load) -> None:
    """
    Transition: DELIVERED → COMPLETED

    WHY: Marks load as fully completed and closed.
    This indicates all tracking, paperwork, and billing are done.

    NOTE: Carrier payment can still be pending.
    """
    if load.status != Load.Status.DELIVERED:
        raise ServiceError("Load is not in DELIVERED status.")

    load.status = Load.Status.COMPLETED
    load.completed_at = timezone.now()
    load.save(update_fields=["status", "completed_at", "updated_at"])
