"""
Role-based access control (RBAC) helper functions.

These functions check if a user belongs to specific groups.
Centralize role checks here to avoid repeating user.groups.filter() everywhere.

Why helper functions?
- DRY principle (Don't Repeat Yourself)
- Single place to update role logic
- Consistent across views, templates, services
- Easier to test permission logic
"""

from django.contrib.auth import get_user_model

User = get_user_model()


def _user_has_group(user, group_name):
    """Check group membership using cached groups (avoids N+1 queries)."""
    # .all() is cached by Django after the first evaluation
    return any(g.name == group_name for g in user.groups.all())


def is_dispatcher(user) -> bool:
    """Check if user is in Dispatcher group."""
    return _user_has_group(user, "Dispatcher")


def is_tracker(user) -> bool:
    """Check if user is in Tracker group."""
    return _user_has_group(user, "Tracker")


def is_accounts(user) -> bool:
    """Check if user is in Accounts group."""
    return _user_has_group(user, "Accounts")


def is_manager(user) -> bool:
    """Check if user is in Manager group."""
    return _user_has_group(user, "Manager")


def has_any_role(user, *role_names) -> bool:
    """Check if user belongs to any of the specified roles (groups)."""
    if not user or user.is_anonymous:
        return False
    return user.groups.filter(name__in=role_names).exists()
