def is_dispatcher(user) -> bool:
    return getattr(user, "role", None) == "dispatcher"


def is_tracking_agent(user) -> bool:
    return getattr(user, "role", None) == "tracking_agent"
