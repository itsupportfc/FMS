from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Manager
from django.utils import timezone

User = get_user_model()


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Broker(BaseModel):
    """Freight broker company."""

    # Identification
    name = models.CharField(max_length=200)
    mc_number = models.CharField(
        max_length=20, unique=True, help_text="Motor Carrier Number"
    )

    # Primary Contact Information
    primary_contact_name = models.CharField(
        max_length=100,
    )
    primary_phone = models.CharField(
        max_length=20,
    )
    primary_email = models.EmailField()

    # Notes
    notes = models.TextField(blank=True)

    # Status
    credit_history = models.TextField(blank=True, help_text="Credit history notes")
    average_payment_days = models.FloatField(
        null=True, blank=True, help_text="Average payment days"
    )

    def __str__(self):
        return self.name


class Facility(BaseModel):
    """Shipper or receiver location."""

    class FacilityType(models.TextChoices):
        SHIPPER = "shipper", "Shipper"
        RECEIVER = "receiver", "Receiver (Consignee)"
        # BOTH = "both", "Both (Shipper & Receiver)"

    # Identification
    name = models.CharField(max_length=200)
    facility_type = models.CharField(max_length=10, choices=FacilityType.choices)

    # Address
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, help_text="US state abbreviation")
    zip_code = models.CharField(max_length=10)

    # Contact
    contact_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)

    # Operational Info
    appointment_required = models.BooleanField(default=True)
    hours_of_operation = models.CharField(
        max_length=100, default="24/7", help_text="e.g., Mon-Fri 8am-5pm"
    )

    notes = models.TextField(
        blank=True, help_text="Special instructions, dock info, etc."
    )

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"


class Carrier(BaseModel):
    """Trucking company or owner-operator."""

    class CarrierType(models.TextChoices):
        COMPANY = "company", "Trucking Company"
        OWNER_OPERATOR = "owner_operator", "Owner-Operator"

    # Identification
    name = models.CharField(max_length=200)
    mc_number = models.CharField(
        max_length=20, unique=True, help_text="Motor Carrier Number"
    )
    dot_number = models.CharField(max_length=20, unique=True, help_text="USDOT Number")
    carrier_type = models.CharField(max_length=20, choices=CarrierType.choices)

    # Contact
    primary_contact_name = models.CharField(max_length=100)
    primary_phone = models.CharField(max_length=20)
    primary_email = models.EmailField()

    # Address
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)  # US state abbreviation
    zip_code = models.CharField(max_length=10)

    # Notes
    notes = models.TextField(blank=True)

    # Insurance Check
    carrier_has_insurance = models.BooleanField(
        default=True, help_text="Does this carrier have valid insurance?"
    )
    # insurance_expiry_date = models.DateField(null=True, blank=True)

    # Audit - who created this carrier
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="carriers_created"
    )

    def __str__(self):
        return self.name


class Truck(BaseModel):
    """
    Truck unit - combines tractor and trailer info for V1 MVP.
    In V1, we treat truck+trailer as a single unit since most operations
    use dry vans and reefers consistently.
    """

    class EquipmentType(models.TextChoices):
        DRY_VAN = "dry_van", "Dry Van"
        REEFER = "reefer", "Refrigerated (Reefer)"
        FLATBED = "flatbed", "Flatbed"
        STEP_DECK = "step_deck", "Step Deck"
        POWER_ONLY = "power_only", "Power Only"
        BOX_TRUCK = "box_truck", "Box Truck"
        OTHER = "other", "Other"

    class TruckStatus(models.TextChoices):
        """Current operational status - used for dispatcher dashboard."""

        AVAILABLE = "available", "Available (Empty)"
        ASSIGNED = "assigned", "Assigned to Load"
        OUT_OF_SERVICE = "out_of_service", "Out of Service"

    # Relationships
    carrier = models.ForeignKey(
        Carrier, on_delete=models.CASCADE, related_name="trucks"
    )

    # Identification
    truck_number = models.CharField(max_length=50, help_text="Internal fleet number")
    trailer_number = models.CharField(
        max_length=50, blank=True, help_text="Trailer number if applicable"
    )
    vin = models.CharField(
        max_length=17, blank=True, help_text="Vehicle Identification Number"
    )  # can be blank?
    license_plate = models.CharField(
        max_length=20, help_text="License plate number (required for road operations)"
    )

    # Equipment Type
    equipment_type = models.CharField(max_length=20, choices=EquipmentType.choices)
    length_feet = models.PositiveIntegerField(
        default=53, help_text="Trailer length (48 or 53)"
    )

    # Equipment Identification
    chassis_no = models.CharField(
        max_length=50,
        blank=True,
        help_text="Chassis/frame number (tractor unit identifier)",
    )

    # Current Status (for dispatcher dashboard - "empty trucks" view)
    current_status = models.CharField(
        max_length=20,
        choices=TruckStatus.choices,
        default=TruckStatus.AVAILABLE,
        help_text="Current operational status",
    )
    current_location_city = models.CharField(max_length=100, blank=True)
    current_location_state = models.CharField(max_length=2, blank=True)
    last_location_update = models.DateTimeField(null=True, blank=True)

    # Insurance Check
    truck_has_insurance = models.BooleanField(
        default=True, help_text="Does this truck have valid insurance?"
    )

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "truck_number"], name="unique_truck_per_carrier"
            )
        ]

    def __str__(self):
        return f"{self.truck_number} ({self.get_equipment_type_display()})"


