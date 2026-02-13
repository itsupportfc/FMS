import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from tms.models import Load, LoadStop


@dataclass(frozen=True)
class RouteSnapshotResult:
    changed: bool
    reason: str


@transaction.atomic
def refresh_route_snapshot(*, load: Load, now=None) -> RouteSnapshotResult:
    """
    Single source of truth to denormalize route summary fields onto Load.

    Why denormalize?
    - loads_list should NOT prefetch stops (expensive)
    - origin/destination properties were causing DB hits
    - dashboard/list filters become cheap & index-friendly

    What we store (V1):
    - pickup_city/state/appt_start/appt_end (from first pickup stop by sequence)
    - delivery_city/state/appt_start/appt_end (from last delivery stop by sequence)
    """
    now = now or timezone.now()

    # Pull the *minimum required* fields for snapshot.
    stops = list(
        LoadStop.objects.filter(load=load)
        .select_related("facility")
        .only(
            "id",
            "stop_type",
            "sequence",
            "appt_start",
            "appt_end",
            "facility__city",
            "facility__state",
        )
        .order_by("sequence")
    )
    # next(generator, default) => return the first match and break , if not found return default
    first_pickup = next(
        (s for s in stops if s.stop_type == LoadStop.StopType.PICKUP), None
    )
    last_delivery = next(
        (s for s in reversed(stops) if s.stop_type == LoadStop.StopType.DELIVERY), None
    )
    # Build new snapshot values
    new_values = {
        "origin_city": getattr(first_pickup.facility, "city", None)
        if first_pickup
        else None,
        "origin_state": getattr(first_pickup.facility, "state", None)
        if first_pickup
        else None,
        "origin_appt_start": first_pickup.appt_start if first_pickup else None,
        "origin_appt_end": first_pickup.appt_end if first_pickup else None,
        # destination
        "destination_city": getattr(last_delivery.facility, "city", None)
        if last_delivery
        else None,
        "destination_state": getattr(last_delivery.facility, "state", None)
        if last_delivery
        else None,
        "destination_appt_start": last_delivery.appt_start if last_delivery else None,
        "destination_appt_end": last_delivery.appt_end if last_delivery else None,
    }

    # Detect whether anything changed (so we don't write on every call)
    changed_fields = []
    for field, new_val in new_values.items():
        if getattr(load, field) != new_val:
            changed_fields.append(field)

    if not changed_fields:
        return RouteSnapshotResult(changed=False, reason="No changes detected")

    for f in changed_fields:
        setattr(load, f, new_values[f])

    load.save()
    return RouteSnapshotResult(
        changed=True, reason=f"Updated fields: {', '.join(changed_fields)}"
    )
