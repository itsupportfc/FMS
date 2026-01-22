from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

User = get_user_model()


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

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
        return f"{self.truck_number} ({self.get_equipment_type_display()})"  # type: ignore


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
    # cdl_state = models.CharField(
    #     max_length=2, blank=True, help_text="State of CDL issuance"
    # )
    # cdl_expiration = models.DateField(
    #     null=True, blank=True, help_text="CDL expiration date"
    # )

    # HOS Configuration
    hos_cycle = models.CharField(
        max_length=10,
        choices=[("60_7", "60 hours/7 days"), ("70_8", "70 hours/8 days")],
        default="60_7",
    )
    is_short_haul_exempt = models.BooleanField(
        default=False, help_text="150 air-mile short-haul exemption"
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


class Document(BaseModel):
    """Uploaded document."""

    DOCUMENT_TYPE_CHOICES = [
        ("RC", "Rate Confirmation"),
        ("BOL", "Bill of Lading"),
        ("POD", "Proof of Delivery"),
        ("DETENTION", "Detention"),
        ("LUMPER", "Lumper"),
        ("TONU", "Truck Order Not Used"),
        ("OTHERS", "Others"),
    ]

    # NEW: Define which types are ALWAYS required
    REQUIRED_FOR_COMPLETION = ["POD", "BOL"]  # Business rule in one place

    # Relationships
    load = models.ForeignKey("Load", on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default="OTHERS",
    )

    # File
    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    original_filename = models.CharField(max_length=255)

    # Metadata
    description = models.TextField(blank=True)

    # is_required_for_completion = models.BooleanField(
    #     default=False, help_text="Document required to mark load as complete"
    # )

    def save(self, *args, **kwargs):
        """Auto-populate original_filename from uploaded file if not set."""
        if self.file and not self.original_filename:
            self.original_filename = self.file.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.load.load_id} - {self.get_document_type_display()} ({self.original_filename})"  # type: ignore


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


class Load(BaseModel):
    """
    Freight load - the core business entity.
    Check for completeness before handover to tracking.
    """

    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        DISPATCHED = "dispatched", "Dispatched"
        # AT_PICKUP = "at_pickup", "At Pickup"
        IN_TRANSIT = "in_transit", "In Transit"
        # AT_DELIVERY = "at_delivery", "At Delivery"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        # TONU = "tonu", "TONU (Truck Ordered Not Used)"

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
    pickup_facility = models.ForeignKey(
        Facility,
        on_delete=models.PROTECT,
        related_name="pickup_loads",
        help_text="Shipper location - contains address details",
    )
    # pickup_date = models.DateField()
    pickup_datetime = models.DateTimeField(null=True, blank=True)
    pickup_appointment_type = models.CharField(
        max_length=10,
        choices=[("appt", "Appointment"), ("fcfs", "First Come First Serve")],
        default="appt",
        blank=True,
    )

    # Delivery Information (address stored in Facility model)
    delivery_facility = models.ForeignKey(
        Facility,
        on_delete=models.PROTECT,
        related_name="delivery_loads",
        help_text="Receiver/consignee location - contains address details",
    )
    delivery_datetime = models.DateTimeField(null=True, blank=True)
    delivery_appointment_type = models.CharField(
        max_length=10,
        choices=[("appt", "Appointment"), ("fcfs", "First Come First Serve")],
        default="appt",
        blank=True,
    )

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
    pickup_arrival_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When truck arrived at pickup facility",
    )
    pickup_departure_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When truck departed pickup facility",
    )
    delivery_arrival_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When truck arrived at delivery facility",
    )
    delivery_departure_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When truck departed delivery facility",
    )
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
        return f"{self.load_id} - {self.get_status_display()}"  # type: ignore

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
        return self.documents.filter(document_type="RC").exists()

    def can_handover(self):
        """
        Check if load is ready for handover to tracking agent.

        WHY: Prevents UI from showing "Handover" button when preconditions aren't met.
        Used in template: {% if load.can_handover %}<button>Handover</button>{% endif %}

        Business Rules:
        - Must be in BOOKED status (not already dispatched)
        - Must have RC document (broker confirmed the rate)
        - Must have carrier/truck/driver assigned (physical assets ready)
        """
        return (
            self.status == self.Status.BOOKED
            and self.has_rate_confirmation()
            and self.carrier is not None
            and self.truck is not None
            and self.driver is not None
        )

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
            pickup_departure_at=timezone.now(),
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

        # Check required documents (POD, BOL)
        missing_types = []
        for doc_type in Document.REQUIRED_FOR_COMPLETION:
            if not self.documents.filter(document_type=doc_type).exists():
                missing_types.append(
                    dict(Document.DOCUMENT_TYPE_CHOICES).get(doc_type, doc_type)
                )
        if missing_types:
            raise ValueError(
                f"Cannot mark as delivered. These documents are missing: {', '.join(missing_types)}"
            )

        # TODO: Additional checks before marking delivered
        # 1. delivery_arrival_at is set? => ??
        # 2. Accessorials approved?? here or in complete_load?
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

    @property
    def is_fully_approved(self):
        """Check if all approvals are complete."""
        return (
            self.consignee_approved and self.broker_approved and self.manager_approved
        )

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.is_fully_approved:
            self.load.delivery_datetime = self.new_appointment
            self.load.save(update_fields=["delivery_datetime"])

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
