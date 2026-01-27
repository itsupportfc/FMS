# forms.py
from typing import Optional, cast

from django import forms
from django.db.models import QuerySet
from django.forms import ModelChoiceField
from django.utils import timezone

from .models import (
    Accessorial,
    Driver,
    DutyLog,
    Load,
    LoadDocument,
    LoadStop,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
    User,
)

_DT_LOCAL_FMT = "%Y-%m-%dT%H:%M"


class LoadForm(forms.ModelForm):
    """
    Form for creating and editing Load records.

    Key Features:
    - Datetime pickers with step=60 (1-minute intervals)
    - Dynamic carrier filtering (HTMX updates driver/truck options)
    - Placeholders for better UX (hints in empty fields)
    - All validation in model, form just handles input/output
    """

    class Meta:
        model = Load
        fields = [
            # broker fields
            "load_id",
            "broker",
            "commodity_type",
            "weight",
            # financials
            "rate",
            "miles",
            "commission_type",
            "dispatcher_commission",
            # carrier
            "carrier",
            "driver",
            "truck",
            # Timestamps (for edit view - tracking agent fills these in)
            # "dispatched_at",
            # "delivered_at",
            # "completed_at",
            # "cancelled_at",
            # Notes
            "remarks",
        ]

        # Widget customization: Convert datetime fields to HTML5 datetime-local
        # WHY: Native browser datetime picker is better UX than text input
        widgets = {
            "carrier": forms.Select(
                attrs={
                    "hx-get": "/loads/carrier-assets/",
                    "hx-target": "#carrier-assets",
                    "hx-trigger": "change",
                }
            ),
            # "dispatched_at": forms.DateTimeInput(
            #     attrs={"type": "datetime-local", "step": "60"}
            # ),
            # "delivered_at": forms.DateTimeInput(
            #     attrs={"type": "datetime-local", "step": "60"}
            # ),
            # "completed_at": forms.DateTimeInput(
            #     attrs={"type": "datetime-local", "step": "60"}
            # ),
            # "cancelled_at": forms.DateTimeInput(
            #     attrs={"type": "datetime-local", "step": "60"}
            # ),
            "remarks": forms.Textarea(attrs={"rows": 4}),  # Multi-line text
        }

    def __init__(self, *args, **kwargs):
        """
        Customize form initialization.

        Runs when form is instantiated in view:
        - For create:
            - GET LoadForm()
            - POST LoadForm(request.POST)
        - For edit:
            - GET LoadForm(instance=load)
            - POST LoadForm(request.POST, instance=load)

        Customizations:
        1. Add placeholders (UX hints in empty fields)
        2. Configure HTMX for carrier filtering
        3. Filter driver/truck querysets based on selected carrier
        """
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Set placeholder text (UX hints, not styling)
        placeholders = {
            "load_id": "Internal or broker load ID",
            "rate": "0.00",
            "miles": "0",
            "remarks": "Notes for dispatch/tracking",
        }

        for name, field in self.fields.items():
            if name in placeholders:
                field.widget.attrs.setdefault("placeholder", placeholders[name])

        # Dynamic Dropdown
        carrier_id = None

        # EDIT Views: instance is there + carrier assigned
        if self.instance and getattr(self.instance, "carrier", None):
            carrier_id = self.instance.carrier_id

        # CREATE Views: self.data exists on POST requests
        elif "carrier" in self.data:
            carrier_id = self.data.get("carrier")

        driver_field = cast(ModelChoiceField, self.fields["driver"])
        truck_field = cast(ModelChoiceField, self.fields["truck"])
        # Filter driver/truck based on carrier
        if carrier_id:
            driver_field.queryset = Driver.objects.filter(carrier_id=carrier_id)
            truck_field.queryset = Truck.objects.filter(carrier_id=carrier_id)
        else:
            driver_field.queryset = Driver.objects.none()
            truck_field.queryset = Truck.objects.none()

        # Lock financial fields after IN_TRANSIT
        if (
            self.instance
            and self.instance.pk
            and self.instance.status
            in [
                Load.Status.IN_TRANSIT,
                Load.Status.DELIVERED,
                Load.Status.COMPLETED,
            ]
        ):
            # Add obvious disabled styling
            disabled_classes = "bg-gray-200 cursor-not-allowed text-gray-600"

            lock_fields = [
                "load_id",
                "broker",
                "rate",
                "miles",
                "carrier",
                "driver",
                "truck",
                "dispatcher_commission",
                "commission_type",
            ]
            for f in lock_fields:
                if f in self.fields:
                    self.fields[f].disabled = True
                    self.fields[f].widget.attrs.update({"class": disabled_classes})

        # Optional: role-based disabling
        # Dispatcher edits most fields; tracking agent should not edit financials/assets generally.
        if self.user and getattr(self.user, "role", None) == "tracking_agent":
            disabled_classes = "bg-gray-100 cursor-not-allowed text-gray-600"
            tracker_lock = [
                "broker",
                "rate",
                "miles",
                "carrier",
                "driver",
                "truck",
                "commission_type",
                "dispatcher_commission",
            ]
            for f in tracker_lock:
                if f in self.fields:
                    self.fields[f].disabled = True
                    self.fields[f].widget.attrs.update({"class": disabled_classes})


