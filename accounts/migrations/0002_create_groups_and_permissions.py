"""
Data migration to create RBAC groups and assign permissions.

This migration creates 4 groups (Dispatcher, Tracker, Accounts, Manager)
with appropriate Django permissions for each role.

Why data migration?
- Reproducible across all environments (dev, staging, production)
- Version-controlled in git (auditable history)
- Automatically runs with 'python manage.py migrate'
- Idempotent (safe to run multiple times)
"""

from django.contrib.auth.models import Group
from django.db import migrations


# Django permissions are NOT automatically enforced at the database/ORM layer.
# They only work when you explicitly check them
def create_groups_and_permissions(apps, schema_editor):
    """
    Create RBAC groups without assigning permissions.

    This function:
    1. Creates 4 groups (if they don't exist)
    2. Saves groups to the database

    Why QuerySet.get_or_create()?
    - Returns (object, created_bool) tuple
    - Creates group only if it doesn't exist
    - Safe to run migration multiple times (idempotent)
    """

    # Define groups (no permissions assigned yet)
    group_names = [
        "Dispatcher",
        "Tracker",
        "Accounts",
        "Manager",
    ]

    # Iterate through groups_config and create groups + assign permissions
    for group_name in group_names:
        # get_or_create returns (group_object, was_created_bool)
        group, created = Group.objects.get_or_create(name=group_name)

        if created:
            print(f"✓ Created group: {group_name}")


def delete_groups(apps, schema_editor):
    """
    Reverse function - removes groups if migration is rolled back.

    Called when running: python manage.py migrate accounts 0001

    Why reverse?
    - Django requires reverse function for all data migrations
    - Allows rollback without errors
    - Makes migration properly reversible
    """
    Group = apps.get_model("auth", "Group")

    # Delete our 4 groups by name
    deleted_count, _ = Group.objects.filter(
        name__in=["Dispatcher", "Tracker", "Accounts", "Manager"]
    ).delete()

    print(f"✓ Deleted {deleted_count} groups during rollback")


class Migration(migrations.Migration):
    """
    Migration class - Django's ORM automatically processes this.

    Dependencies:
    - Depends on 0001_initial to ensure User model exists

    Operations:
    - RunPython executes our functions (forward & reverse)
    """

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_groups_and_permissions,
            delete_groups,  # Reverse function
        ),
    ]
