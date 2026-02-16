import os
from operator import index
from tabnanny import verbose
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Manager, Prefetch, Q
from django.utils import timezone

User = get_user_model()


# ============================================================================
# CUSTOM QUERYSETS & MANAGERS
# ============================================================================
class LoadQuerySet(models.QuerySet):
    """Industry pattern: keep query optimizations in one place."""

    def for_list_display(self):
        """
        Optimized for loads_list view.
        - select_related for FK labels
        - only() to restrict columns (big win on wide tables)
        - uses denormalized pickup/delivery fields (no stops prefetch)
        """
        return self.select_related("broker", "carrier", "truck", "driver").only(
            "id",
            "load_id",
            "status",
            "created_at",
            # denormalized route snapshot fields
            "origin_city",
            "origin_state",
            "origin_appt_start",
            "origin_appt_end",
            "destination_city",
            "destination_state",
            "destination_appt_start",
            "destination_appt_end",
            # related label fields
            "broker__id",
            "broker__name",
            "carrier__id",
            "carrier__name",
            "truck__id",
            "truck__truck_number",
            "driver__id",
            "driver__first_name",
            "driver__last_name",
        )

    def for_detail_display(self):
        """
        Optimized for load_detail view.
        Prefetch heavy relations ONLY on detail.
        """
        # to avoid circular edge cases
        from tms.models import (
            Accessorial,
            LoadDocument,
            LoadNote,
            LoadStop,
            RescheduleRequest,
        )

        stops_qs = LoadStop.objects.select_related("facility").order_by("sequence")
        docs_qs = LoadDocument.objects.order_by("-created_at")
        notes_qs = LoadNote.objects.select_related("author").order_by("-created_at")
        accessorials_qs = Accessorial.objects.select_related("created_by").order_by(
            "-created_at"
        )
        reschedule_qs = RescheduleRequest.objects.select_related(
            "created_by", "stop", "stop__facility"
        ).order_by("-created_at")

        return self.select_related(
            "broker",
            "carrier",
            "truck",
            "driver",
            "dispatcher",
            "tracking_agent",
            "lock",
            "lock__locked_by",
        ).prefetch_related(
            Prefetch("stops", queryset=stops_qs),
            Prefetch("documents", queryset=docs_qs),
            Prefetch("notes", queryset=notes_qs),
            Prefetch("accessorials", queryset=accessorials_qs),
            Prefetch("reschedule_requests", queryset=reschedule_qs),
            "tracking_updates",
        )

    def active(self):
        return self.exclude(status__in=[Load.Status.COMPLETED, Load.Status.CANCELLED])

    def for_dispatcher(self, user):
        return self.filter(dispatcher=user)

    def for_tracking_agent(self, user):
        return self.filter(tracking_agent=user)


class LoadManager(models.Manager):
    def get_queryset(self):
        return LoadQuerySet(self.model, using=self._db)

    def for_list_display(self):
        return self.get_queryset().for_list_display()

    def for_detail_display(self):
        return self.get_queryset().for_detail_display()

    def active(self):
        return self.get_queryset().active()


def carrier_document_upload_path(instance, filename):
    """Generate upload path: carrier_documents/carrier_id/document_type/filename"""
    ext = os.path.splitext(filename)[1]  # get file extension
    # clean filename to avoid issues
    clean_filename = f"{instance.document_type}{ext}"
    return f"carrier_documents/{instance.carrier.id}/{instance.document_type}/{clean_filename}"


def load_document_upload_path(instance, filename):
    """Generate upload path: load_documents/load_id/document_type/filename"""
    ext = os.path.splitext(filename)[1]
    # Use current timestamp instead of instance.created_at (which doesn't exist yet on first save)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    clean_filename = f"{instance.document_type}_{timestamp}{ext}"
    return (
        f"load_documents/{instance.load.id}/{instance.document_type}/{clean_filename}"
    )


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

    class Meta:
        ordering = ["name"]
        verbose_name = "Broker"
        verbose_name_plural = "Brokers"
        indexes = [
            models.Index(fields=["name"], name="broker_name_idx"),
            models.Index(fields=["mc_number"], name="broker_mc_number_idx"),
        ]