class Driver(BaseModel):
    """Truck driver."""

    # Relationships
    carrier = models.ForeignKey(
        Carrier, on_delete=models.CASCADE, related_name="drivers"
    )

    # Personal Information
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)

    # License Information
    cdl_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Commercial Driver's License (required for operations)",
    )
    cdl_expiration = models.DateField(
        null=True, blank=True, help_text="CDL expiration date"
    )

    # HOS Configuration
    hos_cycle = models.CharField(
        max_length=10,
        choices=[("60_7", "60 hours/7 days"), ("70_8", "70 hours/8 days")],
        default="60_7",
    )

    # Current Assignment (denormalized for quick access)
    current_truck = models.ForeignKey(
        Truck,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_driver",
    )

    # Notes
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class CarrierDocument(BaseModel):
    """LoadDocument related to a Carrier."""

    # Override uploaded_by with unique related_name

    class DocumentType(models.TextChoices):
        W9 = "W9", "W9"
        INSURANCE_COI = "INSURANCE_COI", "Insurance (COI)"
        AUTHORITY = "AUTHORITY", "MC / Authority Letter"
        ACH = "ACH", "ACH / Banking Form"
        LOR = "LOR", "Letter of Reference"
        OTHER = "OTHER", "Other"

    carrier = models.ForeignKey(
        "Carrier", on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
    )

    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    original_filename = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = self.file.name
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "document_type"],
                name="unique_document_per_carrier_and_type",
            )
        ]


class LoadDocument(BaseModel):
    """LoadDocument related to a Load."""

    class DocumentType(models.TextChoices):
        RC = "RC", "Rate Confirmation"
        BOL = "BOL", "Bill of Lading"
        POD = "POD", "Proof of Delivery"
        DETENTION = "DETENTION", "Detention"
        LUMPER = "LUMPER", "Lumper"
        TONU = "TONU", "Truck Order Not Used"
        OTHER = "OTHER", "Other"

    # NEW: Define which types are ALWAYS required
    REQUIRED_FOR_COMPLETION = ["POD", "BOL"]  # Business rule in one place

    # Relationships
    load = models.ForeignKey("Load", on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
    )

    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    original_filename = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = self.file.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.load.load_id} - {self.document_type.label} ({self.original_filename})"


class Accessorial(BaseModel):
    """
    Canonical extra charge applied to a load.
    This table is the source of truth for:
    - money
    - approvals
    - reporting
    - accounting exports

    V1 Approval: Simple boolean toggles
    - Tracking agent manually obtains approval (phone/email)
    - Updates manager_approved and broker_approved booleans directly
    - No automated workflow - just manual updates
    """

    class ChargeType(models.TextChoices):
        DETENTION = "detention", "Detention"
        LAYOVER = "layover", "Layover"
        TONU = "tonu", "TONU"
        LUMPER = "lumper", "Lumper"
        OTHER = "other", "Other"

    # ---- Relationships ----
    load = models.ForeignKey(
        "Load",
        on_delete=models.CASCADE,
        related_name="accessorials",
    )

    # ---- Classification ----
    charge_type = models.CharField(
        max_length=20,
        choices=ChargeType.choices,
    )

    # ---- Money ----
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,  # Allow null for preliminary charges
        blank=True,
        help_text="Amount in USD. Leave blank for manager to calculate.",
    )

    description = models.TextField(blank=True)

    # ---- Approval Workflow (Simple Booleans) ----
    # Tracking agent updates these after obtaining verbal approval
    manager_approved = models.BooleanField(default=False)
    broker_approved = models.BooleanField(default=False)
    # broker_notified = models.BooleanField(default=False)

    # ---- Audit ----
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_accessorials",
    )

    # detention specific
    detention_start = models.DateTimeField(null=True, blank=True)
    detention_end = models.DateTimeField(null=True, blank=True)
    detention_billed_hours = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    # layover specific
    layover_start_date = models.DateField(null=True, blank=True)
    layover_end_date = models.DateField(null=True, blank=True)
    # tonu specific
    # lumper specific

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount < 0:
            raise ValidationError({"amount": "Amount cannot be negative."})

    @property
    def is_approved(self):
        """
        Core approval status: True if both manager and broker approved.

        WHY property not stored field: Avoids sync issues and redundancy.
        Single source of truth: manager_approved and broker_approved booleans.
        """
        return self.manager_approved and self.broker_approved

    def get_approval_status_display(self):
        """Returns 'APPROVED' or 'PENDING' for display in templates/exports."""
        return "APPROVED" if self.is_approved else "PENDING"

    def __str__(self):
        return f"{self.charge_type} {self.load.load_id}"


