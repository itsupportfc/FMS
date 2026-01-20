from os import access
from webbrowser import get

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from tms.services.duty_logs import create_duty_log
from tms.services.hos import HOSCalculator

from .forms import (
    AccessorialForm,
    DocumentUploadForm,
    DutyLogForm,
    LoadForm,
    RescheduleRequestForm,
    TrackingUpdateForm,
)
from .models import (
    Accessorial,
    Carrier,
    Document,
    Driver,
    Load,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
)


@login_required
def dashboard(request):
    """Decide dashboard based on user role"""

    user = request.user

    if user.role == "dispatcher":
        dashboard_template = "dashboard/_dispatcher_dashboard.html"

        booked_loads = Load.objects.filter(status=Load.Status.BOOKED)

        dispatched_loads = Load.objects.filter(status=Load.Status.DISPATCHED)

        rc_missing_loads = booked_loads.exclude(documents__document_type="RC")

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
        active_loads = my_loads.filter(
            status__in=[Load.Status.DISPATCHED, Load.Status.IN_TRANSIT]
        ).select_related("broker", "carrier", "driver", "truck")

        # Loads awaiting transit start (handed over but not yet started)
        awaiting_start = my_loads.filter(status=Load.Status.DISPATCHED)

        # Loads currently in transit (need tracking updates)
        in_transit = my_loads.filter(status=Load.Status.IN_TRANSIT)

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
    # fallback
    # else:
    #     context = {
    #         "dashboard_template": "dashboard/_default_dashboard.html",
    #     }

    return render(request, "dashboard/dashboard.html", context)


@login_required
def create_load(request):
    """
    Create new freight load (dispatcher only).

    Workflow:
    1. GET: Show empty form
    2. POST: Validate + save → redirect to load_detail

    WHY login_required: Only authenticated users can create loads.
    Future: Add @role_required("dispatcher") decorator for stricter control.
    """

    # carrier = None

    if request.user.role != "dispatcher":
        messages.error(request, "Only dispatchers can create loads.")
        return redirect("dashboard")

    if request.method == "POST":
        form = LoadForm(request.POST)
        if form.is_valid():
            load = form.save(commit=False)
            load.dispatcher = request.user
            # Status defaults to BOOKED (set in model field default)
            # No need to set it explicitly here
            load.save()
            messages.success(request, f"Load {load.load_id} created successfully.")
            # Redirect to load detail page (PRG pattern: Post-Redirect-Get)
            # WHY: Prevents duplicate submissions if user refreshes page
            return redirect("load_detail", load_id=load.load_id)
    else:
        # GET request - show empty form
        form = LoadForm()

    # Render template with form
    # WHY: Same template for GET (empty form) and POST (form with errors)
    return render(request, "tms/create_load.html", {"form": form})