class Facility(BaseModel):
    """Shipper or receiver location."""

    name = models.CharField(max_length=200)

    # Address
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, help_text="US state abbreviation")
    zip_code = models.CharField(max_length=10)

    # Contact
    contact_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)

    notes = models.TextField(
        blank=True, help_text="Special instructions, dock info, etc."
    )

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state} )"

    class Meta:
        ordering = ["name"]
        verbose_name = "Facility"
        verbose_name_plural = "Facilities"
        indexes = [
            models.Index(fields=["name", "city"], name="facility_name_city_idx"),
        ]


class Carrier(BaseModel):
    """Trucking company or owner-operator."""

    class CarrierType(models.TextChoices):
        COMPANY = "company", "Trucking Company"
        OWNER_OPERATOR = "owner_operator", "Owner-Operator"

    class CommissionType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage of Rate"
        FIXED = "fixed", "Fixed Amount (per load)"

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

    # Audit - who created this carrier
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="carriers_created"
    )

    # Commission configuration (admin-only in UI)
    commission_type = models.CharField(
        max_length=20,
        choices=CommissionType.choices,
        default=CommissionType.PERCENTAGE,
        blank=True,
        null=True,
        help_text="Carrier pay type (percentage or fixed per load).",
    )
    commission_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="If percentage: enter 0-100. If fixed: amount per load in USD.",
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Carrier"
        verbose_name_plural = "Carriers"
        indexes = [
            GinIndex(
                fields=["name"], name="carrier_name_gin_idx", opclasses=["gin_trgm_ops"]
            ),
            models.Index(fields=["mc_number"], name="carrier_mc_number_idx"),
        ]


class Truck(BaseModel):
    """
    Truck unit - combines tractor and trailer info for V1 MVP.
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
        ordering = ["truck_number"]
        verbose_name = "Truck"
        verbose_name_plural = "Trucks"
        indexes = [
            models.Index(
                fields=["carrier", "truck_number"], name="truck_number_carrier_idx"
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "truck_number"], name="unique_truck_per_carrier"
            )
        ]

    def __str__(self):
        return f"{self.truck_number} ({self.EquipmentType(self.equipment_type).label})"


class Driver(BaseModel):
    """Truck driver."""

    class DriverStatus(models.TextChoices):
        AVAILABLE = "available", "Available"
        ASSIGNED = "assigned", "Assigned to Load"

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

    # Current Status
    current_status = models.CharField(
        max_length=20,
        choices=DriverStatus.choices,
        default=DriverStatus.AVAILABLE,
        help_text="Current operational status",
    )

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "Driver"
        verbose_name_plural = "Drivers"
        indexes = [
            models.Index(fields=["carrier", "current_status"], name="driver_status_idx")
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class CarrierDocument(BaseModel):
    """LoadDocument related to a Carrier."""

    class DocumentType(models.TextChoices):
        W9 = "W9", "W9"
        INSURANCE_COI = "INSURANCE_COI", "Insurance (COI)"
        AUTHORITY = "AUTHORITY", "MC / Authority Letter"
        ACH = "ACH", "ACH / Banking Form"
        LOR = "LOR", "Letter of Reference"
        OTHER = "OTHER", "Other"

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    carrier = models.ForeignKey(
        "Carrier", on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
    )

    file = models.FileField(upload_to=carrier_document_upload_path, max_length=500)
    original_filename = models.CharField(max_length=255, blank=True, editable=False)
    description = models.TextField(blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        if self.file:
            if not self.original_filename:
                self.original_filename = self.file.name
            if not self.file_size:
                self.file_size = self.file.size

        # Run validation
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """delete file froms torage when model is deleted"""
        if self.file:
            self.file.delete(save=False)
        super().delete(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "document_type"],
                name="unique_document_per_carrier_and_type",
            )
        ]
        ordering = ["-created_at"]

    def clean(self):
        if self.file:
            if self.file.size > self.MAX_FILE_SIZE:
                raise ValidationError(
                    {
                        "file": f"File size cannot exceed {self.MAX_FILE_SIZE / (1024 * 1024)} MB."
                    }
                )


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
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    # Relationships
    load = models.ForeignKey("Load", on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.OTHER,
    )

    file = models.FileField(upload_to=load_document_upload_path, max_length=500)
    original_filename = models.CharField(max_length=255, blank=True, editable=False)
    description = models.TextField(blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if self.file:
            if self.file.size > self.MAX_FILE_SIZE:
                raise ValidationError(
                    {
                        "file": f"File size cannot exceed {self.MAX_FILE_SIZE / (1024 * 1024)} MB."
                    }
                )

    def save(self, *args, **kwargs):
        if self.file:
            if not self.original_filename:
                self.original_filename = self.file.name
            if not self.file_size:
                self.file_size = self.file.size
        # Run validation
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """delete file from storage when model is deleted"""
        if self.file:
            self.file.delete(save=False)
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.load.load_id} - {self.document_type} ({self.original_filename})"


class Accessorial(BaseModel):
    """
    Extra charges for a Load
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
        COMPLETED = "completed", "Completed"

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
        default="fcfs",
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

    weight = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Weight for this stop only",
    )

    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["load", "sequence"], name="unique_stop_sequence"
            )
        ]
        ordering = ["sequence"]

    def __str__(self):
        return (
            f"{self.load.load_id} - Stop"
            f" ({self.StopType(self.stop_type).label}: {self.facility.name})"
        )

    def clean(self):
        super().clean()

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
    def duration_at_facility(self):
        """Duration truck spent at this stop (arrival to departure)."""
        if self.arrived_at and self.departed_at:
            return self.departed_at - self.arrived_at
        return None

    def check_in(self, arrival_time=None):
        """
        V1 convenience. Mark stop as checked in with arrival time.
        """
        if arrival_time:
            self.arrived_at = arrival_time
        else:
            self.arrived_at = timezone.now()
        self.save(update_fields=["arrived_at", "updated_at"])

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


