from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models


class User(AbstractUser):
    """Custom user model extending Django's AbstractUser."""

    email = models.EmailField(unique=True)
    phone_regex = RegexValidator(regex=r"^\+\d{10,15}$")
    phone = models.CharField(validators=[phone_regex], max_length=20, null=True)

    is_active = models.BooleanField(default=True)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.username

    def get_full_name(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.username

    def get_groups_display(self):
        """
        Return comma-separated list of group names.

        Usage: user.get_groups_display() → "Dispatcher, Manager"
        Useful for templates and admin display.
        """
        return ", ".join([g.name for g in self.groups.all()]) or "No roles"
