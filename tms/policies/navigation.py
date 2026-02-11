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