class LoadNote(BaseModel):
    """Append-only notes for a load( author + when)"""

    load = models.ForeignKey("Load", on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="load_notes"
    )
    body = models.TextField()

    class Meta:
        ordering = ["-created_at"]


class LoadLock(BaseModel):
    """Locking mechanism on load."""

    load = models.OneToOneField("Load", on_delete=models.CASCADE, related_name="lock")
    locked_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="load_locks",
        help_text="User who currently holds the lock",
    )
    locked_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["load"], name="lock_load_idx"),
            models.Index(fields=["expires_at"], name="lock_exp_idx"),
        ]
        permissions = [
            ("override_load_lock", "Can override load lock held by another user")
        ]

    def is_expired(self):
        return timezone.now() >= self.expires_at


class Load(BaseModel):
    """
    Freight load - the core business entity.
    Check for completeness before handover to tracking.
    """

    objects = LoadManager()

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

    # Financial

    miles = models.PositiveIntegerField(
        help_text="Total loaded miles", blank=True, null=True
    )
    deadhead_miles = models.PositiveIntegerField(
        help_text="Empty miles to pickup (deadhead)", blank=True, null=True
    )
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total rate in USD",
        blank=True,
        null=True,
    )
    rpm = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        editable=False,
        null=True,
        help_text="Rate Per Mile (auto-calculated)",
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
    planned_eta = models.DateTimeField(
        null=True, blank=True, help_text="Planned ETA for final delivery"
    )
    dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When assigned to carrier/truck/driver",
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

    class Meta:
        indexes = [
            # Dispatcher dashboards / tracking wall
            models.Index(fields=["status"], name="load_status_idx"),
            # Dispatcher list filters (status + newest first)
            models.Index(
                fields=["dispatcher", "status", "-created_at"],
                name="load_disp_status_created_idx",
            ),
            models.Index(fields=["dispatcher", "status"], name="load_disp_status_idx"),
            # Date filtering / aging / KPI windows
            models.Index(fields=["created_at"], name="load_created_idx"),
            # Common lookups
            models.Index(fields=["broker"], name="load_broker_idx"),
        ]

    def clean(self):
        super().clean()
        existing = None
        if self.pk:
            existing = (
                Load.objects.filter(pk=self.pk).values("driver_id", "truck_id").first()
            )

        driver_changed = existing is None or existing.get("driver_id") != self.driver_id
        truck_changed = existing is None or existing.get("truck_id") != self.truck_id

        if (self.driver or self.truck) and not self.carrier:
            raise ValidationError(
                "Carrier must be assigned if driver or truck is assigned."
            )
        if self.carrier and self.driver and self.driver.carrier != self.carrier:
            raise ValidationError("Driver's carrier does not match assigned carrier.")
        if self.carrier and self.truck and self.truck.carrier != self.carrier:
            raise ValidationError("Truck's carrier does not match assigned carrier.")
        if (
            driver_changed
            and self.driver
            and self.driver.current_status != self.driver.DriverStatus.AVAILABLE
        ):
            raise ValidationError({"driver": "Driver is not available."})
        if (
            truck_changed
            and self.truck
            and self.truck.current_status != self.truck.TruckStatus.AVAILABLE
        ):
            raise ValidationError({"truck": "Truck is not available."})

    # denormalized fields
    origin_city = models.CharField(max_length=100, blank=True, null=True)
    origin_state = models.CharField(max_length=2, blank=True, null=True)
    origin_appt_start = models.DateTimeField(null=True, blank=True)
    origin_appt_end = models.DateTimeField(null=True, blank=True)
    destination_city = models.CharField(max_length=100, blank=True, null=True)
    destination_state = models.CharField(max_length=2, blank=True, null=True)
    destination_appt_start = models.DateTimeField(null=True, blank=True)
    destination_appt_end = models.DateTimeField(null=True, blank=True)
    last_tracking_at = models.DateTimeField(null=True, blank=True)
    is_delayed = models.BooleanField(default=False)

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
        if self.origin_city and self.origin_state:
            return f"{self.origin_city}, {self.origin_state}"
        return "-"

    @property
    def destination(self):
        if self.destination_city and self.destination_state:
            return f"{self.destination_city}, {self.destination_state}"
        return "-"

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

    def has_rate_confirmation(self):
        """
        Check if Rate Confirmation document is uploaded.
        Can keep here as it is a simple Read-only property.
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
        LoadStop,
        on_delete=models.PROTECT,
        related_name="reschedule_requests",
        help_text="The specific stop for which the reschedule is requested",
    )
    # Snapshot of what the stop appointment was at the time the request was created
    original_appt_start = models.DateTimeField(null=True, blank=True)
    original_appt_end = models.DateTimeField(null=True, blank=True)

    # What is being requested (new window)
    requested_appt_start = models.DateTimeField(null=True, blank=True)
    requested_appt_end = models.DateTimeField(null=True, blank=True)

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
        # Validate window ordering for requested window
        if self.requested_appt_start and self.requested_appt_end:
            if self.requested_appt_start > self.requested_appt_end:
                raise ValidationError(
                    {"requested_appt_end": "Requested end must be after start."}
                )

        # Validate window ordering for original snapshot (if provided)
        if self.original_appt_start and self.original_appt_end:
            if self.original_appt_start > self.original_appt_end:
                raise ValidationError(
                    {"original_appt_end": "Original end must be after start."}
                )

        if self.stop:
            if self.stop.appointment_type == "appt":
                if not self.requested_appt_start and not self.requested_appt_end:
                    raise ValidationError(
                        {
                            "requested_appt_start": "For APPT stops, provide at least requested_appt_start (or a window)."
                        }
                    )
            else:  # fcfs
                if not self.remarks and not (
                    self.requested_appt_start or self.requested_appt_end
                ):
                    raise ValidationError(
                        {
                            "remarks": "For FCFS stops, provide details in remarks if no specific requested appointment time is given."
                        }
                    )

    @property
    def is_fully_approved(self):
        """Check if all approvals are complete."""
        return (
            self.consignee_approved and self.broker_approved and self.manager_approved
        )


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
        OTHER = "other", "Other"

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
