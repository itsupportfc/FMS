from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models


class User(AbstractUser):
    """Custom user model extending Django's AbstractUser."""

    # Django’s enum pattern for model fields.
    class Role(models.TextChoices):
        # actual value stored in the database, human-readable name
        DISPATCHER = "dispatcher", "Dispatcher"
        TRACKING_AGENT = "tracking_agent", "Tracking Agent"
        ACCOUNTS = "accounts", "Accounts"
        MANAGER = "manager", "Manager"
        ADMIN = "admin", "Admin"

    role = models.CharField(
        choices=Role.choices,
        default=Role.DISPATCHER,
        max_length=20,
        help_text="User role for permission management",
    )
    email = models.EmailField(unique=True)
    phone_regex = RegexValidator(regex=r"^\+\d{10,15}$")
    phone = models.CharField(validators=[phone_regex], max_length=20, null=True)

    is_active = models.BooleanField(default=True)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_full_name()} ({self.username})"
