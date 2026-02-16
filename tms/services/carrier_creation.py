from typing import Any, Dict, Optional, Tuple

from django.db import transaction

from tms.models import Carrier, Driver, Truck


class CarrierCreationError(Exception):
    """Raised when carrier creation fails validation."""


def create_carrier_with_assets(
    carrier_data: Dict,
    created_by: Any,
    driver_data: Optional[Dict] = None,
    truck_data: Optional[Dict] = None,
) -> Tuple[Carrier, Optional[Driver], Optional[Truck]]:
    """Create a carrier with optional driver and truck in one transaction."""

    _validate_carrier_data(carrier_data)

    is_owner_operator = (
        carrier_data.get("carrier_type") == Carrier.CarrierType.OWNER_OPERATOR
    )

    if is_owner_operator:
        _validate_owner_operator_requirements(driver_data, truck_data)

    with transaction.atomic():
        carrier = _create_carrier(carrier_data, created_by)

        if is_owner_operator:
            driver = _create_driver(carrier, driver_data or {})
            truck = _create_truck(carrier, truck_data or {})
        else:
            driver = None
            truck = None

        return carrier, driver, truck


def _validate_carrier_data(carrier_data: Dict) -> None:
    required_fields = [
        "name",
        "mc_number",
        "dot_number",
        "carrier_type",
        "primary_contact_name",
        "primary_phone",
        "primary_email",
        "address_line1",
        "city",
        "state",
        "zip_code",
    ]

    missing = [field for field in required_fields if not carrier_data.get(field)]
    if missing:
        raise CarrierCreationError(f"Missing required fields: {', '.join(missing)}")

    if Carrier.objects.filter(mc_number=carrier_data["mc_number"]).exists():
        raise CarrierCreationError(
            f"Carrier with MC number {carrier_data['mc_number']} already exists."
        )

    if Carrier.objects.filter(dot_number=carrier_data["dot_number"]).exists():
        raise CarrierCreationError(
            f"Carrier with DOT number {carrier_data['dot_number']} already exists."
        )


def _validate_owner_operator_requirements(
    driver_data: Optional[Dict],
    truck_data: Optional[Dict],
) -> None:
    if not driver_data:
        raise CarrierCreationError("Owner-operators require driver information.")

    if not truck_data:
        raise CarrierCreationError("Owner-operators require truck information.")

    driver_required = ["first_name", "last_name", "phone", "cdl_number"]
    missing_driver = [field for field in driver_required if not driver_data.get(field)]
    if missing_driver:
        raise CarrierCreationError(
            f"Driver missing required fields: {', '.join(missing_driver)}"
        )

    truck_required = ["truck_number", "equipment_type", "license_plate"]
    missing_truck = [field for field in truck_required if not truck_data.get(field)]
    if missing_truck:
        raise CarrierCreationError(
            f"Truck missing required fields: {', '.join(missing_truck)}"
        )


def _create_carrier(carrier_data: Dict, created_by: Any) -> Carrier:
    carrier = Carrier.objects.create(
        name=carrier_data["name"],
        mc_number=carrier_data["mc_number"],
        dot_number=carrier_data["dot_number"],
        carrier_type=carrier_data["carrier_type"],
        primary_contact_name=carrier_data["primary_contact_name"],
        primary_phone=carrier_data["primary_phone"],
        primary_email=carrier_data["primary_email"],
        address_line1=carrier_data["address_line1"],
        address_line2=carrier_data.get("address_line2", ""),
        city=carrier_data["city"],
        state=carrier_data["state"],
        zip_code=carrier_data["zip_code"],
        notes=carrier_data.get("notes", ""),
        carrier_has_insurance=carrier_data.get("carrier_has_insurance", True),
        created_by=created_by,
    )
    carrier.full_clean()
    return carrier


def _create_driver(carrier: Carrier, driver_data: Dict) -> Driver:
    driver = Driver.objects.create(
        carrier=carrier,
        first_name=driver_data["first_name"],
        last_name=driver_data["last_name"],
        phone=driver_data["phone"],
        email=driver_data.get("email", ""),
        cdl_number=driver_data["cdl_number"],
        cdl_expiration=driver_data.get("cdl_expiration"),
        hos_cycle=driver_data.get("hos_cycle", "60_7"),
        current_status=driver_data.get("current_status", Driver.DriverStatus.AVAILABLE),
        notes=driver_data.get("notes", ""),
    )
    driver.full_clean()
    return driver


def _create_truck(carrier: Carrier, truck_data: Dict) -> Truck:
    truck = Truck.objects.create(
        carrier=carrier,
        truck_number=truck_data["truck_number"],
        equipment_type=truck_data["equipment_type"],
        trailer_number=truck_data.get("trailer_number", ""),
        vin=truck_data.get("vin", ""),
        license_plate=truck_data["license_plate"],
        chassis_no=truck_data.get("chassis_no", ""),
        current_status=truck_data.get("current_status", Truck.TruckStatus.AVAILABLE),
        truck_has_insurance=truck_data.get("truck_has_insurance", True),
        notes=truck_data.get("notes", ""),
    )
    truck.full_clean()
    return truck
