from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import CustomPasswordChangeDoneView, CustomPasswordChangeView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Custom password change views (before generic auth urls)
    path(
        "accounts/password_change/",
        CustomPasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "accounts/password_change/done/",
        CustomPasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    # All other auth URLs (login, logout, password reset, etc.)
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("tms.urls")),
]

# Serve user-uploaded media in development.
# In production, serve media via CDN or web server (e.g., Nginx) instead.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # Add debug toolbar URLs in development
    if "debug_toolbar" in settings.INSTALLED_APPS:
        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

# admin customisation
admin.site.site_header = "Truck Management System"
admin.site.site_title = "TMS"
admin.site.index_title = "TMS Portal"
