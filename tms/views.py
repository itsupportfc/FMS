from datetime import datetime, time, timedelta
from io import BytesIO
from operator import is_

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import (
    BooleanField,
    Case,
    DateTimeField,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from accounts.models import User
from tms.policies.load_actions import get_available_actions
from tms.policies.roles import (
    has_any_role,
    is_accounts,
    is_dispatcher,
    is_manager,
    is_tracker,
)
from tms.services import load_locks
from tms.services.cancel import cancel_load
from tms.services.completion import complete_load
from tms.services.delivery import mark_delivered
from tms.services.duty_logs import create_duty_log
from tms.services.exceptions import ServiceError
from tms.services.handover import handover_to_tracking
from tms.services.hos import HOSCalculator
from tms.services.load_creation import create_load_with_stops
from tms.services.route_snapshot import refresh_route_snapshot
from tms.services.transit import start_transit
from tms.utils.locks import require_load_lock

from .forms import (
    AccessorialForm,
    BrokerForm,
    CarrierForm,
    DocumentUploadForm,
    DriverForm,
    DutyLogForm,
    FacilityForm,
    LoadForm,
    LoadNoteForm,
    LoadStopForm,
    LoadStopFormSet,
    OwnerOperatorForm,
    RescheduleRequestForm,
    StopEditForm,
    TrackingUpdateForm,
    TruckForm,
)
from .models import (
    Accessorial,
    Broker,
    Carrier,
    Driver,
    Facility,
    Load,
    LoadDocument,
    LoadNote,
    LoadStop,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
)
from .services.carrier_creation import CarrierCreationError, create_carrier_with_assets


@login_required
def dashboard(request):
    """Decide dashboard based on user role"""

    user = request.user

    if is_dispatcher(user):
        today = timezone.localdate()

        rc_exists_sq = LoadDocument.objects.filter(
            load=OuterRef("pk"), document_type=LoadDocument.DocumentType.RC
        )
        latest_new_eta_sq = (
            TrackingUpdate.objects.filter(load=OuterRef("pk"), new_eta__isnull=False)
            .order_by("-created_at")
            .values("new_eta")[:1]
        )
        # 3) "Target pickup time" for first pickup stop:
        #    Use appt_start/appt_end for BOTH APPT and FCFS if present, else NULL -> show "FCFS/TBD" in UI.
        first_pickup_appt_start_sq = (
            LoadStop.objects.filter(
                load=OuterRef("pk"), stop_type=LoadStop.StopType.PICKUP
            )
            .order_by("sequence")
            .values("appt_start")[:1]
        )
        first_pickup_appt_end_sq = (
            LoadStop.objects.filter(
                load=OuterRef("pk"), stop_type=LoadStop.StopType.PICKUP
            )
            .order_by("sequence")
            .values("appt_end")[:1]
        )

        base_qs = (
            Load.objects.filter(dispatcher=user)
            .select_related("broker", "carrier", "truck", "driver")
            .annotate(
                # RC missing bucket need this
                has_rc=Exists(rc_exists_sq),
                # Pickup Today needs this (scheduled/target pickup time)
                pickup_target_dt=Coalesce(
                    Subquery(first_pickup_appt_start_sq, output_field=DateTimeField()),
                    Subquery(first_pickup_appt_end_sq, output_field=DateTimeField()),
                ),
                # Delivery Today uses load.planned_eta directly
                delivery_target_dt=F("planned_eta"),
                # Delayed: current ETA = latest new_eta else planned_eta
                current_eta_dt=Coalesce(
                    Subquery(latest_new_eta_sq, output_field=DateTimeField()),
                    F("planned_eta"),
                ),
                planned_eta_dt=F("planned_eta"),
            )
            .annotate(
                is_late=Case(
                    When(
                        Q(current_eta_dt__isnull=False)
                        & Q(planned_eta_dt__isnull=False)
                        & Q(current_eta_dt__gt=F("planned_eta_dt")),
                        then=Value(True),
                    ),
                    default=Value(False),
                    output_field=BooleanField(),
                )
            )
            .order_by("-created_at")
        )

        excluded_terminal_statuses = [
            Load.Status.CANCELLED,
            Load.Status.COMPLETED,
            Load.Status.DELIVERED,
        ]

        # 1) RC Missing: created, status=booked, but RC missing
        rc_missing_loads = base_qs.filter(status=Load.Status.BOOKED, has_rc=False)

        # 2) Delayed
        delayed_loads = base_qs.filter(is_late=True).exclude(
            status__in=excluded_terminal_statuses
        )

        # 3) In Transit
        in_transit_loads = base_qs.filter(status=Load.Status.IN_TRANSIT)
        # 4) Pickup Today (only loads that actually have a target pickup datetime)
        pickup_today_loads = base_qs.filter(pickup_target_dt__date=today).exclude(
            status__in=excluded_terminal_statuses
        )
        # 5) Delivery Today (planned_eta date = today)
        delivery_today_loads = base_qs.filter(delivery_target_dt__date=today).exclude(
            status__in=excluded_terminal_statuses
        )

        # PERFORMANCE: COUNT ONCE
        rc_missing_count = rc_missing_loads.count()
        delayed_count = delayed_loads.count()
        in_transit_count = in_transit_loads.count()
        pickup_today_count = pickup_today_loads.count()
        delivery_today_count = delivery_today_loads.count()

        context = {
            "rc_missing_loads": rc_missing_loads,
            "delayed_loads": delayed_loads,
            "in_transit_loads": in_transit_loads,
            "pickup_today_loads": pickup_today_loads,
            "delivery_today_loads": delivery_today_loads,
            "today": today,
            "dashboard_template": "dashboard/_dispatcher_dashboard.html",
            # ADDED COUNTS
            "rc_missing_count": rc_missing_count,
            "delayed_count": delayed_count,
            "in_transit_count": in_transit_count,
            "pickup_today_count": pickup_today_count,
            "delivery_today_count": delivery_today_count,
        }
        return render(request, "dashboard/dashboard.html", context)

    elif is_tracker(user):
        context = {
            "dashboard_template": "dashboard/_tracker_dashboard.html",
        }
        return render(request, "dashboard/dashboard.html", context)

    elif is_accounts(user):
        context = {
            "dashboard_template": "dashboard/_accounts_dashboard.html",
        }
        return render(request, "dashboard/dashboard.html", context)

    elif is_manager(user):
        context = {
            "dashboard_template": "dashboard/_manager_dashboard.html",
        }
        return render(request, "dashboard/dashboard.html", context)

    else:
        return HttpResponse("No dashboard available for your role.", status=403)


@login_required
def create_load(request):
    """
    Create new freight load (dispatcher only) + create initial stops (V1 multi-stop).

    Workflow:
    1. GET: Show empty LoadForm + Stop formset (at least 2 blank forms)
    2. POST: Validate LoadForm + Stop formset → save → redirect to load_detail

    WHY do stops on create:
    - Dispatcher should define the route at booking time.
    - Later, once RC exists, stops will be locked (read-only).
    """

    if not is_dispatcher(request.user):
        messages.error(request, "Only dispatchers can create loads.")
        return redirect("dashboard")

    if request.method == "POST":
        form = LoadForm(
            request.POST, user=request.user
        )  # binds the POST data to the parent form.
        # create a Load object only in memory not in DB, but why?
        # coz formset needs a parent clas instance, but load may not be created now. so givew a dummy
        temp_load = Load(dispatcher=request.user)
        stop_formset = LoadStopFormSet(request.POST, instance=temp_load, prefix="stops")
        if form.is_valid() and stop_formset.is_valid():
            try:
                load = create_load_with_stops(
                    dispatcher=request.user, load_form=form, stop_formset=stop_formset
                )
            except ServiceError as e:
                form.add_error(None, str(e))  # non-field error
                return render(
                    request,
                    "tms/create_load.html",
                    {"form": form, "stop_formset": stop_formset},
                )

            messages.success(request, f"Load {load.load_id} created successfully.")
            # Redirect to load detail page (PRG pattern: Post-Redirect-Get)
            # WHY: Prevents duplicate submissions if user refreshes page
            return redirect("load_detail", load_id=load.load_id)
    else:
        # GET request - show empty form
        form = LoadForm()
        temp_load = Load(dispatcher=request.user)
        stop_formset = LoadStopFormSet(instance=temp_load, prefix="stops")

    # Render template with form
    # WHY: Same template for GET (empty form) and POST (form with errors)
    return render(
        request, "tms/create_load.html", {"form": form, "stop_formset": stop_formset}
    )


# HTMX endpoint to render a single empty LoadStop form row
@login_required
def load_stop_row(request):
    """
    HTMX: returns ONE new stop row for the formset.
    Also updates stops-TOTAL_FORMS using hx-swap-oob.
    """

    index = int(request.GET.get("index", 0))

    # Create a single empty form (not formset) for the new stop
    stop_form = LoadStopForm()

    # Manually set the form prefix and initial data
    stop_form.prefix = f"stops-{index}"

    html = render_to_string(
        "tms/partials/_stop_row.html",
        {"stop_form": stop_form, "index": index, "next_total": index + 1},
        request=request,
    )
    return HttpResponse(html)


@login_required
def load_detail(request, load_id):
    """
    Display and edit load details + show stops (read-only)

    Single view for both:
    - GET: Display current load state + editable form
    - POST: Update load fields (not status - that's via change_status view)

    WHY single view: Reduces code duplication. Edit form looks identical
    to detail view, just with editable fields instead of readonly text.

    V1 Rule:
    - Stops are read-only on load_detail page.
    - Stop editing only happens during load creation.

    """

    # select_related() => for FK
    # prefetch_related() => for reverse relations
    # make sure templates does not do DB hits
    # list() => as django qs is lazy

    load = get_object_or_404(Load.objects.for_detail_display(), load_id=load_id)

    # LOCK
    lock_result = load_locks.acquire_lock(load=load, user=request.user)
    lock = lock_result.lock
    is_locked_by_other = lock_result.locked_by_other

    if request.method == "POST":
        if lock and is_locked_by_other:
            messages.error(
                request,
                f"Load is currently being edited by {lock.locked_by.get_full_name() or lock.locked_by.username}. Please try again later.",
            )
            return redirect("load_detail", load_id=load.load_id)

        # Update existing load with form data
        # WHY instance=load: Pre-populates form with current values
        # WHY user=request.user: Form needs user for permission checks
        form = LoadForm(request.POST, instance=load, user=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, "Load updated successfully.")
            load_locks.release_lock(
                load=load, user=request.user, allow_override=False
            )  # Only release if it's currently locked by this user
            return redirect("load_detail", load_id=load.load_id)
    else:
        # GET request: Show form pre-filled with current load data
        form = LoadForm(instance=load, user=request.user)

    # LoadDocument upload form (always shown, even on COMPLETED loads for audit)
    doc_form = DocumentUploadForm()

    # Get list of tracking agents for handover dropdown
    # WHY: Dispatcher selects who to handover load to
    # agents = User.objects.filter(groups__name="Dispatcher")
    agents = User.objects.filter(groups__name__in=["Dispatcher", "Tracker"]).distinct()

    # Get available actions for current user
    # WHY: Template uses this to show/hide action buttons
    available_actions = get_available_actions(request.user, load)

    # Use prefetched objects (no template ORM calls)
    stops = list(load.stops.all())  # already ordered via prefetch
    documents = list(load.documents.all())
    has_documents = bool(documents)
    reschedule_requests = list(load.reschedule_requests.all())
    notes = list(load.notes.all())
    note_form = LoadNoteForm()
    accessorials = list(load.accessorials.all())
    tracking_updates = list(load.tracking_updates.all())
    # enforce newest-first in Python (prefetch doesn't guarantee ordering unless qs provided)
    # tracking_updates.sort(key=lambda x: x.created_at, reverse=True)

    # ETA: current = latest tracking update new_eta else planned_eta
    latest_eta_update = next((tu for tu in tracking_updates if tu.new_eta), None)
    current_eta = latest_eta_update.new_eta if latest_eta_update else load.planned_eta
    planned_eta = load.planned_eta
    is_late = bool(current_eta and planned_eta and current_eta > planned_eta)

    # Related activity lists for sidebar/history panels
    # tracking_updates = load.tracking_updates.all()
    # reschedule_requests = load.reschedule_requests.all()

    # notes
    # notes = load.notes.select_related("author").all()
    # note_form = LoadNoteForm()

    # # ETA
    # latest_eta_update = (
    #     load.tracking_updates.filter(new_eta__isnull=False)
    #     .order_by("-created_at")
    #     .first()
    # )
    # current_eta = latest_eta_update.new_eta if latest_eta_update else load.planned_eta
    # planned_eta = load.planned_eta

    return render(
        request,
        "tms/load_detail.html",
        {
            "load": load,
            "form": form,
            "doc_form": doc_form,
            "agents": agents,
            "available_actions": available_actions,
            # explicitly passed lists (fast, no ORM in templates)
            "stops": stops,
            "documents": documents,
            "has_documents": has_documents,
            "tracking_updates": tracking_updates,
            "reschedule_requests": reschedule_requests,
            "accessorials": accessorials,
            "notes": notes,
            "note_form": note_form,
            # lock context (unchanged)
            "lock": lock,
            "is_locked_by_other": is_locked_by_other,
            "can_take_over": load_locks.can_take_over(user=request.user),
            # ETA
            "current_eta": current_eta,
            "planned_eta": planned_eta,
            "is_late": is_late,
        },
    )


@login_required
def load_lock_ping(request, load_id):
    load = get_object_or_404(Load, load_id=load_id)
    load_locks.refresh_lock(load=load, user=request.user)
    return HttpResponse(status=204)  # No content, just a ping to refresh the lock


@login_required
@require_POST
def load_lock_takeover(request, load_id):
    load = get_object_or_404(Load, load_id=load_id)
    result = load_locks.take_over_lock(load=load, user=request.user)
    if result.acquired:
        messages.success(request, "You  can now edit this load.")
    else:
        messages.error(request, "Unable to take over lock. ")

    return redirect("load_detail", load_id=load.load_id)


@login_required
@require_POST
def load_lock_release(request, load_id):
    load = get_object_or_404(Load, load_id=load_id)
    load_locks.release_lock(
        load=load, user=request.user, allow_override=False
    )  # Only release if it's currently locked by this user
    if request.headers.get("HX-Request") == "true":
        return HttpResponse(status=204)  # No content, just a ping to release the lock

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        return redirect(next_url)

    return redirect("loads_list")


@login_required
@require_load_lock
def create_load_note(request, load_id):
    if request.method == "POST":
        load = get_object_or_404(Load, load_id=load_id)
        form = LoadNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.load = load
            note.author = request.user
            note.save()
            messages.success(request, "Note added.")
        else:
            messages.error(request, "Failed to add note. Please try again.")

        return redirect("load_detail", load_id=load_id)
    else:
        return redirect("load_detail", load_id=load_id)


@login_required
@require_load_lock
def upload_document(request, load_id):
    """
    Upload document to load (any user, any status).

    WHY separate view:  LoadDocument upload is a side action, not part of
    main load edit workflow. Keeps load_detail() view cleaner.

    WHY allow upload on COMPLETED loads: May need to add POD later,
    or upload detention receipts after delivery.
    """
    load = get_object_or_404(Load, load_id=load_id)

    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)

        if form.is_valid():
            # Save form but don't commit (need to set load relationship)
            doc = form.save(commit=False)

            # Link document to this load
            # WHY: Form doesn't have load field (set from URL parameter)
            doc.load = load
            # Set original filename from uploaded file
            # WHY: Already done in  LoadDocument.save() but explicit is better
            if doc.file and not doc.original_filename:
                doc.original_filename = doc.file.name

            doc.save()

            messages.success(
                request, f"{doc.get_document_type_display()} uploaded successfully."
            )

            # Redirect back to load detail page
            return redirect("load_detail", load_id=load.load_id)

    # If GET or form invalid, redirect back (shouldn't happen normally)
    # WHY: Upload form is on load_detail page, not separate page
    return redirect("load_detail", load_id=load.load_id)


@login_required
def change_status(request, load_id, action):
    """
    Handle status transition actions.

    should remain a view as it handles HTTP concerns ,
    but should call service methods
    """
    load = get_object_or_404(Load, load_id=load_id)

    # Only POST requests allowed ( prevents accidental status changes via GET)
    # WHY: Status changes modify data - should use POST, not GET
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("load_detail", load_id=load.load_id)

    try:
        if action == "handover":
            # get tracking agent from post data
            tracking_agent_id = request.POST.get("tracking_agent")
            tracking_agent = get_object_or_404(User, id=tracking_agent_id)

            # get optional instructions
            instructions = request.POST.get("instructions", "")

            # Call model methos( raises ValueError if preconsitions not met)
            handover_to_tracking(
                load=load,
                tracking_agent=tracking_agent,
                from_agent=request.user,
                instructions=instructions,
            )

            agent_name = tracking_agent.get_full_name() or tracking_agent.username
            messages.success(request, f"Load handed over to {agent_name},")

        elif action == "start_transit":
            start_transit(load)
            messages.success(request, "Load marked as In Transit")

        elif action == "mark_delivered":
            # Model validates required documents (POD, BOL)
            mark_delivered(load)
            messages.success(request, "Load marked as Delivered.")

        elif action == "complete_load":
            # Final completion - ready for billing
            complete_load(load)
            messages.success(request, "Load completed and ready for billing.")

        elif action == "cancel":
            # get optional cancellation reason
            reason = request.POST.get("reason", "")

            # call cancel method ( auto-creates TONU charge)
            cancel_load(load=load, reason=reason)
            messages.warning(request, "Load cancelled. CREATE TONU charge.")

        else:
            # Unknown action ( shouldn't happen if URLs are correct)
            messages.error(request, f"Unknown action: {action}")

    except ServiceError as e:
        # Model method raised error (preconditions not met)
        # WHY: Show error to user so they know what to fix
        messages.error(request, str(e))

    # Redirect back to load detail page (PRG pattern)
    return redirect("load_detail", load_id=load.load_id)


