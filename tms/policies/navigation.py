from tms.policies.roles import is_accounts, is_dispatcher, is_manager, is_tracker


def get_sidebar_items(user):
    """
    Pure function. No request. No DB writes. Safe to test.
    """

    if is_dispatcher(user) or is_manager(user):
        return [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Create Load", "url": "create_load"},
            {"label": "All Loads", "url": "loads_list"},
            {"label": "My Loads", "url": "my_loads"},
            {"label": "Facilities", "url": "facilities_list"},
            {"label": "Brokers", "url": "brokers_list"},
            {"label": "Carriers", "url": "carriers_list"},
            {"label": "Owner Operators", "url": "owner_operators_list"},
            {"label": "Drivers", "url": "drivers_list"},
            {"label": "Trucks", "url": "trucks_list"},
        ]
    if is_tracker(user):
        return [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Active Loads", "url": "active_loads"},
        ]
    if is_accounts(user):
        return [
            {"label": "Dashboard", "url": "dashboard"},
            {"label": "Loads", "url": "loads_list"},
        ]

    return []