class LoadStop(BaseModel):
    """
    Individual stop on a multi-stop load route.
    """

    class StopType(models.TextChoices):
        PICKUP = "pickup", "Pickup"
        DELIVERY = "delivery", "Delivery"

    class StopStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        # ARRIVED = "arrived", "Arrived"
        # IN_PROGRESS = "in_progress", "Loading/Unloading"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"

    load = models.ForeignKey("Load", on_delete=models.CASCADE, related_name="stops")
    facility = models.ForeignKey(
        "Facility", on_delete=models.PROTECT, related_name="load_stops"
    )
    stop_type = models.CharField(
        max_length=10, choices=StopType.choices, help_text="Pickup or Delivery"
    )
    sequence = models.PositiveIntegerField(
        help_text="Route order: 1,2,3 ..(important for routing)"
    )

    # Appointment (Compatibility + Future)
    # appointment_datetime = models.DateTimeField(
    #     null=True,
    #     blank=True,
    #     help_text="(Legacy/compat) Single appointment datetime if not using a window",
    # )
    appt_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Appointment window start time (preferred for real ops)",
    )
    appt_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Appointment window end time (preferred for real ops)",
    )
    appointment_type = models.CharField(
        max_length=10,
        choices=[
            ("appt", "Appointment"),
            ("fcfs", "First Come First Serve"),
        ],
        default="appt",
    )

    status = models.CharField(
        max_length=20,
        choices=StopStatus.choices,
        default=StopStatus.PENDING,
    )

    arrived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When truck physically arrived at this stop",
    )
    departed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When truck physically departed this stop",
    )

    # Optional per-stop shipment identifiers / quantities (very common in multi-stop)
    reference_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="PO#, BOL#, Delivery#, etc. specific to this stop",
    )
    pieces = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Pieces/pallets for this stop only",
    )
    weight = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Weight for this stop only",
    )

    special_instructions = models.TextField(
        blank=True,
        help_text="Dock#, gate code, contact name, check-in process, etc.",
    )

    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["load", "sequence"], name="unique_stop_sequence"
            )
        ]

    def __str__(self):
        return (
            f"{self.load.load_id} - Stop {self.sequence}"
            f" ({self.get_stop_type_display()}: {self.facility.name})"
        )

    def clean(self):
        super().clean()
        # squence must start from 1
        if self.sequence and self.sequence < 1:
            raise ValidationError({"sequence": "Sequence must be 1 or greater."})
        # appt window
        if self.appt_start and self.appt_end:
            if self.appt_start > self.appt_end:
                raise ValidationError(
                    {"appt_end": "Appointment end must be after start time."}
                )
        # Arrival and Departure logic
        if self.arrived_at and self.departed_at:
            if self.arrived_at >= self.departed_at:
                raise ValidationError(
                    {"departed_at": "Departure time must be after arrival time."}
                )

        # If APPT, strongly recommended to have at least appt_start (V1 rule)
        if self.appointment_type == "appt":
            if not self.appt_start and not self.appt_end:
                raise ValidationError(
                    {
                        "appt_start": "For APPT stops, provide at least appt_start (or a window)."
                    }
                )

    @property
    def is_completed(self):
        return self.status == self.StopStatus.COMPLETED

    @property
    def is_skipped(self):
        return self.status == self.StopStatus.SKIPPED

    @property
    def duration_at_facility(self):
        """Duration truck spent at this stop (arrival to departure)."""
        if self.arrived_at and self.departed_at:
            return self.departed_at - self.arrived_at
        return None

    def mark_completed(self, departure_time=None):
        """
        V1 convenience. No state machine needed.
        """
        self.status = self.StopStatus.COMPLETED
        if departure_time:
            # if provided
            self.departed_at = departure_time
        elif self.arrived_at and not self.departed_at:
            # if already arrived, set departed_at to now
            self.departed_at = timezone.now()
        self.save(update_fields=["status", "departed_at", "updated_at"])

    def mark_skipped(self):
        """
        V1 convenience. No state machine needed.
        """
        self.status = self.StopStatus.SKIPPED
        self.save(update_fields=["status", "updated_at"])