@login_required
def load_detail(request, load_id):
    """
    Display and edit load details.

    Single view for both:
    - GET: Display current load state + editable form
    - POST: Update load fields (not status - that's via change_status view)

    WHY single view: Reduces code duplication. Edit form looks identical
    to detail view, just with editable fields instead of readonly text.

    Template shows/hides sections based on:
    - user.role (dispatcher sees different buttons than tracker)
    - load.status (BOOKED shows handover button, IN_TRANSIT shows complete)
    - load.can_handover() (disable handover button until preconditions met)
    """
    # Get load or 404 if not found
    # WHY get_object_or_404: Better UX than generic 500 error
    load = get_object_or_404(Load, load_id=load_id)

    if request.method == "POST":
        # Update existing load with form data
        # WHY instance=load: Pre-populates form with current values
        # here also form's __init__ runs
        form = LoadForm(request.POST, instance=load)
        if form.is_valid():
            form.save()
            messages.success(request, "Load updated successfully.")
            # Redirect back to same page (PRG pattern)
            return redirect("load_detail", load_id=load.load_id)
    else:
        # GET request: Show form pre-filled with current load data
        # here also form's __init__ runs
        form = LoadForm(instance=load)

    # Document upload form (always shown, even on COMPLETED loads for audit)
    doc_form = DocumentUploadForm()

    # Get list of tracking agents for handover dropdown
    # WHY: Dispatcher selects who to handover load to
    tracking_agents = User.objects.filter(role="tracking_agent", is_active=True)

    # Get available actions for current user
    # WHY: Template uses this to show/hide action buttons
    available_actions = load.get_available_actions(request.user)

    # Related activity lists for sidebar/history panels
    tracking_updates = load.tracking_updates.all()  # type: ignore
    reschedule_requests = load.reschedule_requests.all()  # type: ignore

    return render(
        request,
        "tms/load_detail.html",
        {
            "load": load,
            "form": form,
            "doc_form": doc_form,
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

    WHY separate view: Document upload is a side action, not part of
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
            # WHY: Already done in Document.save() but explicit is better
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
# @require_POST
def change_status(request, load_id, action):
    """
    Handle status transition actions.

    Route different actions to appropriate model methods:
    - handover → load.handover_to_tracking()
    - start_transit → load.start_transit()
    - complete → load.complete_load()
    - cancel → load.cancel()

    WHY thin view: All business logic in model methods. View just:
    1. Gets load from database
    2. Calls appropriate model method
    3. Catches errors and shows messages
    4. Redirects back

    Error Handling:
    - Model methods raise ValueError if preconditions not met
    - View catches error and displays user-friendly message
    - User sees error, fixes issue, tries again

    This keeps validation logic in model (testable, reusable) while
    view handles HTTP concerns (request/response/redirect).
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
            load.handover_to_tracking(
                tracking_agent=tracking_agent, instructions=instructions
            )

            messages.success(
                request, f"Load handed over to {tracking_agent.get_full_name()},"
            )

        elif action == "start_transit":
            # No extra parameters needed
            load.start_transit()
            messages.success(request, "Load marked as In Transit")

        elif action == "complete":
            # Model validates required documents
            load.complete_load()
            messages.success(request, "Load marked as Complete.")

        elif action == "cancel":
            # get optional cancellation reason
            reason = request.POST.get("reason", "")

            # call cancel method ( auto-creates TONU charge)
            load.cancel(reason=reason)
            messages.warning(request, "Load cancelled. TONU charge created.")

        else:
            # Unknown action ( shouldn't happen if URLs are correct)
            messages.error(request, f"Unknown action: {action}")

    except ValueError as e:
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
    """List active loads for tracking"""
    loads = (
        Load.objects.filter(status__in=[Load.Status.DISPATCHED, Load.Status.IN_TRANSIT])
        .select_related("broker", "carrier", "truck", "driver")
        .order_by("-created_at")
    )
    context = {"loads": loads}
    # TODO: create loads_list.html
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
    Create a reschedule request. Prefills original_appointment from load.delivery_datetime
    and new_appointment from latest tracking update's new_eta when available.
    """
    load = get_object_or_404(Load, load_id=load_id)

    if request.user.role not in ["tracking_agent", "dispatcher"]:
        messages.error(request, "Not authorized to create reschedule requests.")
        return redirect("load_detail", load_id=load.load_id)

    # Prefill values
    latest_update = load.tracking_updates.first()  # type: ignore
    initial = {
        "original_appointment": load.delivery_datetime,
        "new_appointment": latest_update.new_eta if latest_update else None,
    }

    if request.method == "POST":
        form = RescheduleRequestForm(request.POST)
        if form.is_valid():
            rr = form.save(commit=False)
            rr.load = load
            rr.created_by = request.user
            rr.save()
            messages.success(request, "Reschedule request created.")
            return redirect("load_detail", load_id=load.load_id)
    else:
        form = RescheduleRequestForm(initial=initial)

    return render(
        request,
        "tms/reschedule_request_form.html",
        {"form": form, "load": load},
    )


@login_required
@require_POST
def update_reschedule_approvals(request, load_id, request_id):
    """
    Update approval checkboxes for a reschedule request. When all three are approved,
    the model save() will apply the new appointment to the load.
    """
    load = get_object_or_404(Load, load_id=load_id)
    rr = get_object_or_404(RescheduleRequest, id=request_id, load=load)

    if request.user.role not in ["dispatcher", "tracking_agent"]:
        messages.error(request, "Not authorized to update approvals.")
        return redirect("load_detail", load_id=load.load_id)

    # Update from POST checkboxes (present when checked)
    rr.consignee_approved = bool(request.POST.get("consignee_approved"))
    rr.broker_approved = bool(request.POST.get("broker_approved"))
    rr.manager_approved = bool(request.POST.get("manager_approved"))
    rr.save()

    if rr.is_fully_approved:
        messages.success(
            request,
            "Reschedule fully approved. Delivery appointment updated on the load.",
        )
    else:
        messages.info(request, "Reschedule approvals updated.")

    return redirect("load_detail", load_id=load.load_id)


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
