from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from tms.policies.load_actions import get_available_actions
from tms.services.cancel import cancel_load
from tms.services.completion import complete_load
from tms.services.delivery import mark_delivered
from tms.services.duty_logs import create_duty_log
from tms.services.exceptions import ServiceError
from tms.services.handover import handover_to_tracking
from tms.services.hos import HOSCalculator
from tms.services.load_creation import create_load_with_stops
from tms.services.transit import start_transit

from .forms import (
    AccessorialForm,
    DocumentUploadForm,
    DutyLogForm,
    LoadForm,
    LoadStopForm,
    LoadStopFormSet,
    RescheduleRequestForm,
    TrackingUpdateForm,
)
from .models import (
    Accessorial,
    Broker,
    Carrier,
    Driver,
    Facility,
    Load,
    LoadDocument,
    LoadStop,
    RescheduleRequest,
    Truck,
)


@login_required
def dashboard(request):
    """Decide dashboard based on user role"""

    user = request.user

    if user.role == "dispatcher":
        dashboard_template = "dashboard/_dispatcher_dashboard.html"

        booked_loads = (
            Load.objects.filter(status=Load.Status.BOOKED)
            .select_related("broker", "carrier", "driver", "truck")
            .prefetch_related("stops", "documents")
        )

        dispatched_loads = (
            Load.objects.filter(status=Load.Status.DISPATCHED)
            .select_related("broker", "carrier", "driver", "truck")
            .prefetch_related("stops", "documents")
        )

        rc_missing_loads = booked_loads.exclude(
            documents__document_type=LoadDocument.DocumentType.RC
        )

        context = {
            "dashboard_template": dashboard_template,
            # KPI numbers
            "booked_count": booked_loads.count(),
            "dispatched_count": dispatched_loads.count(),
            "handover_pending_count": dispatched_loads.count(),
            "rc_missing_count": rc_missing_loads.count(),
            # Tables
            "booked_loads": booked_loads[:10],
            "handover_loads": dispatched_loads[:10],
        }
    elif user.role == "tracking_agent":
        dashboard_template = "dashboard/_tracker_dashboard.html"

        # Get loads assigned to this tracking agent
        # WHY: Tracker only sees loads they're responsible for
        my_loads = Load.objects.filter(tracking_agent=user)

        # Active loads (in transit or dispatched, not completed/cancelled)
        active_loads = (
            my_loads.filter(status__in=[Load.Status.DISPATCHED, Load.Status.IN_TRANSIT])
            .select_related("broker", "carrier", "driver", "truck")
            .prefetch_related("stops", "documents")
        )

        # Loads awaiting transit start (handed over but not yet started)
        awaiting_start = (
            my_loads.filter(status=Load.Status.DISPATCHED)
            .select_related("broker", "carrier", "driver", "truck")
            .prefetch_related("stops", "documents")
        )

        # Loads currently in transit (need tracking updates)
        in_transit = my_loads.filter(status=Load.Status.IN_TRANSIT).prefetch_related(
            "stops"
        )

        context = {
            "dashboard_template": dashboard_template,
            # KPI numbers
            "active_count": active_loads.count(),
            "awaiting_start_count": awaiting_start.count(),
            "in_transit_count": in_transit.count(),
            # Tables
            "awaiting_start_loads": awaiting_start[:10],
            "in_transit_loads": in_transit[:10],
        }

    return render(request, "dashboard/dashboard.html", context)


def _validate_stops_formset(stop_formset):
    """
    V1 sanity checks *before saving*:
    - at least 2 non-deleted stops
    - at least one pickup and one delivery
    """
    errors = []
    valid_forms = []
    for f in stop_formset.forms:
        if not hasattr(f, "cleaned_data"):
            continue  # skip invalid forms
        cd = f.cleaned_data
        if not cd:
            continue
        if cd.get("DELETE"):
            continue  # skip deleted forms
        # ignore completely empty extra forms
        if (
            not cd.get("facility")
            and not cd.get("stop_type")
            and not cd.get("sequence")
        ):
            continue
        valid_forms.append(cd)

    if len(valid_forms) < 2:
        errors.append("At least 2 stops (Pickup and Delivery) are required.")

    has_pickup = any(
        cd.get("stop_type") == LoadStop.StopType.PICKUP for cd in valid_forms
    )
    has_delivery = any(
        cd.get("stop_type") == LoadStop.StopType.DELIVERY for cd in valid_forms
    )

    if not has_pickup:
        errors.append("At least one PICKUP stop is required.")
    if not has_delivery:
        errors.append("At least one DELIVERY stop is required.")

    return errors


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

    if request.user.role != "dispatcher":
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
    if request.user.role != "dispatcher":
        return HttpResponse("", status=403)

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
    # Get load or 404 if not found
    # WHY get_object_or_404: Better UX than generic 500 error
    load = get_object_or_404(Load, load_id=load_id)

    if request.method == "POST":
        # Update existing load with form data
        # WHY instance=load: Pre-populates form with current values
        # WHY user=request.user: Form needs user for permission checks
        form = LoadForm(request.POST, instance=load, user=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, "Load updated successfully.")
            # Redirect back to same page (PRG pattern)
            return redirect("load_detail", load_id=load.load_id)
    else:
        # GET request: Show form pre-filled with current load data
        form = LoadForm(instance=load, user=request.user)

    # LoadDocument upload form (always shown, even on COMPLETED loads for audit)
    doc_form = DocumentUploadForm()

    # Get list of tracking agents for handover dropdown
    # WHY: Dispatcher selects who to handover load to
    tracking_agents = User.objects.filter(role="tracking_agent", is_active=True)

    # Get available actions for current user
    # WHY: Template uses this to show/hide action buttons
    available_actions = get_available_actions(request.user, load)

    # Related activity lists for sidebar/history panels
    tracking_updates = load.tracking_updates.all()
    reschedule_requests = load.reschedule_requests.all()

    # For read-only display
    stops = load.stops.order_by("sequence")

    return render(
        request,
        "tms/load_detail.html",
        {
            "load": load,
            "form": form,
            "doc_form": doc_form,
            "stops": stops,
            "tracking_agents": tracking_agents,
            "available_actions": available_actions,
            "tracking_updates": tracking_updates,
            "reschedule_requests": reschedule_requests,
        },
    )


@login_required
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
            messages.warning(request, "Load cancelled. TONU charge created.")

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

    drivers = (
        Driver.objects.filter(carrier_id=carrier_id)
        if carrier_id
        else Driver.objects.none()
    )
    trucks = (
        Truck.objects.filter(carrier_id=carrier_id)
        if carrier_id
        else Truck.objects.none()
    )

    return render(
        request,
        "tms/partials/carrier_assets.html",
        {
            "drivers": drivers,
            "trucks": trucks,
        },
    )


@login_required
def loads_list(request):
    """List all loads"""
    loads = Load.objects.select_related(
        "broker", "carrier", "truck", "driver"
    ).order_by("-created_at")
    context = {"loads": loads}
    # TODO: create loads_list.html
    return render(request, "tms/loads_list.html", context)


@login_required
def carriers_list(request):
    """List all carriers"""
    carriers = Carrier.objects.prefetch_related("trucks", "drivers").order_by("name")
    context = {"carriers": carriers}
    # TODO: create loads_list.html
    return render(request, "tms/carriers_list.html", context)


