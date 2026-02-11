from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS += [
    "debug_toolbar",
    "django_extensions",
    "django_stubs_ext",
]

MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]


# TEMPORARY: Use R2 in development for testing
# Change this back to False after testing
USE_R2_IN_DEV = False

if USE_R2_IN_DEV:
    # Use Cloudflare R2 for testing
    # Override STORAGES to use Cloudflare R2
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }

