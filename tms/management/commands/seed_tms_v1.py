# tms/management/commands/seed_tms_v1.py

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from tms.models import (
    Broker,
    Carrier,
    Driver,
    Facility,
    Load,
    LoadDocument,
    LoadStop,
    Truck,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Seed TMS V1 data (up to Load creation + Stops)."

    def handle(self, *args, **options):
        # -----------------------------
        # USERS
        # -----------------------------
        dispatcher, _ = User.objects.get_or_create(
            username="dispatcher1",
            defaults={"email": "dispatcher1@test.com", "role": "dispatcher"},
        )
        dispatcher.set_password("test1234")
        dispatcher.save()

        tracker, _ = User.objects.get_or_create(
            username="tracker1",
            defaults={"email": "tracker1@test.com", "role": "tracking_agent"},
        )
        tracker.set_password("test1234")
        tracker.save()

        self.stdout.write(self.style.SUCCESS("✅ Users created/updated"))
        self.stdout.write("  dispatcher1 / test1234")
        self.stdout.write("  tracker1 / test1234")

        # -----------------------------
        # BROKERS
        # -----------------------------
        broker1, _ = Broker.objects.get_or_create(
            mc_number="MC-BRK-1001",
            defaults={
                "name": "Acme Brokerage",
                "primary_contact_name": "John Broker",
                "primary_phone": "555-1001",
                "primary_email": "broker@acme.com",
            },
        )

        broker2, _ = Broker.objects.get_or_create(
            mc_number="MC-BRK-1002",
            defaults={
                "name": "BlueSky Logistics",
                "primary_contact_name": "Sara Broker",
                "primary_phone": "555-1002",
                "primary_email": "broker@bluesky.com",
            },
        )

        # -----------------------------
        # FACILITIES
        # -----------------------------
        shipper, _ = Facility.objects.get_or_create(
            name="Shipper Warehouse Dallas",
            defaults={
                "facility_type": Facility.FacilityType.SHIPPER,
                "address_line1": "100 Shipper St",
                "address_line2": "",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75001",
                "contact_name": "Dock Manager",
                "phone": "555-2001",
                "appointment_required": True,
                "hours_of_operation": "Mon-Fri 8am-5pm",
            },
        )

        receiver, _ = Facility.objects.get_or_create(
            name="Receiver DC Chicago",
            defaults={
                "facility_type": Facility.FacilityType.RECEIVER,
                "address_line1": "500 Receiver Ave",
                "address_line2": "",
                "city": "Chicago",
                "state": "IL",
                "zip_code": "60601",
                "contact_name": "Receiving Clerk",
                "phone": "555-2002",
                "appointment_required": True,
                "hours_of_operation": "Mon-Fri 8am-6pm",
            },
        )

        mid_stop, _ = Facility.objects.get_or_create(
            name="Crossdock Memphis",
            defaults={
                "facility_type": Facility.FacilityType.SHIPPER,
                "address_line1": "250 Crossdock Rd",
                "address_line2": "",
                "city": "Memphis",
                "state": "TN",
                "zip_code": "38103",
                "contact_name": "Crossdock",
                "phone": "555-2003",
                "appointment_required": False,
                "hours_of_operation": "24/7",
            },
        )

        # -----------------------------
        # CARRIERS / TRUCKS / DRIVERS
        # -----------------------------
        carrier1, _ = Carrier.objects.get_or_create(
            mc_number="MC-CAR-3001",
            defaults={
                "name": "RoadRunner Transport",
                "dot_number": "DOT-9001",
                "carrier_type": Carrier.CarrierType.COMPANY,
                "primary_contact_name": "Dispatch Desk",
                "primary_phone": "555-3001",
                "primary_email": "dispatch@roadrunner.com",
                "address_line1": "10 Fleet Blvd",
                "address_line2": "",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75001",
                "created_by": dispatcher,
            },
        )

        truck1, _ = Truck.objects.get_or_create(
            carrier=carrier1,
            truck_number="TRK-101",
            defaults={
                "trailer_number": "TRL-9001",
                "vin": "1HGBH41JXMN109186",
                "license_plate": "TX-ABCD-101",
                "equipment_type": Truck.EquipmentType.DRY_VAN,
                "length_feet": 53,
                "current_status": Truck.TruckStatus.AVAILABLE,
                "current_location_city": "Dallas",
                "current_location_state": "TX",
                "last_location_update": timezone.now(),
            },
        )

        driver1, _ = Driver.objects.get_or_create(
            cdl_number="CDL-7001",
            defaults={
                "carrier": carrier1,
                "first_name": "Mike",
                "last_name": "Driver",
                "phone": "555-4001",
                "email": "mike.driver@test.com",
                "cdl_expiration": timezone.now()
                .date()
                .replace(year=timezone.now().year + 1),
                "hos_cycle": "70_8",
                "current_truck": truck1,
            },
        )

        # -----------------------------
        # LOADS + STOPS
        # -----------------------------
        Load.objects.filter(load_id__in=["LD-10001", "LD-10002"]).delete()

        load1 = Load.objects.create(
            load_id="LD-10001",
            broker=broker1,
            commodity_type="Electronics",
            weight=12000,
            rate=2500.00,
            miles=920,
            commission_type=Load.PaymentMethod.PERCENTAGE,
            dispatcher_commission=85.00,
            carrier=carrier1,
            truck=truck1,
            driver=driver1,
            status=Load.Status.BOOKED,
            dispatcher=dispatcher,
            remarks="Seeded load for testing create/load_detail.",
        )

        LoadStop.objects.create(
            load=load1,
            facility=shipper,
            stop_type=LoadStop.StopType.PICKUP,
            sequence=1,
            appointment_type="appt",
            appt_start=timezone.now().replace(
                hour=10, minute=0, second=0, microsecond=0
            ),
            appt_end=timezone.now().replace(hour=12, minute=0, second=0, microsecond=0),
            status=LoadStop.StopStatus.PENDING,
        )

        LoadStop.objects.create(
            load=load1,
            facility=receiver,
            stop_type=LoadStop.StopType.DELIVERY,
            sequence=2,
            appointment_type="appt",
            appt_start=timezone.now().replace(
                hour=18, minute=0, second=0, microsecond=0
            ),
            appt_end=timezone.now().replace(hour=20, minute=0, second=0, microsecond=0),
            status=LoadStop.StopStatus.PENDING,
        )

        # Multi-stop example
        load2 = Load.objects.create(
            load_id="LD-10002",
            broker=broker2,
            commodity_type="Furniture",
            weight=18000,
            rate=3200.00,
            miles=1100,
            commission_type=Load.PaymentMethod.FIXED,
            dispatcher_commission=300.00,
            carrier=carrier1,
            truck=truck1,
            driver=driver1,
            status=Load.Status.BOOKED,
            dispatcher=dispatcher,
            remarks="Multi-stop sample load.",
        )

        LoadStop.objects.create(
            load=load2,
            facility=shipper,
            stop_type=LoadStop.StopType.PICKUP,
            sequence=1,
            appointment_type="appt",
            appt_start=timezone.now().replace(
                hour=9, minute=0, second=0, microsecond=0
            ),
        )
        LoadStop.objects.create(
            load=load2,
            facility=mid_stop,
            stop_type=LoadStop.StopType.DELIVERY,
            sequence=2,
            appointment_type="fcfs",
        )
        LoadStop.objects.create(
            load=load2,
            facility=receiver,
            stop_type=LoadStop.StopType.DELIVERY,
            sequence=3,
            appointment_type="appt",
            appt_start=timezone.now().replace(
                hour=19, minute=0, second=0, microsecond=0
            ),
        )

        self.stdout.write(
            self.style.SUCCESS("✅ Seed data created (up to load creation workflow)")
        )