class Load(BaseModel):
    """
    Freight load - the core business entity.
    Check for completeness before handover to tracking.
    """

    if TYPE_CHECKING:
        stops: Manager["LoadStop"]
        documents: Manager["LoadDocument"]

    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        DISPATCHED = "dispatched", "Dispatched"
        IN_TRANSIT = "in_transit", "In Transit"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentMethod(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage of Rate"
        FIXED = "fixed", "Fixed Amount"

    # Broker Load Reference
    load_id = models.CharField(
        max_length=50,
        help_text="Broker's load/reference number",
        unique=True,
        verbose_name="Broker Load ID",
    )

    # === COMMODITY INFO (Load-level) ===
    commodity_type = models.CharField(max_length=100, blank=True, null=True)
    weight = models.PositiveIntegerField(
        blank=True,
        null=True,
    )

    # Relationships
    broker = models.ForeignKey(Broker, on_delete=models.PROTECT, related_name="loads")
    carrier = models.ForeignKey(
        Carrier,
        on_delete=models.PROTECT,
        related_name="loads",
        null=True,
        blank=True,
        help_text="Assigned during dispatch",
    )
    truck = models.ForeignKey(
        Truck,
        on_delete=models.PROTECT,
        related_name="loads",
        null=True,
        blank=True,
        help_text="Assigned during dispatch",
    )
    driver = models.ForeignKey(
        Driver,
        on_delete=models.PROTECT,
        related_name="loads",
        null=True,
        blank=True,
        help_text="Assigned during dispatch",
    )

    # Pickup Information (address stored in Facility model)
    # pickup_facility = models.ForeignKey(
    #     Facility,
    #     on_delete=models.PROTECT,
    #     related_name="pickup_loads",
    #     help_text="Shipper location - contains address details",
    # )
    # # pickup_date = models.DateField()
    # pickup_datetime = models.DateTimeField(null=True, blank=True)
    # pickup_appointment_type = models.CharField(
    #     max_length=10,
    #     choices=[("appt", "Appointment"), ("fcfs", "First Come First Serve")],
    #     default="appt",
    #     blank=True,
    # )

    # # Delivery Information (address stored in Facility model)
    # delivery_facility = models.ForeignKey(
    #     Facility,
    #     on_delete=models.PROTECT,
    #     related_name="delivery_loads",
    #     help_text="Receiver/consignee location - contains address details",
    # )
    # delivery_datetime = models.DateTimeField(null=True, blank=True)
    # delivery_appointment_type = models.CharField(
    #     max_length=10,
    #     choices=[("appt", "Appointment"), ("fcfs", "First Come First Serve")],
    #     default="appt",
    #     blank=True,
    # )

    # Financial
    miles = models.PositiveIntegerField(
        help_text="Total loaded miles", blank=True, null=True
    )
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total rate in USD",
        blank=True,
        null=True,
    )
    rpm = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        editable=False,
        null=True,
        help_text="Rate Per Mile (auto-calculated)",
    )

    # Payment from Carrier
    commission_type = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.PERCENTAGE,
        help_text="How you receive payment from carrier",
        blank=True,
        null=True,
    )
    dispatcher_commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentage (e.g., 85.00 for 85%) or fixed amount in USD",
    )

    # Status
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOOKED
    )

    # Assignment
    dispatcher = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="dispatched_loads",
        help_text="Dispatcher who booked this load",
    )
    tracking_agent = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracked_loads",
        help_text="Tracking agent assigned after handover from dispatch",
    )

    # Milestone Timestamps (enter manually or auto set)
    dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When assigned to carrier/truck/driver",
    )
    # pickup_arrival_at = models.DateTimeField(
    #     null=True,
    #     blank=True,
    #     help_text="When truck arrived at pickup facility",
    # )
    # pickup_departure_at = models.DateTimeField(
    #     null=True,
    #     blank=True,
    #     help_text="When truck departed pickup facility",
    # )
    # delivery_arrival_at = models.DateTimeField(
    #     null=True,
    #     blank=True,
    #     help_text="When truck arrived at delivery facility",
    # )
    # delivery_departure_at = models.DateTimeField(
    #     null=True,
    #     blank=True,
    #     help_text="When truck departed delivery facility",
    # )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When delivery was completed",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When load was closed",
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When load was cancelled or TONU'd",
    )

    # Notes
    remarks = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        # Auto-calculate RPM
        if self.miles and self.rate and self.miles > 0:
            self.rpm = self.rate / self.miles
        else:
            self.rpm = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.load_id} - {self.Status(self.status).label}"

    # =========================================================================
    # MULTI-STOP CONVENIENCE PROPERTIES (expects LoadStop model to exist)
    # =========================================================================

    @property
    def first_pickup(self):
        return self.stops.filter(stop_type="pickup").order_by("sequence").first()

    @property
    def last_delivery(self):
        return self.stops.filter(stop_type="delivery").order_by("-sequence").first()

    @property
    def origin(self):
        first = self.first_pickup
        if first:
            return f"{first.facility.city}, {first.facility.state}"
        return None

    @property
    def destination(self):
        last = self.last_delivery
        if last:
            return f"{last.facility.city}, {last.facility.state}"
        return None

    def get_route_summary(self):
        stops = self.stops.order_by("sequence")
        if not stops.exists():
            return "No routes defined"
        locations = [f"{stop.facility.city}, {stop.facility.state}" for stop in stops]

        return " → ".join(locations)

    def get_total_stops_count(self):
        return self.stops.count()

    def get_completed_stops_count(self):
        return self.stops.filter(status=LoadStop.StopStatus.COMPLETED).count()

    def is_multi_stop(self):
        return self.get_total_stops_count() > 2

    # ============================================================================
    # STATUS WORKFLOW METHODS
    # ============================================================================
    # Design Pattern: State Machine with Guard Clauses
    # - Each transition method validates preconditions before changing state
    # - Uses @transaction.atomic to ensure database consistency
    # - Centralizes business logic in model (Django best practice)
    # ============================================================================

    def _transition(self, new_status, **extra_fields):
        """
        Internal helper to change load status safely.

        WHY: Centralizing status changes prevents bugs where status is set
        without updating related timestamps or fields. All status changes
        MUST go through transition methods, never direct assignment.

        Args:
            new_status: Target status from Load.Status choices
            **extra_fields: Additional fields to update (e.g., dispatched_at=timezone.now())
        """

        self.status = new_status

        # update additional fields passed like timestamps etc
        # my_dict.items() → key–value pairs
        for key, value in extra_fields.items():
            setattr(self, key, value)
        self.save()

        # TODO
        # Log status change in LoadHistory model (not implemented yet)

    # STATUS HELPERS
    def has_rate_confirmation(self):
        """
        Check if Rate Confirmation document is uploaded.

        WHY: RC document is required before handover to tracking.
        This is a business rule - loads can't be dispatched without broker approval.
        Separating this check makes it reusable and testable.
        """
        return self.documents.filter(
            document_type=LoadDocument.DocumentType.RC
        ).exists()

    def can_handover(self):
        """
        Check if load is ready for handover to tracking agent.

        WHY: Prevents UI from showing "Handover" button when preconditions aren't met.
        Used in template: {% if load.can_handover %}<button>Handover</button>{% endif %}

        V1 handover rules:
        - BOOKED
        - RC uploaded
        - carrier/truck/driver assigned
        - stops exist
        - for APPT stops: must have appt_start or appt_end
        """
        basic_checks = (
            self.status == self.Status.BOOKED
            and self.has_rate_confirmation()
            and self.carrier is not None
            and self.truck is not None
            and self.driver is not None
        )

        if not basic_checks:
            return False

        if not self.stops.exists():
            return False

        for stop in self.stops.all():
            if stop.appointment_type == "appt":
                if not (stop.appt_start or stop.appt_end):
                    return False

        return True

    def get_available_actions(self, user):
        """
        Return list of actions this user can perform on this load RIGHT
          NOW.

        WHY: Only showing relevant actions (not grayed-out buttons) creates
        cleaner UX and reduces cognitive load. Users see exactly what they
        can do at this moment based on load status.

        Returns: List of action strings like ["start_transit", "upload_document"]

        Usage in template:
            {% with actions=load.get_available_actions user %}
                {% if "start_transit" in actions %}
                    <button>Start Transit</button>
                {% endif %}
            {% endwith %}

        Design: Actions filtered by role AND current load status.
        Validation still happens in views for safety, but UI only shows
        actions that should succeed.
        """
        actions = []

        # Dispatcher actions
        if user.role == "dispatcher":
            # Can handover only when BOOKED and all preconditions met
            if self.status == self.Status.BOOKED and self.can_handover():
                actions.append("handover_to_tracking")

            # Can cancel anytime before completion
            if self.status not in [
                self.Status.COMPLETED,
                self.Status.DELIVERED,
                self.Status.CANCELLED,
            ]:
                actions.append("cancel_load")

            # Can reschedule anytime before completion
            if self.status not in [
                self.Status.COMPLETED,
                self.Status.CANCELLED,
                self.Status.DELIVERED,
            ]:
                actions.append("create_reschedule_request")

            # Can add accessorials anytime before completion
            if self.status not in [self.Status.COMPLETED, self.Status.CANCELLED]:
                actions.append("add_accessorial")

        # Tracking agent actions
        if user.role == "tracking_agent":
            # Can start transit only when dispatched
            if self.status == self.Status.DISPATCHED:
                actions.append("start_transit")

            # Can mark delivered only when in transit
            if self.status == self.Status.IN_TRANSIT:
                actions.append("mark_delivered")

            # Can complete only when delivered
            if self.status == self.Status.DELIVERED:
                actions.append("complete_load")

            # Can add tracking updates during active transit
            if self.status in [
                self.Status.DISPATCHED,
                self.Status.IN_TRANSIT,
                # self.Status.DELIVERED,
            ]:
                actions.append("add_tracking_update")

            # Can reschedule anytime before completion
            if self.status not in [
                self.Status.COMPLETED,
                self.Status.CANCELLED,
                self.Status.DELIVERED,
            ]:
                actions.append("create_reschedule_request")

            # Can add accessorials anytime before completion
            if self.status not in [self.Status.COMPLETED, self.Status.CANCELLED]:
                actions.append("add_accessorial")

        # COMMON ACTIONS FOR ALL ROLES

        # Can view driver HOS if driver is assigned
        if self.driver:
            actions.append("view_driver_hos")

        # Document upload available for all users, all statuses (including COMPLETED for audit)
        # WHY: May need to upload POD after completion, or detention receipts later
        actions.append("upload_document")

        return actions

    # ============================================================================
    # STATUS TRANSITION METHODS
    # ============================================================================
    # Pattern: Guard Clauses → State Change → Side Effects
    # Each method follows same structure:
    # 1. Validate current status
    # 2. Validate business rules (documents, assignments, etc.)
    # 3. Change status using _transition()
    # 4. Create side-effect records (Handover, Accessorial, etc.)
    # ============================================================================

    @transaction.atomic
    def handover_to_tracking(self, tracking_agent, instructions=""):
        """
        BOOKED -> DISPATCHED
        WHY: Marks when dispatcher hands responsibility to tracking agent.
        This is a critical workflow boundary - dispatcher books/assigns,
        tracker monitors/completes.

        Side Effects:
        - Sets dispatched_at timestamp (marks when handover occurred)
        - Assigns tracking_agent (who is now responsible)
        - Creates Handover record (audit trail of who handed to whom)

        @transaction.atomic WHY: If Handover record creation fails, we don't
        want Load stuck in DISPATCHED without audit record. All-or-nothing.

        Args:
            tracking_agent: User instance (must have role="tracking_agent")
            instructions: Optional special instructions for tracker

        Raises:
            ValueError: If preconditions not met (clear message for user)
        """

        # GUARD CLAUSES
        errors = []
        if self.status != self.Status.BOOKED:
            errors.append("Load is not in BOOKED status.")
        if not self.has_rate_confirmation():
            # WHY: Broker must confirm rate before we dispatch truck
            errors.append("Rate Confirmation document is missing.")
        if not self.carrier or not self.truck or not self.driver:
            errors.append("Carrier, Truck, and Driver must be assigned.")

        # require stops
        if not self.stops.exists():
            errors.append("At least 2 stops must be defined for the load.")

        # Validate APPT stops have appointment window
        if self.stops.exists():
            for stop in self.stops.all():
                if stop.appointment_type == "appt" and not (
                    stop.appt_start or stop.appt_end
                ):
                    errors.append(
                        "All APPT stops must have at least appt_start (or a window)."
                    )
                    break

        if errors:
            raise ValueError("Cannot handover load: " + "; ".join(errors))

        # if no errors -> TRANSITION
        self._transition(
            new_status=self.Status.DISPATCHED,
            tracking_agent=tracking_agent,
            dispatched_at=timezone.now(),
        )

        # create HANDOVER record/excel sheet equivalent
        # WHY: Immutable record of who handed what to whom, when
        Handover.objects.create(
            load=self,
            from_agent=self.dispatcher,
            to_agent=tracking_agent,
            special_instructions=instructions,
        )

    @transaction.atomic
    def start_transit(self):
        """
        Transition: DISPATCHED → IN_TRANSIT

        WHY: Marks when truck physically leaves pickup facility with cargo.
        This is important for:
        - ETA calculations (transit started, can estimate delivery)
        - Driver HOS tracking (on-duty driving time starts)
        - Milestone reporting to broker ("load picked up")

        Side Effects:
        - Sets pickup_departure_at timestamp (when truck left shipper)

        Note: pickup_arrival_at should be set separately (manual entry by tracker) => IF NEEDED
        WHY: Tracker logs arrival when driver calls/texts, but departure is when
        they actually start moving - that's when status changes.
        """
        # Guard clause
        if self.status != self.Status.DISPATCHED:
            raise ValueError("Load is not in DISPATCHED status.")

        # TODO: what extra things we can check?
        # 1. validate pickup_arrival_at is set?
        self._transition(
            new_status=self.Status.IN_TRANSIT,
        )

    @transaction.atomic
    def mark_delivered(self):
        """
        Transition: IN_TRANSIT → DELIVERED

        WHY: Marks load as physically delivered at destination.
        This confirms the truck has completed delivery but load is not yet
        PAID , the accounts team will now take over and create invoices and track payment.

        Validation:
        - Checks that all documents required for delivery exist
        - WHY: Can't mark delivered without POD (Proof of Delivery)

        Side Effects:
        - Sets delivered_at timestamp (when delivery physically completed)
        """

        # Guard clause
        if self.status != self.Status.IN_TRANSIT:
            raise ValueError("Load is not in IN_TRANSIT status.")

        # Multi-stop completion check (delivery stops must be completed or skipped)
        delivery_stops = self.stops.filter(stop_type=LoadStop.StopType.DELIVERY)
        if delivery_stops.exists():
            incomplete_stops = delivery_stops.exclude(
                status__in=[LoadStop.StopStatus.COMPLETED, LoadStop.StopStatus.SKIPPED]
            )
            if incomplete_stops.exists():
                raise ValueError(
                    "Cannot mark as delivered. All delivery stops must be completed or skipped."
                )

        # Check required documents (POD, BOL)
        missing_types = []
        for doc_type in LoadDocument.REQUIRED_FOR_COMPLETION:
            if not self.documents.filter(document_type=doc_type).exists():
                missing_types.append(LoadDocument.DocumentType(doc_type).label)
        if missing_types:
            raise ValueError(
                f"Cannot mark as delivered. These documents are missing: {', '.join(missing_types)}"
            )

        # TODO: Additional checks before marking delivered
        # 1. Accessorials approved?? here or in complete_load?
        self._transition(
            new_status=self.Status.DELIVERED,
            delivered_at=timezone.now(),
        )

    @transaction.atomic
    def complete_load(self):
        """
        Transition: DELIVERED → COMPLETED
        WHY: Marks load as fully completed and closed.
        This indicates all tracking, paperwork, and billing are done.

        BUT payment from carrier is still pending.
        """

        # Guard clause
        if self.status != self.Status.DELIVERED:
            raise ValueError("Load is not in DELIVERED status.")

        # TODO: Additional checks before final completion
        # 1. All accessorials approved?
        # 2. All detention/layover details finalized?
        # 3. Carrier payment confirmed?

        self._transition(
            new_status=self.Status.COMPLETED,
            completed_at=timezone.now(),
        )

    @transaction.atomic
    def cancel(self, reason=""):
        """
        Transition: (ANY except COMPLETED) → CANCELLED

        WHY: Loads can be cancelled at any stage before completion:
        - During booking: Broker cancelled the shipment
        - During dispatch: Carrier backed out
        - During transit: Truck breakdown, shipper closed, etc.

        Side Effects:
        - Sets cancelled_at timestamp
        - Auto-creates TONU (Truck Order Not Used) accessorial charge

        TONU Charge WHY: When load is cancelled, we may bill broker for
        calling a truck that didn't haul freight. Charge starts as PENDING
        so dispatcher/manager can set amount and get broker approval.

        Amount = 0 by default because TONU rates vary by situation:
        - Cancelled before pickup: Usually 0 or small fee
        - Cancelled at shipper: Higher fee (truck drove there)
        - Cancelled mid-transit: Negotiated with broker

        @transaction.atomic WHY: Status change + TONU creation must be atomic.
        Don't want load CANCELLED without corresponding charge record.
        """

        # Guard clause
        if self.status in [
            self.Status.CANCELLED,
            self.Status.COMPLETED,
            self.Status.DELIVERED,
        ]:
            raise ValueError("Load is already CANCELLED, DELIVERED or COMPLETED.")

        self._transition(
            new_status=self.Status.CANCELLED,
            cancelled_at=timezone.now(),
        )

        # Auto-create TONU accessorial charge (initially pending via boolean approvals)
        tonu = Accessorial.objects.create(
            load=self,
            charge_type=Accessorial.ChargeType.TONU,
            amount=0.00,  # will be set during approval
            description=f"TONU charge - Load cancelled at {self.Status(self.status).label}",
            created_by=self.dispatcher,
        )
        # Free up truck status
        if self.truck:
            self.truck.current_status = Truck.TruckStatus.AVAILABLE
            self.truck.save(update_fields=["current_status"])


