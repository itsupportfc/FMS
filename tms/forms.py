# forms.py
from django import forms

from .models import (
    Accessorial,
    Document,
    Driver,
    DutyLog,
    Load,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
)


class LoadForm(forms.ModelForm):
    """
    Form for creating and editing Load records.

    Key Features:
    - Datetime pickers with step=60 (1-minute intervals)
    - Dynamic carrier filtering (HTMX updates driver/truck options)
    - Placeholders for better UX (hints in empty fields)
    - All validation in model, form just handles input/output
    """

    # driver = forms.ModelChoiceField(
    #     queryset=Driver.objects.none(),
    #     required=False,
    #     empty_label="Select driver",
    # )

    # truck = forms.ModelChoiceField(
    #     queryset=Truck.objects.none(),
    #     required=False,
    #     empty_label="Select truck",
    # )

    class Meta:
        model = Load
        fields = [
            # broker
            "load_id",
            "broker",
            # pickup
            "pickup_facility",
            "pickup_datetime",
            "pickup_appointment_type",
            # delivery
            "delivery_facility",
            "delivery_datetime",
            "delivery_appointment_type",
            # financials
            "rate",
            "miles",
            "commission_type",
            "dispatcher_commission",
            # carrier
            "carrier",
            "driver",
            "truck",
            # "status",
            # Timestamps (for edit view - tracking agent fills these in)
            "pickup_arrival_at",
            "pickup_departure_at",
            "delivery_arrival_at",
            "delivery_departure_at",
            "delivered_at",
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
            "pickup_datetime": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",  # HTML5 native picker
                    "step": "60",  # 1-minute intervals (not 1-second)
                }
            ),
            "delivery_datetime": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                }
            ),
            # Facility timestamp fields (filled by tracking agent during transit)
            "pickup_arrival_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                }
            ),
            "pickup_departure_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                }
            ),
            "delivery_arrival_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                }
            ),
            "delivery_departure_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                }
            ),
            "delivered_at": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                }
            ),
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
        # carrier = kwargs.pop("carrier", None)
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
        if self.instance and self.instance.carrier:
            carrier_id = self.instance.carrier_id

        # CREATE Views: self.data exists on POST requests
        elif "carrier" in self.data:
            carrier_id = self.data.get("carrier")

        # Filter driver/truck based on carrier
        if carrier_id:
            self.fields["driver"].queryset = Driver.objects.filter(  # type: ignore
                carrier_id=carrier_id
            )
            self.fields["truck"].queryset = Truck.objects.filter(carrier_id=carrier_id)  # pyright: ignore[reportAttributeAccessIssue]
        else:
            self.fields["driver"].queryset = Driver.objects.none()  # type: ignore
            self.fields["truck"].queryset = Truck.objects.none()  # type: ignore

        # Lock financial fields after IN_TRANSIT
        if self.instance and self.instance.status in [
            Load.Status.IN_TRANSIT,
            Load.Status.COMPLETED,
        ]:
            # Add obvious disabled styling
            disabled_classes = "bg-gray-100 cursor-not-allowed text-gray-600"

            self.fields["rate"].disabled = True
            self.fields["rate"].widget.attrs.update({"class": disabled_classes})

            self.fields["miles"].disabled = True
            self.fields["miles"].widget.attrs.update({"class": disabled_classes})

            self.fields["broker"].disabled = True
            self.fields["broker"].widget.attrs.update({"class": disabled_classes})

            self.fields["carrier"].disabled = True
            self.fields["carrier"].widget.attrs.update({"class": disabled_classes})

            self.fields["driver"].disabled = True
            self.fields["driver"].widget.attrs.update({"class": disabled_classes})

            self.fields["truck"].disabled = True
            self.fields["truck"].widget.attrs.update({"class": disabled_classes})

            self.fields["dispatcher_commission"].disabled = True
            self.fields["dispatcher_commission"].widget.attrs.update(
                {"class": disabled_classes}
            )

            # lock some other fields also
            self.fields["load_id"].disabled = True
            self.fields["load_id"].widget.attrs.update({"class": disabled_classes})

            self.fields["pickup_facility"].disabled = True
            self.fields["pickup_facility"].widget.attrs.update(
                {"class": disabled_classes}
            )

            self.fields["delivery_facility"].disabled = True
            self.fields["delivery_facility"].widget.attrs.update(
                {"class": disabled_classes}
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
        model = Document
        fields = ["document_type", "file", "description"]

        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class TrackingUpdateForm(forms.ModelForm):
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
                attrs={"type": "datetime-local", "step": "60"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Add brief notes..."}
            ),
        }


class RescheduleRequestForm(forms.ModelForm):
    """
    Form for requesting and recording delivery reschedules.

    Excludes relational fields (`load`, `created_by`) which are set in views.
    """

    class Meta:
        model = RescheduleRequest
        fields = [
            "original_appointment",
            "new_appointment",
            "reason",
            "consignee_approved",
            "broker_approved",
            "manager_approved",
            "remarks",
        ]
        widgets = {
            "original_appointment": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}
            ),
            "new_appointment": forms.DateTimeInput(
                attrs={"type": "datetime-local", "step": "60"}
            ),
            "reason": forms.Select(),
            "consignee_approved": forms.CheckboxInput(),
            "broker_approved": forms.CheckboxInput(),
            "manager_approved": forms.CheckboxInput(),
            "remarks": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Contacts, confirmation #, notes..."}
            ),
        }


# ============================================================================
# ACCESSORIAL FORMS
# ============================================================================


class AccessorialForm(forms.ModelForm):
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
                }
            ),
            "detention_end": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "step": "60",
                    "class": "w-full px-3 py-2 border border-gray-300",
                }
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


class DutyLogForm(forms.ModelForm):
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
                attrs={"type": "datetime-local", "step": "60"}
            ),
            "current_location": forms.TextInput(
                attrs={"placeholder": "e.g., I-80 exit 42, IA"}
            ),
            "remarks": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Add brief notes..."}
            ),
        }
