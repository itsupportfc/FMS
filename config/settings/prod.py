from .base import *  # noqa: F403

DEBUG = False

# Use Cloudflare R2 for production
# Override STORAGES to use Cloudflare R2 in production
STORAGES["default"] = {
    "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
}