class RescheduleRequest(BaseModel):
    """
    Scheduling Log Sheet equivalent
    """

    class RescheduleReason(models.TextChoices):
        SHIPPER_DELAY = "shipper_delay", "Shipper - Facility Not Ready"
        RECEIVER_DELAY = "receiver_delay", "Receiver - Facility Full/Busy"
        DRIVER_HOS = "driver_hos", "Driver - Out of Hours (HOS)"
        MECHANICAL = "mechanical", "Driver - Mechanical Breakdown"
        WEATHER = "weather", "Environmental - Weather/Road Closure"
        TRAFFIC = "traffic", "Environmental - Heavy Traffic/Accident"
        BROKER_REQ = "broker_req", "Broker - Requested Change"
        DOC_ERROR = "doc_error", "Administrative - Rate Con/Paperwork Error"
        MISSED_APPT = "missed_appt", "Operational - Driver Missed Appointment"

    # Relationships
    load = models.ForeignKey(
        Load, on_delete=models.CASCADE, related_name="reschedule_requests"
    )
    # reschedule will be for a specific stop
    stop = models.ForeignKey(
        "LoadStop",
        on_delete=models.PROTECT,
        related_name="reschedule_requests",
        help_text="The specific stop for which the reschedule is requested",
    )
    original_appointment = models.DateTimeField(
        verbose_name="Original Appointment"
    )  # allow it to be blank??

    # Requested New Schedule
    new_appointment = models.DateTimeField(
        verbose_name="New Appointment"
    )  # allow it to be blank??

    reason = models.CharField(
        max_length=20,
        choices=RescheduleReason.choices,
        help_text="Why is rescheduling needed?",
    )

    consignee_approved = models.BooleanField(
        default=False,
        help_text="Has consignee approved? Write contact Details in notes.",
    )

    # Broker Approval
    broker_approved = models.BooleanField(
        default=False,
        help_text="Has broker approved?",
    )

    # Manager Approval (internal)
    manager_approved = models.BooleanField(
        default=False,
        help_text="Has internal manager approved?",
    )

    # Notes
    remarks = models.TextField(blank=True, help_text="Write all details here")

    # Audit
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_reschedules",
        help_text="Tracking agent who initiated reschedule",
    )

    class Meta:
        ordering = ["-created_at"]  # Show newest requests first

    def clean(self):
        super().clean()
        if self.stop and self.load and self.stop.load.load_id != self.load.load_id:
            raise ValidationError(
                {"stop": "The selected stop does not belong to the specified load."}
            )
        if self.original_appointment and self.new_appointment:
            if self.new_appointment <= self.original_appointment:
                raise ValidationError(
                    {
                        "new_appointment": "New appointment must be after the original appointment."
                    }
                )

    @property
    def is_fully_approved(self):
        """Check if all approvals are complete."""
        return (
            self.consignee_approved and self.broker_approved and self.manager_approved
        )

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.is_fully_approved:
            self.stop.appt_start = self.new_appointment
            self.stop.save(update_fields=["appt_start", "updated_at"])

        super().save(*args, **kwargs)


