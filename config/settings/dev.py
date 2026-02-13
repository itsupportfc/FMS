from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]


# Add development-only apps
INSTALLED_APPS += [
    "debug_toolbar",
    "django_extensions",
]
# Add debug toolbar middleware
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.common.CommonMiddleware") + 1,
    "debug_toolbar.middleware.DebugToolbarMiddleware",
)
# needed for Debug Toolbar 
INTERNAL_IPS = [
    "127.0.0.1",
]
# Development-specific settings
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# TEMPORARY: Use R2 in development for testing
# Change this back to False after testing
USE_R2_IN_DEV = False

if USE_R2_IN_DEV:
    # Use Cloudflare R2 for testing
    # Override STORAGES to use Cloudflare R2
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }
