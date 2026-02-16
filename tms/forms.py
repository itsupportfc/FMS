# forms.py
from typing import cast

from django import forms
from django.core.exceptions import ValidationError
from django.forms import ModelChoiceField

from .models import (
    Accessorial,
    Broker,
    Carrier,
    Driver,
    DutyLog,
    Facility,
    Load,
    LoadDocument,
    LoadNote,
    LoadStop,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
    User,
)

_DT_LOCAL_FMT = "%Y-%m-%dT%H:%M"


class RequiredFieldsMixin:
    """
    Mixin to automatically add asterisks (*) to required field labels.
    blank=True => in field definition => not required => no asterisk
    blank=False (default) => required => add asterisk
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            if field.required:
                current_label = field.label or field_name.replace("_", " ").title()
                field.label = f"{current_label} *"


class LoadForm(RequiredFieldsMixin, forms.ModelForm):
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
            "deadhead_miles",
            "carrier",
            "driver",
            "truck",
            "planned_eta",
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
            "planned_eta": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}
            ),
            "load_id": forms.TextInput(
                attrs={"placeholder": "Internal or broker load ID"}
            ),
            "rate": forms.NumberInput(attrs={"placeholder": "0.00", "step": "0.01"}),
            "miles": forms.NumberInput(attrs={"placeholder": "0"}),
            "deadhead_miles": forms.NumberInput(attrs={"placeholder": "0"}),
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

        # Lock fields after DISPATCHED
        if (
            self.instance
            and self.instance.pk
            and self.instance.status
            in [
                Load.Status.DISPATCHED,
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
                "deadhead_miles",
                "carrier",
                "driver",
                "truck",
                # "dispatcher_commission",
                # "commission_type",
            ]
            for f in lock_fields:
                if f in self.fields:
                    self.fields[f].disabled = True
                    self.fields[f].widget.attrs.update({"class": disabled_classes})


class LoadStopForm(RequiredFieldsMixin, forms.ModelForm):
    class Meta:
        model = LoadStop
        fields = [
            "stop_type",
            "facility",
            "appointment_type",
            "appt_start",
            "appt_end",
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


class LoadNoteForm(RequiredFieldsMixin, forms.ModelForm):
    class Meta:
        model = LoadNote
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Add a note...",
                    "class": "form-textarea w-full max-w-full box-border resize-y",
                }
            ),
        }


class DocumentUploadForm(RequiredFieldsMixin, forms.ModelForm):
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


class TrackingUpdateForm(RequiredFieldsMixin, forms.ModelForm):
    """
    Form for creating tracking updates.

    Excludes relational fields (`load`, `tracking_agent`) which are set in views.
    """

    class Meta:
        model = TrackingUpdate
        fields = [
            "current_location",
            "tracking_method",
            "is_delayed",
            "delay_reason",
            "new_eta",
            "notes",
        ]
        widgets = {
            "current_location": forms.TextInput(
                attrs={"placeholder": "e.g., I-80 exit 42, IA"}
            ),
            "tracking_method": forms.Select(),
            "is_delayed": forms.CheckboxInput(),
            "delay_reason": forms.Select(),
            "new_eta": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Add brief notes..."}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        is_delayed = cleaned.get("is_delayed")
        delay_reason = cleaned.get("delay_reason")

        if is_delayed and not delay_reason:
            self.add_error(
                "delay_reason", "Delay reason is required when marked delayed."
            )

        return cleaned


class RescheduleRequestForm(RequiredFieldsMixin, forms.ModelForm):
    """
    Form for requesting and recording stop appointment reschedules.

    Excludes relational fields (`load`, `created_by`, `stop`) which are set in views.
    Shows original appointment window from selected stop as read-only display.
    User proposes new requested appointment window.
    """

    class Meta:
        model = RescheduleRequest
        fields = [
            "stop",
            "reason",
            "requested_appt_start",
            "requested_appt_end",
            "remarks",
            "consignee_approved",
            "broker_approved",
            "manager_approved",
        ]
        widgets = {
            "stop": forms.Select(),
            "reason": forms.Select(),
            "requested_appt_start": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            ),
            "requested_appt_end": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            ),
            "consignee_approved": forms.CheckboxInput(),
            "broker_approved": forms.CheckboxInput(),
            "manager_approved": forms.CheckboxInput(),
            "remarks": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Contacts, confirmation #, notes..."}
            ),
        }

    def __init__(self, load, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter stops to only those from this load
        self.fields["stop"].queryset = load.stops.all()
        self.fields["stop"].label = "Select Stop to Reschedule"

        # Set input formats for datetime fields
        self.fields["requested_appt_start"].input_formats = [_DT_LOCAL_FMT]
        self.fields["requested_appt_end"].input_formats = [_DT_LOCAL_FMT]


# ============================================================================
# ACCESSORIAL FORMS
# ============================================================================


class AccessorialForm(RequiredFieldsMixin, forms.ModelForm):
    class Meta:
        model = Accessorial
        fields = [
            "charge_type",
            "amount",
            "description",
            # Detention fields
            "detention_start",
            "detention_end",
            "detention_billed_hours",
            # Layover fields
            "layover_start_date",
            "layover_end_date",
            # Approvals
            "manager_approved",
            "broker_approved",
        ]
        widgets = {
            "charge_type": forms.Select(
                attrs={"class": "w-full px-3 py-2 border border-gray-300 bg-white"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "type": "number",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Leave blank for manager to calculate",
                    "class": "w-full px-3 py-2 border border-gray-300",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Details, reasons, notes...",
                    "class": "w-full px-3 py-2 border border-gray-300",
                }
            ),
            # Detention
            "detention_start": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                    "class": "w-full px-3 py-2 border border-gray-300",
                },
                format="%Y-%m-%dT%H:%M",
            ),
            "detention_end": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                    "class": "w-full px-3 py-2 border border-gray-300",
                },
                format="%Y-%m-%dT%H:%M",
            ),
            "detention_billed_hours": forms.NumberInput(
                attrs={
                    "type": "number",
                    "step": "0.25",
                    "min": "0",
                    "placeholder": "Billable hours",
                    "class": "w-full px-3 py-2 border border-gray-300",
                }
            ),
            # Layover
            "layover_start_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "w-full px-3 py-2 border border-gray-300",
                }
            ),
            "layover_end_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "w-full px-3 py-2 border border-gray-300",
                }
            ),
            "manager_approved": forms.CheckboxInput(),
            "broker_approved": forms.CheckboxInput(),
        }

    def clean(self):
        """Custom validation based on charge_type."""
        cleaned_data = super().clean()
        charge_type = cleaned_data.get("charge_type")

        if charge_type == Accessorial.ChargeType.DETENTION:
            detention_start = cleaned_data.get("detention_start")
            detention_end = cleaned_data.get("detention_end")
            billed_hours = cleaned_data.get("detention_billed_hours")

            if not detention_start or not detention_end:
                raise forms.ValidationError(
                    "Detention start and end times are required for Detention charges."
                )
            if detention_end <= detention_start:
                raise forms.ValidationError(
                    "Detention end time must be after start time."
                )
            if billed_hours is None or billed_hours <= 0:
                raise forms.ValidationError(
                    "Billed hours must be a positive number for Detention charges."
                )

        elif charge_type == Accessorial.ChargeType.LAYOVER:
            layover_start = cleaned_data.get("layover_start_date")
            layover_end = cleaned_data.get("layover_end_date")

            if not layover_start or not layover_end:
                raise forms.ValidationError(
                    "Layover start and end dates are required for Layover charges."
                )
            if layover_end < layover_start:
                raise forms.ValidationError(
                    "Layover end date must be on or after start date."
                )
        return cleaned_data


# ============================================================================
# HOS
# ============================================================================


class DutyLogForm(RequiredFieldsMixin, forms.ModelForm):
    class Meta:
        model = DutyLog
        fields = [
            "status",
            "start_time",
            "current_location",
            "remarks",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}, format="%Y-%m-%dT%H:%M"
            ),
            "current_location": forms.TextInput(
                attrs={"placeholder": "e.g., I-80 exit 42, IA"}
            ),
            "remarks": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Add brief notes..."}
            ),
        }


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "attrs",
            {
                "class": "form-input w-full",
            },
        )
        super().__init__(*args, **kwargs)


class StopEditForm(forms.Form):
    arrival_time = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=DateTimeLocalInput(),
    )

    departure_time = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=DateTimeLocalInput(),
    )

    def __init__(self, *args, stop=None, **kwargs):
        self.stop = stop
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()

        arrival = cleaned.get("arrival_time") or self.stop.arrived_at
        departure = cleaned.get("departure_time") or self.stop.departed_at

        if cleaned.get("departure_time") and not arrival:
            raise ValidationError("Arrival time is required before departure time.")

        if arrival and departure and arrival >= departure:
            raise ValidationError("Departure time must be after arrival time.")

        return cleaned


# ENTITY CREATION FORMS
class FacilityForm(RequiredFieldsMixin, forms.ModelForm):
    """Form for creating and editing facilities."""

    class Meta:
        model = Facility
        fields = [
            "name",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "zip_code",
            "contact_name",
            "phone",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Add notes..."}),
            "state": forms.TextInput(attrs={"placeholder": "e.g., NY", "maxlength": 2}),
        }


class BrokerForm(RequiredFieldsMixin, forms.ModelForm):
    """Form for creating and editing brokers."""

    class Meta:
        model = Broker
        fields = [
            "name",
            "mc_number",
            "primary_contact_name",
            "primary_phone",
            "primary_email",
            "notes",
            "credit_history",
            "average_payment_days",
        ]
        widgets = {
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "General notes about this broker..."}
            ),
            "credit_history": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Payment history, credit issues, etc."}
            ),
        }


class CarrierForm(RequiredFieldsMixin, forms.ModelForm):
    """Form for creating normal carriers (not owner-operators)."""

    class Meta:
        model = Carrier
        fields = [
            "name",
            "mc_number",
            "dot_number",
            "primary_contact_name",
            "primary_phone",
            "primary_email",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "zip_code",
            "carrier_has_insurance",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "General notes about this carrier..."}
            ),
            "state": forms.TextInput(attrs={"placeholder": "e.g., NY", "maxlength": 2}),
        }


class DriverForm(RequiredFieldsMixin, forms.ModelForm):
    """Form for creating and editing drivers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        carrier_field = cast(ModelChoiceField, self.fields["carrier"])
        carrier_field.queryset = Carrier.objects.filter(
            carrier_type=Carrier.CarrierType.COMPANY
        ).order_by("name")

    class Meta:
        model = Driver
        fields = [
            "carrier",
            "first_name",
            "last_name",
            "phone",
            "email",
            "cdl_number",
            "cdl_expiration",
            "hos_cycle",
            "notes",
        ]
        widgets = {
            "cdl_expiration": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Driver notes, constraints, preferences...",
                }
            ),
        }