class DutyLog(BaseModel):
    """
    Driver duty status log (manual HOS tracking).

    Tracking agents manually enter duty status based on driver check-ins.
    Duration is auto-calculated when end_time is set.
    """

    class DutyStatus(models.TextChoices):
        OFF_DUTY = "off_duty", "Off Duty"
        SLEEPER_BERTH = "sleeper_berth", "Sleeper Berth"
        DRIVING = "driving", "Driving"
        ON_DUTY_NOT_DRIVING = "on_duty_not_driving", "On Duty (Not Driving)"
        # Additional statuses for better tracking
        YARD_MOVE = "yard_move", "Yard Move"
        PERSONAL_CONVEYANCE = "personal", "Personal Conveyance"

    # Relationships
    driver = models.ForeignKey(
        Driver, on_delete=models.PROTECT, related_name="duty_logs"
    )
    truck = models.ForeignKey(
        Truck, on_delete=models.PROTECT, null=True, blank=True, related_name="duty_logs"
    )
    load = models.ForeignKey(
        Load,
        on_delete=models.PROTECT,
        related_name="duty_logs",
        null=True,
        blank=True,
    )

    # Duty Entry
    status = models.CharField(max_length=25, choices=DutyStatus.choices)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    # duration = models.DurationField(
    #     null=True, blank=True, help_text="Auto-calculated from start/end times"
    # )

    # Location
    current_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Freeform location (e.g., 'I-80 exit 42, IA')",
    )

    # Notes
    remarks = models.TextField(blank=True)

    # Audit
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_duty_logs"
    )

    def clean(self):
        if self.end_time and self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time")

    @property
    def duration(self):
        if not self.end_time:
            return None
        return self.end_time - self.start_time