class LoadStopForm(forms.ModelForm):
    class Meta:
        model = LoadStop
        fields = [
            "stop_type",
            "facility",
            # "sequence",
            "appointment_type",
            "appt_start",
            "appt_end",
            # "status",
            # "arrived_at",
            # "departed_at",
            # "reference_number",
            # "pieces",
            "weight",
            "notes",
        ]

        widgets = {
            "appt_start": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            ),
            "appt_end": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            ),
            # "arrived_at": forms.DateTimeInput(
            #     attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            # ),
            # "departed_at": forms.DateTimeInput(
            #     attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            # ),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# Inline formset factory (standard Django approach)
LoadStopFormSet = forms.inlineformset_factory(
    parent_model=Load,
    model=LoadStop,
    form=LoadStopForm,
    extra=0,  # show 2 empty stop rows by default
    can_delete=False,  # allow removing a stop
    min_num=2,  # REQUIRE at least 2 stops
    validate_min=True,  # enforce min_num validation
)


class DocumentUploadForm(forms.ModelForm):
    """
    Form for uploading documents to a load.

    Simple file upload form - no complex logic needed.
    Load relationship is set in view, not in form.

    WHY: Separate form from LoadForm because document upload happens
    independently (not part of create/edit load workflow).
    """

    class Meta:
        model = LoadDocument
        fields = ["document_type", "file", "description"]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


# class TrackingUpdateForm(forms.ModelForm):
#     """
#     Form for creating tracking updates.

#     Excludes relational fields (`load`, `tracking_agent`) which are set in views.
#     """

#     class Meta:
#         model = TrackingUpdate
#         fields = [
#             "current_location",
#             "tracking_method",
#             "is_delayed",
#             "delay_reason",
#             "new_eta",
#             "notes",
#         ]
#         widgets = {
#             "current_location": forms.TextInput(
#                 attrs={"placeholder": "e.g., I-80 exit 42, IA"}
#             ),
#             "tracking_method": forms.Select(),
#             "is_delayed": forms.CheckboxInput(),
#             "delay_reason": forms.Select(),
#             "new_eta": forms.DateTimeInput(
#                 attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
#             ),
#             "notes": forms.Textarea(
#                 attrs={"rows": 3, "placeholder": "Add brief notes..."}
#             ),
#         }


# class RescheduleRequestForm(forms.ModelForm):
#     """
#     Form for requesting and recording delivery reschedules.

#     Excludes relational fields (`load`, `created_by`) which are set in views.
#     """

#     class Meta:
#         model = RescheduleRequest
#         fields = [
#             "original_appointment",
#             "new_appointment",
#             "reason",
#             "consignee_approved",
#             "broker_approved",
#             "manager_approved",
#             "remarks",
#         ]
#         widgets = {
#             "original_appointment": forms.DateTimeInput(
#                 attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
#             ),
#             "new_appointment": forms.DateTimeInput(
#                 attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
#             ),
#             "reason": forms.Select(),
#             "consignee_approved": forms.CheckboxInput(),
#             "broker_approved": forms.CheckboxInput(),
#             "manager_approved": forms.CheckboxInput(),
#             "remarks": forms.Textarea(
#                 attrs={"rows": 3, "placeholder": "Contacts, confirmation #, notes..."}
#             ),
#         }

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         # Critical: otherwise mypy/pylance + Django sometimes parse wrongly
#         self.fields["original_appointment"].input_formats = [_DT_LOCAL_FMT]
#         self.fields["new_appointment"].input_formats = [_DT_LOCAL_FMT]

