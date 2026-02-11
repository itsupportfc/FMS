from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from tms.models import Load, LoadLock

DEFAULT_TTL_SECONDS = 30


@dataclass(frozen=True)
class LockResult:
    lock: Optional[LoadLock]
    acquired: bool
    locked_by_other: bool


def _now():
    return timezone.now()


def acquire_lock(
    *, load: Load, user, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> LockResult:
    now = _now()
    new_expiry = now + timedelta(seconds=ttl_seconds)

    with transaction.atomic():
        lock = LoadLock.objects.select_for_update().filter(load=load).first()

        if lock is None:
            lock = LoadLock.objects.create(
                load=load,
                locked_by=user,
                locked_at=now,
                expires_at=new_expiry,
            )
            return LockResult(lock=lock, acquired=True, locked_by_other=False)

        if lock.is_expired():
            lock.locked_by = user
            lock.locked_at = now
            lock.expires_at = new_expiry
            lock.save(update_fields=["locked_by", "locked_at", "expires_at"])
            return LockResult(lock=lock, acquired=True, locked_by_other=False)

        if lock.locked_by == user:
            # Already mine -> refresh TTL.
            lock.expires_at = new_expiry
            lock.save(update_fields=["expires_at"])
            return LockResult(lock=lock, acquired=True, locked_by_other=False)

        return LockResult(lock=lock, acquired=False, locked_by_other=True)


def refresh_lock(*, load: Load, user, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    now = _now()
    new_expiry = now + timedelta(seconds=ttl_seconds)

    with transaction.atomic():
        lock = LoadLock.objects.select_for_update().filter(load=load).first()
        if not lock or lock.is_expired() or lock.locked_by != user:
            return False

        lock.expires_at = new_expiry
        lock.save(update_fields=["expires_at"])
        return True


def release_lock(*, load: Load, user, allow_override: bool = False) -> bool:
    with transaction.atomic():
        lock = LoadLock.objects.select_for_update().filter(load=load).first()
        if not lock:
            return False

        if lock.locked_by == user or allow_override:
            lock.delete()
            return True
        return False


def user_can_write(*, load: Load, user) -> bool:
    lock = LoadLock.objects.filter(load=load).first()
    if not lock or lock.is_expired():
        return True
    return lock.locked_by == user


def can_take_over(*, user) -> bool:
    if user.is_superuser:
        return True
    if user.has_perm("tms.override_load_lock"):
        return True
    return user.groups.filter(name__in=["Manager"]).exists()


def take_over_lock(
    *, load: Load, user, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> LockResult:
    if not can_take_over(user=user):
        lock = LoadLock.objects.filter(load=load).first()
        return LockResult(lock=lock, acquired=False, locked_by_other=bool(lock))

    now = _now()
    new_expiry = now + timedelta(seconds=ttl_seconds)

    with transaction.atomic():
        lock = LoadLock.objects.select_for_update().filter(load=load).first()
        if lock is None:
            lock = LoadLock.objects.create(
                load=load, locked_by=user, locked_at=now, expires_at=new_expiry
            )
            return LockResult(lock=lock, acquired=True, locked_by_other=False)

        lock.locked_by = user
        lock.locked_at = now
        lock.expires_at = new_expiry
        lock.save(update_fields=["locked_by", "locked_at", "expires_at"])
        return LockResult(lock=lock, acquired=True, locked_by_other=False)