@login_required
def load_carrier_assets(request):
    """
    HTMX endpoint: Return driver/truck dropdowns for selected carrier.

    Called when user selects carrier in form dropdown.
    Returns HTML snippet with filtered driver/truck options.

    WHY HTMX: Better UX than full page reload. User selects carrier,
    driver/truck dropdowns update instantly without losing other form data.

    Flow:
    1. User selects carrier in dropdown
    2. HTMX fires GET request: /loads/carrier-assets/?carrier_id=5
    3. This view returns HTML with filtered options
    4. HTMX swaps content into #carrier-assets div
    5. User sees only relevant drivers/trucks for that carrier

    Returns:
    - HTML fragment (not full page) with <select> elements
    - Template: tms/partials/carrier_assets.html
    """
    carrier_id = request.GET.get("carrier")

    carrier = (
        Carrier.objects.only("id", "carrier_type").filter(id=carrier_id).first()
        if carrier_id
        else None
    )

    drivers = (
        Driver.objects.filter(
            carrier_id=carrier_id, current_status=Driver.DriverStatus.AVAILABLE
        )
        if carrier_id
        else Driver.objects.none()
    )
    trucks = (
        Truck.objects.filter(
            carrier_id=carrier_id, current_status=Truck.TruckStatus.AVAILABLE
        )
        if carrier_id
        else Truck.objects.none()
    )

    is_owner_operator = bool(
        carrier and carrier.carrier_type == Carrier.CarrierType.OWNER_OPERATOR
    )
    selected_driver_id = None
    selected_truck_id = None

    if is_owner_operator:
        selected_driver_id = drivers.values_list("id", flat=True).first()
        selected_truck_id = trucks.values_list("id", flat=True).first()

    return render(
        request,
        "tms/partials/carrier_assets.html",
        {
            "drivers": drivers,
            "trucks": trucks,
            "selected_driver_id": selected_driver_id,
            "selected_truck_id": selected_truck_id,
            "is_owner_operator": is_owner_operator,
        },
    )


