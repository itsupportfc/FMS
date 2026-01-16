"""Factories for generating demo/test data with factory_boy and Faker.

Use sequences for unique identifiers and Faker for descriptive fields.
"""

import random

import factory
from django.contrib.auth import get_user_model
from factory import Faker
from factory.django import DjangoModelFactory

from . import models


class UserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    role = "dispatcher"
    is_staff = True
    is_active = True

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "password123")
        user = super()._create(model_class, *args, **kwargs)
        user.set_password(password)
        user.save()
        return user


class BrokerFactory(DjangoModelFactory):
    class Meta:
        model = models.Broker

    name = Faker("company")
    mc_number = factory.Sequence(lambda n: f"MC{10000 + n}")
    primary_contact_name = Faker("name")
    primary_phone = factory.Sequence(
        lambda n: f"555-{n % 900 + 100:03d}-{n % 10000:04d}"
    )
    primary_email = Faker("company_email")
    notes = ""
    credit_history = ""
    average_payment_days = 30


class FacilityFactory(DjangoModelFactory):
    class Meta:
        model = models.Facility

    name = Faker("company")
    facility_type = factory.LazyFunction(
        lambda: random.choice(models.Facility.FacilityType.values)
    )
    address_line1 = Faker("street_address")
    address_line2 = ""
    city = Faker("city")
    state = Faker("state_abbr")
    zip_code = Faker("postcode")
    contact_name = Faker("name")
    phone = factory.Sequence(lambda n: f"555-{n % 900 + 100:03d}-{n % 10000:04d}")
    appointment_required = True
    hours_of_operation = "24/7"
    notes = ""


class CarrierFactory(DjangoModelFactory):
    class Meta:
        model = models.Carrier

    name = Faker("company")
    mc_number = factory.Sequence(lambda n: f"CMC{20000 + n}")
    dot_number = factory.Sequence(lambda n: f"DOT{30000 + n}")
    carrier_type = models.Carrier.CarrierType.COMPANY
    primary_contact_name = Faker("name")
    primary_phone = factory.Sequence(
        lambda n: f"555-{n % 900 + 100:03d}-{n % 10000:04d}"
    )
    primary_email = Faker("company_email")
    address_line1 = Faker("street_address")
    address_line2 = ""
    city = Faker("city")
    state = Faker("state_abbr")
    zip_code = Faker("postcode")
    notes = ""
    carrier_has_insurance = True
    created_by = factory.SubFactory(UserFactory)


class TruckFactory(DjangoModelFactory):
    class Meta:
        model = models.Truck

    carrier = factory.SubFactory(CarrierFactory)
    truck_number = factory.Sequence(lambda n: f"TRK{n:04d}")
    trailer_number = factory.Sequence(lambda n: f"TRL{n:04d}")
    vin = factory.Sequence(lambda n: f"1HGBH41JXMN{100000 + n}")
    license_plate = factory.Sequence(lambda n: f"PLT{1000 + n}")
    equipment_type = models.Truck.EquipmentType.DRY_VAN
    length_feet = 53
    chassis_no = ""
    current_status = models.Truck.TruckStatus.AVAILABLE
    current_location_city = Faker("city")
    current_location_state = Faker("state_abbr")
    truck_has_insurance = True
    notes = ""


class DriverFactory(DjangoModelFactory):
    class Meta:
        model = models.Driver

    carrier = factory.SubFactory(CarrierFactory)
    first_name = Faker("first_name")
    last_name = Faker("last_name")
    phone = factory.Sequence(lambda n: f"555-{n % 900 + 100:03d}-{n % 10000:04d}")
    email = factory.LazyAttribute(
        lambda obj: f"{obj.first_name.lower()}.{obj.last_name.lower()}@driver.test"
    )
    cdl_number = factory.Sequence(lambda n: f"CDL{40000 + n}")
    hos_cycle = "60_7"
    is_short_haul_exempt = False
    current_truck = None
    notes = ""