@login_required
def drivers_list(request):
    """List all drivers"""
    drivers = Driver.objects.select_related("carrier", "current_truck").order_by(
        "last_name", "first_name"
    )
    context = {"drivers": drivers}
    # TODO: create loads_list.html
    return render(request, "tms/drivers_list.html", context)


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
def create_tracking_update(request, load_id):
    """Create a tracking update for a load (tracking agents only)."""
    load = get_object_or_404(Load, load_id=load_id)

    if request.user.role != "tracking_agent":
        messages.error(request, "Only tracking agents can add tracking updates.")
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
                tu.new_eta = None
            tu.save()
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
def create_reschedule_request(request, load_id):
    """
    Create a new reschedule request for a specific stop on a load.

    GET: Show blank form with stop dropdown
    POST: Save new reschedule request with original appointment snapshot from selected stop
    """
    load = get_object_or_404(Load, load_id=load_id)

    if request.user.role not in ["tracking_agent", "dispatcher"]:
        messages.error(request, "Not authorized to create reschedule requests.")
        return redirect("load_detail", load_id=load.load_id)

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
def edit_reschedule_approvals(request, load_id, request_id):
    """
    Edit an existing reschedule request.

    GET: Show form pre-filled with existing reschedule request data
    POST: Update reschedule request including approvals and appointment details
    """
    load = get_object_or_404(Load, load_id=load_id)
    rr = get_object_or_404(RescheduleRequest, id=request_id, load=load)

    if request.user.role not in ["dispatcher", "tracking_agent"]:
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

            # Manual override for approval checkboxes (form may not capture unchecked state properly)
            rr.consignee_approved = bool(request.POST.get("consignee_approved"))
            rr.broker_approved = bool(request.POST.get("broker_approved"))
            rr.manager_approved = bool(request.POST.get("manager_approved"))

            rr.save()

            if rr.is_fully_approved:
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
def create_accessorial(request, load_id):
    """
    Create accessorial charge for a load.
    """

    load = get_object_or_404(Load, load_id=load_id)

    # Check permissions
    if request.user.role not in ["dispatcher", "tracking_agent"]:
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
def edit_accessorial(request, load_id, pk):
    load = get_object_or_404(Load, load_id=load_id)
    accessorial = get_object_or_404(Accessorial, pk=pk, load=load)

    # Check permissions
    if request.user.role not in ["dispatcher", "tracking_agent"]:
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
def create_duty_log_view(request, load_id):
    load = get_object_or_404(Load, load_id=load_id)

    if request.user.role != "tracking_agent":
        messages.error(request, "Only tracking agents can add duty logs.")
        return redirect("load_detail", load_id=load.load_id)

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


# ============================================================================
# STOP TRACKING ACTIONS (V1)
# ============================================================================


@login_required
def stop_edit(request, stop_id):
    """
    Edit a LoadStop - check in, complete, or skip.
    GET: Show form pre-filled with current stop data
    POST: Save changes and redirect back to load_detail
    """
    stop = get_object_or_404(LoadStop, id=stop_id)
    load = stop.load

    # Simple permission check
    if request.user.role != "tracking_agent":
        return redirect("dashboard")

    if load.status not in [Load.Status.DISPATCHED, Load.Status.IN_TRANSIT]:
        messages.error(request, "Load not in transit")
        return redirect("load_detail", load_id=load.load_id)

    if request.method == "POST":
        action = request.POST.get("action")  # check_in, complete, or skip

        if action == "check_in":
            arrival_time_str = request.POST.get("arrival_time")
            if arrival_time_str:
                from django.utils.dateparse import parse_datetime

                arrival_time = parse_datetime(arrival_time_str)
                if arrival_time:
                    stop.check_in(arrival_time=arrival_time)
                    messages.success(
                        request,
                        f"Checked in at {stop.facility.name}",
                    )
                else:
                    messages.error(request, "Invalid arrival time format")
            else:
                stop.check_in()
                messages.success(request, f"Checked in at {stop.facility.name}")

        elif action == "complete":
            departure_time_str = request.POST.get("departure_time")
            if departure_time_str:
                from django.utils.dateparse import parse_datetime

                departure_time = parse_datetime(departure_time_str)
                if departure_time:
                    stop.mark_completed(departure_time=departure_time)
                    messages.success(
                        request,
                        f"Completed stop at {stop.facility.name}",
                    )
                else:
                    messages.error(request, "Invalid departure time format")
            else:
                stop.mark_completed()
                messages.success(request, f"Completed stop at {stop.facility.name}")

        elif action == "skip":
            stop.mark_skipped()
            messages.success(request, f"Skipped stop at {stop.facility.name}")

        return redirect("load_detail", load_id=load.load_id)

    # GET: Show form
    from django.utils import timezone

    context = {
        "stop": stop,
        "load": load,
        "current_time": timezone.now().strftime("%Y-%m-%dT%H:%M"),
    }
    return render(request, "tms/stop_form.html", context)


# HTMX endpoints
def search_brokers(request):
    """Search brokers by name"""
    query = request.GET.get("q", "").strip()
    print(f"Search query: {query}")

    if not query:
        brokers = Broker.objects.none()
    else:
        brokers = Broker.objects.filter(name__icontains=query).only("id", "name")[:20]

    print(brokers)

    return render(request, "tms/partials/_broker_options.html", {"brokers": brokers})


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
