from django.contrib.auth.views import PasswordChangeDoneView, PasswordChangeView
from django.urls import reverse_lazy


class CustomPasswordChangeView(PasswordChangeView):
    """Custom password change view with Tailwind styling."""

    template_name = "registration/password_change.html"
    success_url = reverse_lazy("password_change_done")


class CustomPasswordChangeDoneView(PasswordChangeDoneView):
    """Custom password change done view with Tailwind styling."""

    template_name = "registration/password_change_done.html"
