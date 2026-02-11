from django.db import transaction
from django.utils import timezone

from tms.models import Accessorial, Driver, Load, Truck
from tms.services.exceptions import ServiceError


@transaction.atomic
def cancel_load(load: Load, reason: str = "") -> None:
    """
    Transition: (ANY except COMPLETED) → CANCELLED

    WHY: Loads can be cancelled at any stage before completion.

    Side Effects:
    - Sets cancelled_at timestamp
    - Optionally auto-creates TONU accessorial (currently disabled)
    - Frees truck status
    """
    if load.status in [
        Load.Status.CANCELLED,
        Load.Status.COMPLETED,
        Load.Status.DELIVERED,
    ]:
        raise ServiceError("Load is already CANCELLED, DELIVERED or COMPLETED.")

    load.status = Load.Status.CANCELLED
    load.cancelled_at = timezone.now()
    load.save(update_fields=["status", "cancelled_at", "updated_at"])


    if load.truck:
        load.truck.current_status = Truck.TruckStatus.AVAILABLE
        load.truck.save(update_fields=["current_status"])
        if load.driver:
            load.driver.current_status = Driver.DriverStatus.AVAILABLE
            load.driver.save(update_fields=["current_status"])
