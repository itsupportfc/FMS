# tms/admin.py - Replace all the basic registrations

from django.contrib import admin

from .models import (
    Accessorial,
    Broker,
    Carrier,
    Driver,
    DutyLog,
    Facility,
    Handover,
    Load,
    LoadDocument,
    LoadStop,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
)


@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "mc_number",
        "primary_contact_name",
        "primary_phone",
        "created_at",
    )
    search_fields = ("name", "mc_number", "primary_contact_name")
    list_filter = ("created_at",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "facility_type", "city", "state", "contact_name", "phone")
    search_fields = ("name", "city", "state", "contact_name")
    list_filter = ("facility_type", "state", "appointment_required")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Carrier)
class CarrierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "carrier_type",
        "mc_number",
        "dot_number",
        "created_at",
    )
    search_fields = ("name", "mc_number", "dot_number")
    list_filter = ("carrier_type", "created_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(Truck)
class TruckAdmin(admin.ModelAdmin):
    list_display = ("truck_number", "carrier", "vin", "equipment_type", "license_plate")
    search_fields = ("truck_number", "vin", "license_plate")
    list_filter = ("carrier", "equipment_type")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("carrier",)


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("full_name", "carrier", "cdl_number", "phone", "current_status")
    search_fields = ("first_name", "last_name", "cdl_number", "phone")
    list_filter = ("carrier", "current_status", "created_at")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("carrier",)

    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    full_name.short_description = "Driver Name"


@admin.register(Load)
class LoadAdmin(admin.ModelAdmin):
    list_display = (
        "load_id",
        "broker",
        "carrier",
        "status",
        "dispatcher",
        "origin_city",
        "destination_city",
        "created_at",
    )
    search_fields = ("load_id", "broker__name", "carrier__name")
    list_filter = ("status", "dispatcher", "tracking_agent", "created_at")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at", "load_id")
    raw_id_fields = (
        "broker",
        "carrier",
        "dispatcher",
        "tracking_agent",
        "driver",
        "truck",
    )
    ordering = ("-created_at",)

    fieldsets = (
        ("Basic Info", {"fields": ("load_id", "broker", "status")}),
        (
            "Route & Timing",
            {
                "fields": (
                    "origin_city",
                    "origin_state",
                    "destination_city",
                    "destination_state",
                    "planned_eta",
                )
            },
        ),
        ("Carrier Assignment", {"fields": ("carrier", "driver", "truck")}),
        ("Financials", {"fields": ("rate", "miles", "deadhead_miles")}),
        ("Personnel", {"fields": ("dispatcher", "tracking_agent")}),
        (
            "Metadata",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    class LoadStopInline(admin.TabularInline):
        model = LoadStop
        extra = 0
        readonly_fields = ("sequence", "status", "arrived_at", "departed_at")
        fields = (
            "sequence",
            "stop_type",
            "facility",
            "appointment_type",
            "appt_start",
            "appt_end",
            "status",
        )

    inlines = [LoadStopInline]


@admin.register(LoadStop)
class LoadStopAdmin(admin.ModelAdmin):
    list_display = ("load", "sequence", "stop_type", "facility", "status", "appt_start")
    search_fields = ("load__load_id", "facility__name")
    list_filter = ("stop_type", "status", "appointment_type")
    raw_id_fields = ("load", "facility")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Accessorial)
class AccessorialAdmin(admin.ModelAdmin):
    list_display = (
        "load",
        "charge_type",
        "amount",
        "manager_approved",
        "broker_approved",
        "created_at",
    )
    search_fields = ("load__load_id", "description")
    list_filter = ("charge_type", "manager_approved", "broker_approved", "created_at")
    raw_id_fields = ("load", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(LoadDocument)
class LoadDocumentAdmin(admin.ModelAdmin):
    list_display = ("load", "document_type", "original_filename", "created_at")
    search_fields = ("load__load_id", "original_filename")
    list_filter = ("document_type", "created_at")
    raw_id_fields = ("load",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(RescheduleRequest)
class RescheduleRequestAdmin(admin.ModelAdmin):
    list_display = (
        "load",
        "stop",
        "reason",
        "consignee_approved",
        "broker_approved",
        "manager_approved",
        "created_at",
    )
    search_fields = ("load__load_id", "stop__facility__name")
    list_filter = (
        "reason",
        "consignee_approved",
        "broker_approved",
        "manager_approved",
        "created_at",
    )
    raw_id_fields = ("load", "stop", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DutyLog)
class DutyLogAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "status",
        "start_time",
        "end_time",
        "current_location",
        "created_at",
    )
    search_fields = ("driver__first_name", "driver__last_name", "current_location")
    list_filter = ("status", "start_time", "created_at")
    raw_id_fields = ("driver", "truck", "load", "created_by")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "start_time"


@admin.register(TrackingUpdate)
class TrackingUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "load",
        "tracking_agent",
        "current_location",
        "is_delayed",
        "tracking_method",
        "created_at",
    )
    search_fields = ("load__load_id", "current_location", "notes")
    list_filter = ("is_delayed", "delay_reason", "tracking_method", "created_at")
    raw_id_fields = ("load", "tracking_agent")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(Handover)
class HandoverAdmin(admin.ModelAdmin):
    list_display = ("load", "from_agent", "to_agent", "created_at")
    search_fields = ("load__load_id", "from_agent__username", "to_agent__username")
    list_filter = ("created_at",)
    raw_id_fields = ("load", "from_agent", "to_agent")
    readonly_fields = ("created_at", "updated_at")