@login_required
def loads_list(request):
    """
    List all loads
    - Convert date strings -> timezone-aware datetime range (index-friendly)
    - Avoid __date filters (they prevent index usage on created_at)
    """
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    from_date_str = request.GET.get("from_date", "").strip()
    to_date_str = request.GET.get("to_date", "").strip()

    # Base queryset
    qs = Load.objects.for_list_display()

    # FILTERS
    if query:
        qs = qs.filter(load_id__icontains=query)
    if status and status in Load.Status.values:
        qs = qs.filter(status=status)

    tz = timezone.get_current_timezone()

    # get Date object from date string like '2024-01-31'
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None

    #  Date object => to Datetime object => to timezone aware
    if from_date:
        start_dt = timezone.make_aware(datetime.combine(from_date, time.min), tz)
        qs = qs.filter(created_at__gte=start_dt)
    if to_date:
        # Exclusive end boundary = start of next day (clean + avoids microsecond bugs)
        end_dt = timezone.make_aware(
            datetime.combine(to_date, time.min), tz
        ) + timedelta(days=1)
        qs = qs.filter(created_at__lt=end_dt)

    # accounts should only see delivered loads (for billing purposes)
    if is_accounts(request.user):
        qs = qs.filter(status=Load.Status.DELIVERED)

    # Ordering should be LAST so DB does it once after filters
    qs = qs.order_by("-created_at")

    # FIX: pagination added
    paginator = Paginator(qs, 50)  # 50 laods per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "loads": page_obj.object_list,  # the loads for the current page
        "query": query,
        "status": status,
        "from_date": from_date,
        "to_date": to_date,
    }

    return render(request, "tms/loads_list.html", context)


