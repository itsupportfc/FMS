from django.db import transaction
from django.utils import timezone

from tms.models import Accessorial, Load, Truck
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

    # Auto-create TONU (optional; keep commented if you want same behavior)
    # Accessorial.objects.create(
    #     load=load,
    #     charge_type=Accessorial.ChargeType.TONU,
    #     amount=0.00,
    #     description=f"TONU charge - Load cancelled at {load.get_status_display()}",
    #     created_by=load.dispatcher,
    # )

    if load.truck:
        load.truck.current_status = Truck.TruckStatus.AVAILABLE
        load.truck.save(update_fields=["current_status"])
