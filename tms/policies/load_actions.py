from tms.models import Load
from tms.policies.roles import is_dispatcher, is_tracking_agent


def actions_for(user, load: Load) -> list[str]:
    actions: list[str] = []

    if is_dispatcher(user):
        if load.status == Load.Status.BOOKED and load.can_handover():
            actions.append("handover_to_tracking")
        if load.status not in [
            Load.Status.COMPLETED,
            Load.Status.DELIVERED,
            Load.Status.CANCELLED,
        ]:
            actions.append("cancel_load")
            actions.append("create_reschedule_request")
        if load.status not in [Load.Status.COMPLETED, Load.Status.CANCELLED]:
            actions.append("add_accessorial")

    if is_tracking_agent(user):
        if load.status == Load.Status.DISPATCHED:
            actions.append("start_transit")

        if load.status == Load.Status.IN_TRANSIT:
            actions.append("mark_delivered")

        if load.status == Load.Status.DELIVERED:
            actions.append("complete_load")

        if load.status in [Load.Status.DISPATCHED, Load.Status.IN_TRANSIT]:
            actions.append("add_tracking_update")

        if load.status not in [
            Load.Status.COMPLETED,
            Load.Status.CANCELLED,
            Load.Status.DELIVERED,
        ]:
            actions.append("create_reschedule_request")

        if load.status not in [Load.Status.COMPLETED, Load.Status.CANCELLED]:
            actions.append("add_accessorial")

    # Common actions
    if getattr(load, "driver_id", None):
        actions.append("view_driver_hos")

    actions.append("upload_document")
    return actions
