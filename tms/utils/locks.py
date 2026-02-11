from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from tms.models import Load
from tms.services import load_locks


def require_load_lock(view_func):
    @wraps(view_func)
    def _wrapped(request, load_id, *args, **kwargs):
        load = Load.objects.filter(load_id=load_id).first()
        if not load:
            # no load found, let the view handle the 404
            return view_func(request, load_id, *args, **kwargs)

        if request.method != "POST":
            # Only enforce locks on POST requests (i.e. form submissions).
            return view_func(request, load_id, *args, **kwargs)

        if not load_locks.user_can_write(load=load, user=request.user):
            lock = getattr(load, "lock", None)
            if lock and not lock.is_expired():
                messages.error(
                    request,
                    f"Load is currently locked by {lock.locked_by}. Please try again later or request takeover.",
                )
            else:
                messages.error(
                    request,
                    "Load is currently locked by another user. Please try again later or request takeover. ",
                )
            return redirect("load_detail", load_id=load_id)

        return view_func(request, load_id, *args, **kwargs)

    return _wrapped