def _build_my_loads_queryset(request):
    """
    Single source of truth: same queryset used by UI + export.
    Key improvements:
    - created_at filtering is timezone-aware and index-friendly (no __date)
    - uses `.only()` to avoid fetching big columns you don't display
    """
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    from_date_str = request.GET.get("from_date", "").strip()
    to_date_str = request.GET.get("to_date", "").strip()

    ZERO_MONEY = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))

    first_pickup_departed_sq = (
        LoadStop.objects.filter(load=OuterRef("pk"), stop_type=LoadStop.StopType.PICKUP)
        .order_by("sequence")
        .values("departed_at")[:1]
    )

    qs = (
        Load.objects.filter(dispatcher=request.user)
        .select_related("broker", "truck")
        .only(
            "id",
            "load_id",
            "status",
            "created_at",
            "rate",
            "miles",
            "deadhead_miles",
            "rpm",
            "delivered_at",
            "broker_id",
            "truck_id",
            "broker__id",
            "broker__name",
            "truck__id",
            "truck__truck_number",
        )
        .annotate(
            accessorial_total=Coalesce(Sum("accessorials__amount"), ZERO_MONEY),
            total_cost=ExpressionWrapper(
                Coalesce(F("rate"), ZERO_MONEY)
                + Coalesce(Sum("accessorials__amount"), ZERO_MONEY),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            pickup_actual=Subquery(first_pickup_departed_sq),
            delivery_actual=F("delivered_at"),
        )
        .order_by("-created_at")
    )

    if query:
        qs = qs.filter(load_id__icontains=query)
    if status:
        qs = qs.filter(status=status)

    # timzone aware + index friendly
    tz = timezone.get_current_timezone()
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None

    if from_date:
        start_dt = timezone.make_aware(datetime.combine(from_date, time.min), tz)
        qs = qs.filter(created_at__gte=start_dt)
    if to_date:
        end_dt = timezone.make_aware(
            datetime.combine(to_date, time.min), tz
        ) + timedelta(days=1)
        qs = qs.filter(created_at__lt=end_dt)

    return qs


@login_required
def my_loads(request):
    """Dispatcher-only list of loads assigned to the current dispatcher."""
    if not is_dispatcher(request.user):
        return HttpResponse(status=403)

    qs = _build_my_loads_queryset(request)

    # pagination
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "loads": page_obj.object_list,
        "query": request.GET.get("q", "").strip(),
        "status": request.GET.get("status", "").strip(),
        "from_date": request.GET.get("from_date", "").strip(),
        "to_date": request.GET.get("to_date", "").strip(),
    }
    return render(request, "tms/my_loads.html", context)


def my_loads_export_excel(request):
    if not is_dispatcher(request.user):
        return HttpResponse(status=403)

    loads = _build_my_loads_queryset(request)

    wb = Workbook()
    ws = wb.active
    ws.title = "My Loads"

    headers = [
        "Load ID",
        "Broker",
        "Truck No",
        "Pickup Actual",
        "Delivery Actual",
        "Miles",
        "Deadhead Miles",
        "Rate",
        "Extra Charges",
        "RPM",
        "Status",
    ]

    ws.append(headers)
    # use iterator : reduces memory use if many rows
    for load in loads.iterator(chunk_size=2000):
        ws.append(
            [
                load.load_id,
                getattr(load.broker, "name", "") if load.broker_id else "",
                getattr(load.truck, "truck_number", "") if load.truck_id else "",
                load.pickup_actual.replace(tzinfo=None) if load.pickup_actual else None,
                load.delivery_actual.replace(tzinfo=None)
                if load.delivery_actual
                else None,
                load.miles or "",
                load.deadhead_miles or "",
                float(load.rate) if load.rate is not None else 0.0,
                float(load.accessorial_total)
                if load.accessorial_total is not None
                else 0.0,
                float(load.rpm) if load.rpm is not None else None,
                load.status,
            ]
        )

    # Write to response
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    resp = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = 'attachment; filename="my_loads.xlsx"'
    return resp


@login_required
def carriers_list(request):
    """List normal carriers only (exclude owner-operators)."""
    carriers = Carrier.objects.filter(
        carrier_type=Carrier.CarrierType.COMPANY
    ).order_by("name")

    paginator = Paginator(carriers, 20)  # 20 carriers per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {"carriers": page_obj.object_list, "page_obj": page_obj}

    return render(request, "tms/carriers_list.html", context)


@login_required
def owner_operators_list(request):
    """List owner-operator carriers."""
    owner_operators = Carrier.objects.filter(
        carrier_type=Carrier.CarrierType.OWNER_OPERATOR
    ).order_by("name")

    paginator = Paginator(owner_operators, 20)  # 20 owner-operators per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {"owner_operators": page_obj.object_list, "page_obj": page_obj}
    return render(request, "tms/owner_operators_list.html", context)


@login_required
def carrier_create(request):
    """Create a new normal carrier (company only)."""

    if request.method == "POST":
        form = CarrierForm(request.POST)
        if form.is_valid():
            carrier = form.save(commit=False)
            carrier.carrier_type = Carrier.CarrierType.COMPANY
            carrier.created_by = request.user
            carrier.save()
            messages.success(request, f"Carrier '{carrier.name}' created successfully!")
            return redirect("carriers_list")
    else:
        form = CarrierForm()

    return render(request, "tms/carrier_create.html", {"form": form})


