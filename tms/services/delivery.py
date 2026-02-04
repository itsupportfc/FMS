from django.db import transaction
from django.utils import timezone

from tms.models import Load, LoadDocument, LoadStop
from tms.services.exceptions import ServiceError


@transaction.atomic
def mark_delivered(load: Load) -> None:
    """
    Transition: IN_TRANSIT → DELIVERED

    WHY: Marks load as physically delivered at destination.
    Validation:
    - Must be IN_TRANSIT
    - All delivery stops completed or skipped
    - POD + BOL present

    Side Effects:
    - Sets delivered_at timestamp
    """
    if load.status != Load.Status.IN_TRANSIT:
        raise ServiceError("Load is not in IN_TRANSIT status.")

    # Delivery stops must be completed or skipped
    delivery_stops = load.stops.filter(stop_type=LoadStop.StopType.DELIVERY)
    if delivery_stops.exists():
        incomplete = delivery_stops.exclude(
            status__in=[LoadStop.StopStatus.COMPLETED, LoadStop.StopStatus.SKIPPED]
        )
        if incomplete.exists():
            raise ServiceError(
                "Cannot mark as delivered. All delivery stops must be completed or skipped."
            )

    # Required documents (POD, BOL)
    missing_types = []
    for doc_type in LoadDocument.REQUIRED_FOR_COMPLETION:
        if not load.documents.filter(document_type=doc_type).exists():
            missing_types.append(LoadDocument.DocumentType(doc_type).label)

    if missing_types:
        raise ServiceError(
            f"Cannot mark as delivered. These documents are missing: {', '.join(missing_types)}"
        )

    load.status = Load.Status.DELIVERED
    load.delivered_at = timezone.now()
    load.save(update_fields=["status", "delivered_at", "updated_at"])
