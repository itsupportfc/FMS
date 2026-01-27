from django.db import transaction

from tms.models import LoadStop
from tms.services.exceptions import ServiceError


def _validate_stops_business_rules(stop_formset):
    """
    V1 sanity checks *before saving*:
    - at least 2 non-deleted stops
    - at least one pickup and one delivery
    """
    errors = []
    stops = []
    for f in stop_formset.forms:
        if not hasattr(f, "cleaned_data"):
            continue  # skip invalid forms

        cd = f.cleaned_data
        if not cd:
            continue

        if cd.get("DELETE"):
            continue  # skip deleted forms

        # ignore completely empty extra forms
        if (
            not cd.get("facility") and not cd.get("stop_type")
            # and not cd.get("sequence")
        ):
            continue

        stops.append(cd)

    if len(stops) < 2:
        raise ServiceError("At least 2 stops (Pickup and Delivery) are required.")

    has_pickup = any(cd.get("stop_type") == LoadStop.StopType.PICKUP for cd in stops)
    has_delivery = any(
        cd.get("stop_type") == LoadStop.StopType.DELIVERY for cd in stops
    )

    if not has_pickup or not has_delivery:
        raise ServiceError("Route must include at least 1 Pickup and 1 Delivery stop.")

    # seqs = [s.get("sequence") for s in stops if s.get("sequence") is not None]
    # if len(seqs) != len(set(seqs)):
    #     raise ServiceError("Stop sequence numbers must be unique.")

    # sorted_seqs = sorted(seqs)
    # if sorted_seqs and sorted_seqs[0] != 1:
    #     raise ServiceError("Stop sequence must start at 1.")
    # if sorted_seqs and sorted_seqs != list(range(1, len(sorted_seqs) + 1)):
    #     raise ServiceError("Stop sequence must be continuous (1,2,3...).")

    for s in stops:
        if s.get("appointment_type") == "appt" and not (
            s.get("appt_start") or s.get("appt_end")
        ):
            raise ServiceError(
                "For APPT stops, provide at least appt_start (or a window)."
            )


def create_load_with_stops(*, dispatcher, load_form, stop_formset):
    """
    Atomic create: Load + Stops.
    Assumes: load_form.is_valid() and stop_formset.is_valid() already True.
    """
    _validate_stops_business_rules(stop_formset)

    with transaction.atomic():
        load = load_form.save(commit=False)
        load.dispatcher = dispatcher
        load.save()

        stop_formset.instance = load
        stops = stop_formset.save(commit=False)

        for i, stop in enumerate(stops, start=1):
            stop.load = load
            stop.sequence = i
            stop.save()
        # doubt?
        if hasattr(stop_formset, "save_m2m"):
            stop_formset.save_m2m()

    return load