class TruckForm(RequiredFieldsMixin, forms.ModelForm):
    """Form for creating and editing trucks for normal carriers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        carrier_field = cast(ModelChoiceField, self.fields["carrier"])
        carrier_field.queryset = Carrier.objects.filter(
            carrier_type=Carrier.CarrierType.COMPANY
        ).order_by("name")

    class Meta:
        model = Truck
        fields = [
            "carrier",
            "truck_number",
            "trailer_number",
            "vin",
            "license_plate",
            "equipment_type",
            "length_feet",
            "chassis_no",
            "truck_has_insurance",
            "notes",
        ]
        widgets = {
            "length_feet": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Truck notes, maintenance details..."}
            ),
        }


class OwnerOperatorForm(RequiredFieldsMixin, forms.Form):
    # Carrier fields
    carrier_name = forms.CharField(
        max_length=200,
        label="Carrier Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., John Doe Trucking"}),
    )
    mc_number = forms.CharField(
        max_length=20,
        label="MC Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., MC123456"}),
    )
    dot_number = forms.CharField(
        max_length=20,
        label="DOT Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., DOT123456"}),
    )
    primary_contact_name = forms.CharField(
        max_length=100,
        label="Contact Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., John Doe"}),
    )
    primary_phone = forms.CharField(
        max_length=20,
        label="Contact Phone",
        widget=forms.TextInput(attrs={"placeholder": "e.g., 555-1234"}),
    )
    primary_email = forms.EmailField(
        label="Contact Email",
        widget=forms.EmailInput(attrs={"placeholder": "e.g., john@example.com"}),
    )
    address_line1 = forms.CharField(
        max_length=200,
        label="Address Line 1",
        widget=forms.TextInput(attrs={"placeholder": "Street address"}),
    )
    address_line2 = forms.CharField(
        max_length=200,
        required=False,
        label="Address Line 2",
        widget=forms.TextInput(attrs={"placeholder": "Apt, suite, etc. (optional)"}),
    )
    city = forms.CharField(
        max_length=100,
        label="City",
        widget=forms.TextInput(attrs={"placeholder": "e.g., Los Angeles"}),
    )
    state = forms.CharField(
        max_length=2,
        label="State",
        widget=forms.TextInput(attrs={"placeholder": "e.g., CA", "maxlength": "2"}),
    )
    zip_code = forms.CharField(
        max_length=10,
        label="Zip Code",
        widget=forms.TextInput(attrs={"placeholder": "e.g., 90001"}),
    )
    carrier_has_insurance = forms.BooleanField(
        required=False,
        initial=True,
        label="Has Insurance",
    )
    carrier_notes = forms.CharField(
        required=False,
        label="Carrier Notes",
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Additional notes about carrier..."}
        ),
    )

    # Driver fields
    driver_first_name = forms.CharField(
        max_length=50,
        label="Driver First Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., John"}),
    )
    driver_last_name = forms.CharField(
        max_length=50,
        label="Driver Last Name",
        widget=forms.TextInput(attrs={"placeholder": "e.g., Doe"}),
    )
    driver_phone = forms.CharField(
        max_length=20,
        label="Driver Phone",
        widget=forms.TextInput(attrs={"placeholder": "e.g., 555-1234"}),
    )
    driver_email = forms.EmailField(
        required=False,
        label="Driver Email",
        widget=forms.EmailInput(attrs={"placeholder": "e.g., john@example.com"}),
    )
    cdl_number = forms.CharField(
        max_length=50,
        label="CDL Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., A1234567"}),
    )
    cdl_expiration = forms.DateField(
        required=False,
        label="CDL Expiration Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    hos_cycle = forms.ChoiceField(
        choices=[
            ("60_7", "60 hours / 7 days"),
            ("70_8", "70 hours / 8 days"),
        ],
        initial="60_7",
        label="HOS Cycle",
    )
    driver_notes = forms.CharField(
        required=False,
        label="Driver Notes",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "Driver preferences, certifications, etc...",
            }
        ),
    )

    # Truck fields
    truck_number = forms.CharField(
        max_length=50,
        label="Truck Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., TRUCK-001"}),
    )
    trailer_number = forms.CharField(
        max_length=50,
        required=False,
        label="Trailer Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., TRAILER-22"}),
    )
    equipment_type = forms.ChoiceField(
        choices=Truck.EquipmentType.choices,
        label="Equipment Type",
    )
    vin = forms.CharField(
        max_length=17,
        required=False,
        label="VIN",
        widget=forms.TextInput(
            attrs={"placeholder": "e.g., 1FUJGHDV8BLBP4086", "maxlength": "17"}
        ),
    )
    chassis_no = forms.CharField(
        max_length=50,
        required=False,
        label="Chassis Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g., CH-2024-19"}),
    )
    license_plate = forms.CharField(
        max_length=20,
        label="License Plate",
        widget=forms.TextInput(attrs={"placeholder": "e.g., ABC1234"}),
    )
    truck_has_insurance = forms.BooleanField(
        required=False,
        initial=True,
        label="Truck Has Insurance",
    )
    truck_notes = forms.CharField(
        required=False,
        label="Truck Notes",
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Maintenance notes, equipment, etc..."}
        ),
    )

    def clean_state(self):
        state = self.cleaned_data.get("state")
        return state.upper() if state else state
