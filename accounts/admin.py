"""
Django admin configuration for User model.

Benefits of admin customization:
- Control what fields appear in list view
- Organize fields into fieldsets (sections)
- Make fields read-only (created_at, updated_at)
- Add custom methods (get_groups)
- Enable role assignment via groups interface
"""

from django.contrib import admin
from django.contrib.auth import get_user_model

CustomUser = get_user_model()


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    """
    Admin interface for User model.

    Customization features:
    - list_display: What columns show in the list view
    - fieldsets: Organize form fields into collapsible sections
    - readonly_fields: Fields that display but can't be edited
    - search_fields: Fields searchable via admin search bar
    - list_filter: Filter options in right sidebar
    """

    # Columns shown in user list view
    # get_groups is a custom method defined below
    list_display = (
        "username",
        "email",
        "get_full_name",
        "get_groups",
        "is_active",
        "last_login",
    )

    # Search by username, email, or name
    search_fields = ("username", "email", "first_name", "last_name")

    # Filter options in right sidebar
    list_filter = ("is_active", "is_staff", "is_superuser", "groups", "date_joined")

    # Organize form fields into fieldsets (collapsible sections)
    # Format: ("Section Title", {"fields": (...), "classes": ("collapse",)})
    fieldsets = (
        # Account credentials
        (
            "Authentication",
            {
                "fields": ("username", "password"),
                "description": "User login credentials. Use Change password link to update.",
            },
        ),
        # Personal information
        (
            "Personal Information",
            {
                "fields": ("first_name", "last_name", "email", "phone"),
            },
        ),
        # RBAC - assign user to groups and permissions
        (
            "Roles & Permissions",
            {
                "fields": ("groups", "user_permissions"),
                "description": "Assign user to groups to grant permissions. Groups: Dispatcher, Tracker, Accounts, Manager",
            },
        ),
        # Admin status
        (
            "Admin Status",
            {
                "fields": ("is_active", "is_staff", "is_superuser"),
                "description": "is_staff: Can access admin. is_superuser: Has all permissions.",
            },
        ),
        # Audit timestamps (read-only)
        (
            "Timestamps",
            {
                "fields": ("date_joined", "last_login", "created_at", "updated_at"),
                "classes": ("collapse",),  # Collapsed by default
                "description": "Automatically managed by the system.",
            },
        ),
    )

    # Make timestamp fields read-only (can view but not edit)
    readonly_fields = ("date_joined", "last_login", "created_at", "updated_at")

    # Pagination - show N users per page
    list_per_page = 50

    # Inline display - show custom data on user list
    def get_groups(self, obj):
        """
        Display user's groups in list view.

        Args:
            obj (User): The user object for this row

        Returns:
            str: Comma-separated group names or "—" if no groups
        """
        groups = obj.groups.all()
        if groups:
            return ", ".join([g.name for g in groups])
        return "—"  # Em dash for empty

    # Set column header for get_groups method
    get_groups.short_description = "Roles"

    # Allow sorting by this column
    get_groups.admin_order_field = "groups__name"
