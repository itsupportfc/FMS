def layout_context(request):
    user = request.user

    if not user.is_authenticated:
        return {}

    # Sidebar config based on user role
    if user.role == "dispatcher":
        sidebar_items = [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Create Load", "url": "create_load"},
            {"label": "Loads", "url": "loads_list"},
            # {"label": "Carriers", "url": "carriers_list"},
            # {"label": "Drivers", "url": "drivers_list"},
        ]
    elif user.role == "tracking_agent":
        sidebar_items = [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Active Loads", "url": "active_loads"},
        ]
    else:
        sidebar_items = []

    return {
        "sidebar_items": sidebar_items,
    }