class TrackingUpdate(BaseModel):
    """Tracking and Tracing sheet Equivalent."""

    class RescheduleReason(models.TextChoices):
        SHIPPER_DELAY = "shipper_delay", "Shipper - Facility Not Ready"
        RECEIVER_DELAY = "receiver_delay", "Receiver - Facility Full/Busy"
        DRIVER_HOS = "driver_hos", "Driver - Out of Hours (HOS)"
        MECHANICAL = "mechanical", "Driver - Mechanical Breakdown"
        WEATHER = "weather", "Environmental - Weather/Road Closure"
        TRAFFIC = "traffic", "Environmental - Heavy Traffic/Accident"
        BROKER_REQ = "broker_req", "Broker - Requested Change"
        DOC_ERROR = "doc_error", "Administrative - Rate Con/Paperwork Error"
        MISSED_APPT = "missed_appt", "Operational - Driver Missed Appointment"

    class TrackingMethod(models.TextChoices):
        PHONE = "phone", "Phone Call"
        TEXT = "text", "Text Message"
        EMAIL = "email", "Email"

    # Relationships
    load = models.ForeignKey(
        Load, on_delete=models.CASCADE, related_name="tracking_updates"
    )
    tracking_agent = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="tracking_updates",
        help_text="Tracking agent who reported this update (immutable audit)",
    )

    # Location
    current_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Current location description (e.g., 'I-80 exit 42')",
    )

    # Tracking Method
    tracking_method = models.CharField(max_length=20, choices=TrackingMethod.choices)

    # Issues
    is_delayed = models.BooleanField(default=False)
    delay_reason = models.CharField(
        max_length=20, choices=RescheduleReason.choices, blank=True
    )

    new_eta = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Proposed New ETA",
        help_text="If delayed, enter new estimated delivery time",
    )
    # Notes
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.load.load_id} - {self.current_location} "

    class Meta:
        ordering = ["-created_at"]  # Show newest updates first


class Handover(BaseModel):
    """
    Handover Log excel sheet equivalent.
    """

    # Relationships
    load = models.ForeignKey(Load, on_delete=models.CASCADE, related_name="handovers")
    from_agent = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="handovers_from",
        help_text="Dispatcher who handed over (immutable audit)",
    )
    to_agent = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="handovers_to",
        help_text="Tracking agent assigned to load",
    )

    # Handover Details
    special_instructions = models.TextField(blank=True)

    # Notes
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"{self.load.load_id} → {self.to_agent.username if self.to_agent else 'Unassigned'} @ {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    def save(self, *args, **kwargs):
        """
        On handover creation, automatically assign tracking agent to load.
        V1 MVP: No acceptance step needed.
        """
        super().save(*args, **kwargs)
        # Auto-update load's tracking_agent
        if self.to_agent and self.load:
            self.load.tracking_agent = self.to_agent
            self.load.save(update_fields=["tracking_agent"])