@login_required
def drivers_list(request):
    """List all drivers with pagination."""
    drivers = Driver.objects.select_related("carrier", "current_truck").order_by(
        "last_name", "first_name"
    )

    paginator = Paginator(drivers, 20)  # 20 drivers per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {"drivers": page_obj.object_list, "page_obj": page_obj}

    return render(request, "tms/drivers_list.html", context)


@login_required
def driver_create(request):
    """Create a new driver for normal carriers."""

    if request.method == "POST":
        form = DriverForm(request.POST)
        if form.is_valid():
            driver = form.save()
            messages.success(
                request, f"Driver '{driver.full_name}' created successfully!"
            )
            return redirect("drivers_list")
    else:
        form = DriverForm()

    return render(request, "tms/driver_create.html", {"form": form})


@login_required
def owner_operator_create(request):
    """Create an owner-operator with carrier, driver, and truck details."""

    if request.method == "POST":
        form = OwnerOperatorForm(request.POST)

        if form.is_valid():
            try:
                carrier_data = {
                    "name": form.cleaned_data["carrier_name"],
                    "mc_number": form.cleaned_data["mc_number"],
                    "dot_number": form.cleaned_data["dot_number"],
                    "carrier_type": Carrier.CarrierType.OWNER_OPERATOR,
                    "primary_contact_name": form.cleaned_data["primary_contact_name"],
                    "primary_phone": form.cleaned_data["primary_phone"],
                    "primary_email": form.cleaned_data["primary_email"],
                    "address_line1": form.cleaned_data["address_line1"],
                    "address_line2": form.cleaned_data.get("address_line2", ""),
                    "city": form.cleaned_data["city"],
                    "state": form.cleaned_data["state"],
                    "zip_code": form.cleaned_data["zip_code"],
                    "carrier_has_insurance": form.cleaned_data.get(
                        "carrier_has_insurance", True
                    ),
                    "notes": form.cleaned_data.get("carrier_notes", ""),
                }

                driver_data = {
                    "first_name": form.cleaned_data["driver_first_name"],
                    "last_name": form.cleaned_data["driver_last_name"],
                    "phone": form.cleaned_data["driver_phone"],
                    "email": form.cleaned_data.get("driver_email", ""),
                    "cdl_number": form.cleaned_data["cdl_number"],
                    "cdl_expiration": form.cleaned_data.get("cdl_expiration"),
                    "hos_cycle": form.cleaned_data["hos_cycle"],
                    "notes": form.cleaned_data.get("driver_notes", ""),
                }

                truck_data = {
                    "truck_number": form.cleaned_data["truck_number"],
                    "trailer_number": form.cleaned_data.get("trailer_number", ""),
                    "equipment_type": form.cleaned_data["equipment_type"],
                    "vin": form.cleaned_data.get("vin", ""),
                    "license_plate": form.cleaned_data["license_plate"],
                    "chassis_no": form.cleaned_data.get("chassis_no", ""),
                    "truck_has_insurance": form.cleaned_data.get(
                        "truck_has_insurance", True
                    ),
                    "notes": form.cleaned_data.get("truck_notes", ""),
                }

                carrier, driver, truck = create_carrier_with_assets(
                    carrier_data=carrier_data,
                    created_by=request.user,
                    driver_data=driver_data,
                    truck_data=truck_data,
                )

                driver_name = driver.full_name if driver else "-"
                truck_number = truck.truck_number if truck else "-"

                messages.success(
                    request,
                    f"Owner-operator '{carrier.name}' created successfully! "
                    f"Driver: {driver_name}, Truck: {truck_number}",
                )
                return redirect("owner_operators_list")

            except CarrierCreationError as error:
                messages.error(request, str(error))
            except ValidationError as error:
                messages.error(request, f"Validation error: {error}")
    else:
        form = OwnerOperatorForm()

    return render(request, "tms/owner_operator_create.html", {"form": form})


@login_required
def trucks_list(request):
    """List all trucks with pagination."""
    trucks = Truck.objects.select_related("carrier").order_by("truck_number")

    paginator = Paginator(trucks, 20)  # 20 trucks per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {"trucks": page_obj.object_list, "page_obj": page_obj}
    return render(request, "tms/trucks_list.html", context)


@login_required
def truck_create(request):
    """Create a new truck for normal carriers."""

    if request.method == "POST":
        form = TruckForm(request.POST)
        if form.is_valid():
            truck = form.save()
            messages.success(
                request, f"Truck '{truck.truck_number}' created successfully!"
            )
            return redirect("trucks_list")
    else:
        form = TruckForm()

    return render(request, "tms/truck_create.html", {"form": form})


@login_required
def active_loads(request):
    """List active loads assigned to the tracking agent"""
    # Only show loads assigned to this tracking agent
    loads = (
        Load.objects.filter(
            tracking_agent=request.user,
            status__in=[Load.Status.DISPATCHED, Load.Status.IN_TRANSIT],
        )
        .select_related("broker", "carrier", "truck", "driver")
        .prefetch_related("stops", "documents")
        .order_by("-created_at")
    )
    context = {"loads": loads}
    return render(request, "tms/active_loads.html", context)


