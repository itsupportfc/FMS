from decimal import Decimal

import factory
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from factory.declarations import LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from factory.faker import Faker

import tms.models as tms_models


class BrokerFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.Broker

    name = Faker("company")
    mc_number = Faker("bothify", text="MC#####")  # max_length=20
    primary_contact_name = Faker("first_name")
    primary_phone = Faker("bothify", text="555-####")
    primary_email = Faker("company_email")


class CarrierFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.Carrier

    name = Faker("company")
    mc_number = Faker("bothify", text="MC#####")  # max_length=20
    dot_number = Faker("bothify", text="DOT#####")  # max_length=20
    carrier_type = "company"
    primary_contact_name = Faker("first_name")
    primary_phone = Faker("bothify", text="555-####")
    primary_email = Faker("company_email")
    address_line1 = Faker("bothify", text="123 Main St")
    city = Faker("city")
    state = Faker("bothify", text="IL")  # max_length=2
    zip_code = Faker("bothify", text="60601")  # max_length=10


class FacilityFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.Facility

    name = Faker("company")
    facility_type = "shipper"
    address_line1 = Faker("bothify", text="123 Main St")
    city = Faker("city")
    state = Faker("bothify", text="IL")  # max_length=2
    zip_code = Faker("bothify", text="60601")  # max_length=10
    contact_name = Faker("first_name")
    phone = Faker("bothify", text="555-####")


class DriverFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.Driver

    carrier = SubFactory(CarrierFactory)
    first_name = Faker("first_name")
    last_name = Faker("last_name")
    phone = Faker("phone_number")
    cdl_number = Faker("bothify", text="CDL#####")
    hos_cycle = "60_7"


class TruckFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.Truck

    carrier = SubFactory(CarrierFactory)
    truck_number = Faker("bothify", text="TRK-####")
    license_plate = Faker("bothify", text="P-#####")
    equipment_type = "dry_van"


class UserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()

    email = Faker("company_email")
    first_name = Faker("first_name")
    last_name = Faker("last_name")
    username = Faker("user_name")
    role = "dispatcher"


class LoadFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.Load

    load_id = Faker("bothify", text="LOAD-####")
    broker = SubFactory(BrokerFactory)
    pickup_facility = SubFactory(FacilityFactory, facility_type="shipper")
    delivery_facility = SubFactory(FacilityFactory, facility_type="receiver")
    dispatcher = SubFactory(UserFactory)
    status = "booked"


class DocumentFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.LoadDocument

    load = SubFactory(LoadFactory)
    document_type = "RC"
    file = factory.django.FileField(filename="test.pdf")
    original_filename = "test.pdf"
    description = "Test document"


class RescheduleRequestFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.RescheduleRequest

    load = SubFactory(LoadFactory)
    original_appointment = LazyAttribute(lambda o: timezone.now())
    new_appointment = LazyAttribute(
        lambda o: timezone.now() + timezone.timedelta(days=1)
    )
    reason = tms_models.RescheduleRequest.RescheduleReason.SHIPPER_DELAY
    consignee_approved = False
    broker_approved = False
    manager_approved = False
    remarks = "Test reschedule"
    created_by = SubFactory(UserFactory)


class DutyLogFactory(DjangoModelFactory):
    class Meta:
        model = tms_models.DutyLog

    driver = SubFactory(DriverFactory)
    truck = SubFactory(TruckFactory)
    load = SubFactory(LoadFactory)
    status = tms_models.DutyLog.DutyStatus.DRIVING
    start_time = LazyAttribute(lambda o: timezone.now())
    end_time = LazyAttribute(lambda o: timezone.now() + timezone.timedelta(hours=2))


@pytest.fixture
def broker_factory():
    return BrokerFactory


@pytest.fixture
def carrier_factory():
    return CarrierFactory


@pytest.fixture
def facility_factory():
    return FacilityFactory


@pytest.fixture
def driver_factory():
    return DriverFactory


@pytest.fixture
def truck_factory():
    return TruckFactory


@pytest.fixture
def load_factory():
    return LoadFactory


@pytest.fixture
def user_factory():
    return UserFactory


@pytest.fixture
def accessorial_factory(load_factory, user_factory):
    def make_accessorial(**kwargs):
        load = kwargs.pop("load", load_factory())
        created_by = kwargs.pop("created_by", load.dispatcher)
        defaults = dict(
            load=load,
            charge_type=tms_models.Accessorial.ChargeType.DETENTION,
            amount=Decimal("100.00"),
            description="Test accessorial",
            manager_approved=False,
            broker_approved=False,
            created_by=created_by,
        )
        defaults.update(kwargs)
        return tms_models.Accessorial.objects.create(**defaults)

    return make_accessorial


@pytest.fixture
def document_factory():
    return DocumentFactory


@pytest.fixture
def reschedule_request_factory():
    return RescheduleRequestFactory


@pytest.fixture
def duty_log_factory():
    return DutyLogFactory
