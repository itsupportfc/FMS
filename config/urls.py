from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("tms.urls")),
]

# Serve user-uploaded media in development.
# In production, serve media via CDN or web server (e.g., Nginx) instead.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


# admin customisation
admin.site.site_header = "Truck Management System"
admin.site.site_title = "TMS"
admin.site.index_title = "TMS Portal"
