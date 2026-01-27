def get_sidebar_items(user):
    """
    Pure function. No request. No DB writes. Safe to test.
    """
    role = getattr(user, "role", None)

    if role == "dispatcher":
        return [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Create Load", "url": "create_load"},
            {"label": "Loads", "url": "loads_list"},
        ]
    if role == "tracking_agent":
        return [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Active Loads", "url": "active_loads"},
        ]

    return []
