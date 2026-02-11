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


def is_dispatcher(user) -> bool:
    """Check if user is in Dispatcher group."""
    if not user or user.is_anonymous:
        return False
    return user.groups.filter(name="Dispatcher").exists()


def is_tracker(user) -> bool:
    """Check if user is in Tracker group."""
    if not user or user.is_anonymous:
        return False
    return user.groups.filter(name="Tracker").exists()


def is_accounts(user) -> bool:
    """Check if user is in Accounts group."""
    if not user or user.is_anonymous:
        return False
    return user.groups.filter(name="Accounts").exists()


def is_manager(user) -> bool:
    """Check if user is in Manager group."""
    if not user or user.is_anonymous:
        return False
    return user.groups.filter(name="Manager").exists()

def has_any_role(user, *role_names) -> bool:
    """Check if user belongs to any of the specified roles (groups)."""
    if not user or user.is_anonymous:
        return False
    return user.groups.filter(name__in=role_names).exists()