@login_required
@require_load_lock
def create_tracking_update(request, load_id):
    """Create a tracking update for a load (tracking agents only)."""
    load = get_object_or_404(Load, load_id=load_id)

    if load.status not in [Load.Status.DISPATCHED, Load.Status.IN_TRANSIT]:
        messages.error(
            request,
            "Can only add tracking updates to loads that are Dispatched or In Transit.",
        )
        return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        form = TrackingUpdateForm(request.POST)
        if form.is_valid():
            tu = form.save(commit=False)
            tu.load = load
            tu.tracking_agent = request.user
            # If not delayed, clear delay_reason and new_eta
            if not tu.is_delayed:
                tu.delay_reason = ""
                # tu.new_eta = None
            tu.save()

            # set denormalized fields
            load.last_tracking_at = tu.created_at
            load.is_delayed = bool(tu.is_delayed)
            load.save()
            messages.success(request, "Tracking update added.")
            return redirect("load_detail", load_id=load.load_id)
    else:
        form = TrackingUpdateForm()

    return render(
        request,
        "tms/tracking_update_form.html",
        {"form": form, "load": load},
    )


@login_required
@require_load_lock
def create_reschedule_request(request, load_id):
    """
    Create a new reschedule request for a specific stop on a load.

    GET: Show blank form with stop dropdown
    POST: Save new reschedule request with original appointment snapshot from selected stop
    """
    load = get_object_or_404(Load, load_id=load_id)

    # if not has_any_role(request.user, "Dispatcher", "Tracker"):
    #     messages.error(request, "Not authorized to create reschedule requests.")
    #     return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        # Create instance with load and user pre-set for validation
        rr_instance = RescheduleRequest(load=load, created_by=request.user)
        form = RescheduleRequestForm(load, request.POST, instance=rr_instance)

        if form.is_valid():
            rr = form.save(commit=False)

            # Snapshot original appointment window from the selected stop
            stop = form.cleaned_data["stop"]
            rr.original_appt_start = stop.appt_start
            rr.original_appt_end = stop.appt_end

            rr.save()
            messages.success(
                request, f"Reschedule request created for {stop.facility.name}."
            )
            return redirect("load_detail", load_id=load.load_id)
    else:
        form = RescheduleRequestForm(load)

    return render(
        request,
        "tms/reschedule_request_form.html",
        {"form": form, "load": load, "edit_mode": False},
    )


@login_required
@require_load_lock
def edit_reschedule_approvals(request, load_id, request_id):
    """
    Edit an existing reschedule request.

    GET: Show form pre-filled with existing reschedule request data
    POST: Update reschedule request including approvals and appointment details
    """
    load = get_object_or_404(Load, load_id=load_id)
    rr = get_object_or_404(RescheduleRequest, id=request_id, load=load)

    if not has_any_role(request.user, "Dispatcher", "Tracker"):
        messages.error(request, "Not authorized to update reschedule requests.")
        return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        form = RescheduleRequestForm(load, request.POST, instance=rr)

        if form.is_valid():
            rr = form.save(commit=False)

            # Update original appointment snapshot from selected stop (in case stop changed)
            stop = form.cleaned_data["stop"]
            rr.original_appt_start = stop.appt_start
            rr.original_appt_end = stop.appt_end

            # capture old appointment times for comparison after save
            prev_start = stop.appt_start
            prev_end = stop.appt_end

            # Manual override for approval checkboxes (form may not capture unchecked state properly)
            rr.consignee_approved = bool(request.POST.get("consignee_approved"))
            rr.broker_approved = bool(request.POST.get("broker_approved"))
            rr.manager_approved = bool(request.POST.get("manager_approved"))

            rr.save()

            if rr.is_fully_approved:
                stop.appt_start = rr.requested_appt_start
                stop.appt_end = rr.requested_appt_end
                stop.appointment_type = "appt"
                stop.save()

                if prev_start != stop.appt_start or prev_end != stop.appt_end:
                    refresh_route_snapshot(load=load)

                messages.success(
                    request,
                    "Reschedule fully approved. Appointment updated on stop.",
                )
            else:
                messages.success(request, "Reschedule request updated.")

            return redirect("load_detail", load_id=load.load_id)
    else:
        # GET: Pre-fill form with existing reschedule request
        form = RescheduleRequestForm(load, instance=rr)

    return render(
        request,
        "tms/reschedule_request_form.html",
        {"form": form, "load": load, "edit_mode": True, "request_id": rr.id},
    )


# ============================================================================
# ACCESSORIAL VIEWS
# ============================================================================


@login_required
@require_load_lock
def create_accessorial(request, load_id):
    """
    Create accessorial charge for a load.
    """

    load = get_object_or_404(Load, load_id=load_id)

    # Check permissions
    if not has_any_role(request.user, "Dispatcher", "Tracker"):
        messages.error(request, "Not authorized to add charges.")
        return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        form = AccessorialForm(request.POST)

        if form.is_valid():
            accessorial = form.save(commit=False)
            accessorial.load = load
            accessorial.created_by = request.user
            accessorial.save()

            messages.success(request, "Charge added.")
            return redirect("load_detail", load_id=load.load_id)
        else:
            messages.error(request, "Please correct the errors below.")

    else:
        # GET: Show form page
        form = AccessorialForm()

    return render(
        request,
        "tms/accessorial_form.html",
        {"form": form, "load": load, "mode": "create"},
    )