# ============================================================================
# ACCESSORIAL FORMS
# ============================================================================


# class AccessorialForm(forms.ModelForm):
#     class Meta:
#         model = Accessorial
#         fields = [
#             "charge_type",
#             "amount",
#             "description",
#             # Detention fields
#             "detention_start",
#             "detention_end",
#             "detention_billed_hours",
#             # Layover fields
#             "layover_start_date",
#             "layover_end_date",
#             # Approvals
#             "manager_approved",
#             "broker_approved",
#         ]
#         widgets = {
#             "charge_type": forms.Select(
#                 attrs={"class": "w-full px-3 py-2 border border-gray-300 bg-white"}
#             ),
#             "amount": forms.NumberInput(
#                 attrs={
#                     "type": "number",
#                     "step": "0.01",
#                     "min": "0",
#                     "placeholder": "Leave blank for manager to calculate",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }
#             ),
#             "description": forms.Textarea(
#                 attrs={
#                     "rows": 3,
#                     "placeholder": "Details, reasons, notes...",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }
#             ),
#             # Detention
#             "detention_start": forms.DateTimeInput(
#                 attrs={
#                     "type": "datetime-local",
#                     "step": "60",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }, format="%Y-%m-%dT%H:%M"
#             ),
#             "detention_end": forms.DateTimeInput(
#                 attrs={
#                     "type": "datetime-local",
#                     "step": "60",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }, format="%Y-%m-%dT%H:%M"
#             ),
#             "detention_billed_hours": forms.NumberInput(
#                 attrs={
#                     "type": "number",
#                     "step": "0.25",
#                     "min": "0",
#                     "placeholder": "Billable hours",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }
#             ),
#             # Layover
#             "layover_start_date": forms.DateInput(
#                 attrs={
#                     "type": "date",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }
#             ),
#             "layover_end_date": forms.DateInput(
#                 attrs={
#                     "type": "date",
#                     "class": "w-full px-3 py-2 border border-gray-300",
#                 }
#             ),
#             "manager_approved": forms.CheckboxInput(),
#             "broker_approved": forms.CheckboxInput(),
#         }

#     def clean(self):
#         """Custom validation based on charge_type."""
#         cleaned_data = super().clean()
#         charge_type = cleaned_data.get("charge_type")

#         if charge_type == Accessorial.ChargeType.DETENTION:
#             detention_start = cleaned_data.get("detention_start")
#             detention_end = cleaned_data.get("detention_end")
#             billed_hours = cleaned_data.get("detention_billed_hours")

#             if not detention_start or not detention_end:
#                 raise forms.ValidationError(
#                     "Detention start and end times are required for Detention charges."
#                 )
#             if detention_end <= detention_start:
#                 raise forms.ValidationError(
#                     "Detention end time must be after start time."
#                 )
#             if billed_hours is None or billed_hours <= 0:
#                 raise forms.ValidationError(
#                     "Billed hours must be a positive number for Detention charges."
#                 )

#         elif charge_type == Accessorial.ChargeType.LAYOVER:
#             layover_start = cleaned_data.get("layover_start_date")
#             layover_end = cleaned_data.get("layover_end_date")

#             if not layover_start or not layover_end:
#                 raise forms.ValidationError(
#                     "Layover start and end dates are required for Layover charges."
#                 )
#             if layover_end < layover_start:
#                 raise forms.ValidationError(
#                     "Layover end date must be on or after start date."
#                 )
#         return cleaned_data


# ============================================================================
# HOS
# ============================================================================


# class DutyLogForm(forms.ModelForm):
#     class Meta:
#         model = DutyLog
#         fields = [
#             "status",
#             "start_time",
#             "current_location",
#             "remarks",
#         ]
#         widgets = {
#             "start_time": forms.DateTimeInput(
#                 attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
#             ),
#             "current_location": forms.TextInput(
#                 attrs={"placeholder": "e.g., I-80 exit 42, IA"}
#             ),
#             "remarks": forms.Textarea(
#                 attrs={"rows": 3, "placeholder": "Add brief notes..."}
#             ),
#         }