@login_required
@require_load_lock
def edit_accessorial(request, load_id, pk):
    load = get_object_or_404(Load, load_id=load_id)
    accessorial = get_object_or_404(Accessorial, pk=pk, load=load)

    # Check permissions
    if not has_any_role(request.user, "Dispatcher", "Tracker"):
        messages.error(request, "Not authorized to edit charges.")
        return redirect("load_detail", load_id=load.load_id)
    if request.method == "POST":
        form = AccessorialForm(request.POST, instance=accessorial)

        if form.is_valid():
            form.save()
            messages.success(request, "Charge updated.")
            return redirect("load_detail", load_id=load.load_id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        # GET: Show form page
        form = AccessorialForm(instance=accessorial)

    return render(
        request,
        "tms/accessorial_form.html",
        {"form": form, "load": load, "mode": "edit", "charge": accessorial},
    )


@login_required
def accessorial_charge_type_fields(request):
    charge_type = request.GET.get("charge_type")
    charge_id = request.GET.get("charge_id")  # Optional, for edit forms

    accessorial = None
    if charge_id:
        accessorial = get_object_or_404(Accessorial, id=charge_id)

    return render(
        request,
        "tms/partials/accessorial_charge_type_fields.html",
        {
            "charge_type": charge_type,
            "charge": accessorial,
        },
    )


# DUTY LOG


@login_required
@require_load_lock
def create_duty_log_view(request, load_id):
    load = get_object_or_404(Load, load_id=load_id)

    driver = load.driver
    if not driver:
        messages.error(request, "Load has no assigned driver.")
        return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        form = DutyLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.driver = driver
            log.truck = load.truck
            log.created_by = request.user

            try:
                create_duty_log(log=log)
                messages.success(request, "Duty log created successfully.")
            except ValidationError as e:
                messages.error(request, f"Error creating duty log: {e.messages[0]}")

            return redirect("load_detail", load_id=load.load_id)
    else:
        form = DutyLogForm(initial={"start_time": timezone.now()})

    return render(
        request,
        "tms/duty_log_form.html",
        {"form": form, "load": load},
    )


@login_required
def driver_hos_summary(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)
    summary = HOSCalculator(driver).summary()

    # Format timedeltas to human-readable strings for template display
    def format_timedelta(td):
        if not td:
            return "0h 0m"
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m"

    # Convert timedeltas to formatted strings
    formatted_summary = {
        "driving_today": format_timedelta(summary.get("driving_today")),
        "driving_remaining": format_timedelta(summary.get("driving_remaining")),
        "cycle_remaining": format_timedelta(summary.get("cycle_remaining")),
        "break_required": summary.get("break_required", False),
        "warnings": summary.get("warnings", []),
    }

    return render(
        request,
        "tms/partials/driver_hos_summary.html",
        {
            "driver": driver,
            "summary": formatted_summary,
        },
    )


@login_required
def stop_edit(request, stop_id):
    stop = get_object_or_404(LoadStop, id=stop_id)
    load = stop.load

    if load.status not in {
        Load.Status.DISPATCHED,
        Load.Status.IN_TRANSIT,
    }:
        messages.error(request, "Load not in transit.")
        return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        form = StopEditForm(request.POST, stop=stop)

        if form.is_valid():
            arrival = form.cleaned_data.get("arrival_time")
            departure = form.cleaned_data.get("departure_time")

            if arrival:
                stop.arrived_at = arrival

            if departure:
                stop.departed_at = departure
                stop.status = LoadStop.StopStatus.COMPLETED

            stop.save(
                update_fields=["arrived_at", "departed_at", "status", "updated_at"]
            )
            messages.success(request, "Stop updated successfully.")
            return redirect("load_detail", load_id=load.load_id)

    else:
        form = StopEditForm(
            initial={
                "arrival_time": stop.arrived_at,
                "departure_time": stop.departed_at,
            },
            stop=stop,
        )

    return render(
        request,
        "tms/stop_form.html",
        {
            "form": form,
            "stop": stop,
            "load": load,
        },
    )


# HTMX endpoints
@login_required
def search_brokers(request):
    """Search brokers by name"""
    query = request.GET.get("q", "").strip()

    if not query:
        brokers = Broker.objects.none()
    else:
        brokers = Broker.objects.filter(name__icontains=query).only("id", "name")[:20]

    return render(request, "tms/partials/_broker_options.html", {"brokers": brokers})


@login_required
def search_facilities(request):
    """Search facility by name"""
    query = request.GET.get("q", "").strip()
    if not query:
        facilities = Facility.objects.none()
    else:
        facilities = Facility.objects.filter(name__icontains=query).only(
            "id", "name", "city"
        )[:20]

    return render(
        request, "tms/partials/_facility_options.html", {"facilities": facilities}
    )


# ENTITIES
@login_required
def facilities_list(request):
    # apply pagination

    facilities = Facility.objects.all().order_by("name")

    paginator = Paginator(facilities, 20)  # 20 facilities per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "tms/facilities_list.html",
        {"facilities": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
def brokers_list(request):
    # apply pagination

    brokers = Broker.objects.all().order_by("name")

    paginator = Paginator(brokers, 20)  # 20 brokers per page
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "tms/brokers_list.html",
        {"brokers": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
def facility_create(request):
    """Create a new facility."""

    if request.method == "POST":
        form = FacilityForm(request.POST)
        if form.is_valid():
            facility = form.save()
            messages.success(
                request, f"Facility '{facility.name}' created successfully!"
            )
            return redirect("facilities_list")  # Adjust to your URL name
    else:
        form = FacilityForm()

    return render(request, "tms/facility_create.html", {"form": form})


@login_required
def broker_create(request):
    """Create a new broker."""

    if request.method == "POST":
        form = BrokerForm(request.POST)
        if form.is_valid():
            broker = form.save()
            messages.success(request, f"Broker '{broker.name}' created successfully!")
            return redirect("brokers_list")
    else:
        form = BrokerForm()

    return render(request, "tms/broker_create.html", {"form": form})
