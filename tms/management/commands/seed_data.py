# tms/management/commands/seed_data.py
"""
Seed data for local development (including Loads).

Run:
    python manage.py seed_data
    python manage.py seed_data --reset --loads 400 --brokers 40 --facilities 80 --carriers 25

Creates:
- Users + Groups (Dispatcher, Tracker, Accounts, Manager)
- Brokers, Facilities, Carriers (+ Trucks + Drivers)
- Loads across statuses with consistent rules:
  - booked_no_rc
  - booked_has_rc_not_ready
  - booked_ready_to_handover (RC + assignment + stops but still BOOKED)
  - dispatched (handover_to_tracking ran)
  - in_transit (start_transit ran + tracking updates)
  - delivered (delivery stops completed + POD/BOL + mark_delivered ran)
  - completed (complete_load ran)
  - cancelled (cancel_load ran)
"""

from __future__ import annotations

import random
import string
from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tms.models import (
    Accessorial,
    Broker,
    Carrier,
    Driver,
    Facility,
    Handover,
    Load,
    LoadDocument,
    LoadStop,
    TrackingUpdate,
    Truck,
)
from tms.services.cancel import cancel_load
from tms.services.completion import complete_load
from tms.services.delivery import mark_delivered
from tms.services.exceptions import ServiceError
from tms.services.handover import handover_to_tracking
from tms.services.transit import start_transit

# ---------------------------
# Helpers
# ---------------------------

STATES = [
    "CA",
    "TX",
    "FL",
    "IL",
    "GA",
    "NC",
    "NJ",
    "PA",
    "OH",
    "AZ",
    "WA",
    "CO",
    "MI",
    "TN",
    "VA",
]
CITIES = [
    "Los Angeles",
    "Dallas",
    "Houston",
    "Miami",
    "Chicago",
    "Atlanta",
    "Charlotte",
    "Phoenix",
    "Seattle",
    "Denver",
    "Columbus",
    "Detroit",
    "Nashville",
    "Richmond",
    "Newark",
]

BROKER_NAME_LEFT = [
    "Blue",
    "Prime",
    "Eagle",
    "Rapid",
    "Summit",
    "Metro",
    "Coastal",
    "Iron",
    "Northstar",
]
BROKER_NAME_RIGHT = [
    "Logistics",
    "Freight",
    "Transport",
    "Brokerage",
    "Carriers",
    "Shipping",
    "Solutions",
]

FACILITY_BRANDS = [
    "Amazon",
    "Walmart",
    "Costco",
    "Target",
    "Sysco",
    "P&G",
    "Tesla",
    "FedEx",
    "Home Depot",
    "Lowes",
]
FACILITY_TYPES = ["DC", "FC", "Warehouse", "Plant", "Crossdock", "Hub"]

CARRIER_LEFT = [
    "Iron",
    "Pioneer",
    "Lone Star",
    "Evergreen",
    "Keystone",
    "Atlas",
    "Canyon",
    "Liberty",
    "Pacific",
]
CARRIER_RIGHT = ["Trucking", "Transport", "Haulage", "Freight", "Express", "Logistics"]


def _rand_phone() -> str:
    return f"+1{random.randint(200, 999)}{random.randint(200, 999)}{random.randint(1000, 9999)}"


def _rand_state() -> str:
    return random.choice(STATES)


def _rand_city() -> str:
    return random.choice(CITIES)


def _slug(n: int, prefix: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{n:04d}-{suffix}"


def _random_vin() -> str:
    alphabet = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"  # exclude I,O,Q
    return "".join(random.choices(alphabet, k=17))


def _fake_doc_bytes(title: str) -> bytes:
    # Not a real PDF, but fine for dev FileField content.
    return f"{title}\nSeeded for dev.\n".encode("utf-8")


def _now_minus(days: int = 0, hours: int = 0) -> timezone.datetime:
    return timezone.now() - timedelta(days=days, hours=hours)


def _pick_one(qs):
    return qs.order_by("?").first()


def _chunked(iterable: Iterable, size: int):
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


# ---------------------------
# Command
# ---------------------------


class Command(BaseCommand):
    help = "Seed demo data for TMS (master data + loads across statuses)."

    def add_arguments(self, parser):
        # master data
        parser.add_argument("--brokers", type=int, default=25)
        parser.add_argument("--carriers", type=int, default=15)
        parser.add_argument("--drivers-per-carrier", type=int, default=5)
        parser.add_argument("--trucks-per-carrier", type=int, default=4)
        parser.add_argument("--facilities", type=int, default=40)

        # users
        parser.add_argument("--dispatchers", type=int, default=2)
        parser.add_argument("--trackers", type=int, default=2)
        parser.add_argument("--accounts", type=int, default=1)
        parser.add_argument("--managers", type=int, default=1)

        # loads
        parser.add_argument("--loads", type=int, default=200)
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing non-superuser users + ALL tms data before seeding.",
        )
        parser.add_argument("--batch", type=int, default=200)

    def handle(self, *args, **opts):
        User = get_user_model()

        # Ensure groups exist
        group_names = ["Dispatcher", "Tracker", "Accounts", "Manager"]
        groups = {
            name: Group.objects.get_or_create(name=name)[0] for name in group_names
        }

        if opts["reset"]:
            self._reset_all(User)

        # Users
        self._create_users(
            User=User,
            groups=groups,
            dispatchers=opts["dispatchers"],
            trackers=opts["trackers"],
            accounts=opts["accounts"],
            managers=opts["managers"],
        )

        dispatcher = (
            User.objects.filter(groups__name="Dispatcher").first()
            or User.objects.filter(is_superuser=True).first()
        )
        tracker = User.objects.filter(groups__name="Tracker").first() or dispatcher
        manager = User.objects.filter(groups__name="Manager").first() or dispatcher

        # Master data
        self._create_brokers(count=opts["brokers"])
        self._create_facilities(count=opts["facilities"])
        self._create_carriers_with_assets(
            count=opts["carriers"],
            drivers_per_carrier=opts["drivers_per_carrier"],
            trucks_per_carrier=opts["trucks_per_carrier"],
            created_by=manager,
        )

        # Loads
        total = int(opts["loads"])
        batch = int(opts["batch"])

        created_total = 0
        for chunk in _chunked(range(1, total + 1), batch):
            with transaction.atomic():
                created_total += self._create_loads(
                    count=len(chunk),
                    seq_start=chunk[0],
                    dispatcher=dispatcher,
                    tracker=tracker,
                    manager=manager,
                )

        self.stdout.write(
            self.style.SUCCESS(f"Seeding complete. Loads created: {created_total}")
        )

    # ---------------------------
    # Reset
    # ---------------------------

    def _reset_all(self, User):
        # Delete child tables first
        TrackingUpdate.objects.all().delete()
        Handover.objects.all().delete()
        Accessorial.objects.all().delete()
        LoadDocument.objects.all().delete()
        LoadStop.objects.all().delete()
        Load.objects.all().delete()

        Driver.objects.all().delete()
        Truck.objects.all().delete()
        Carrier.objects.all().delete()
        Facility.objects.all().delete()
        Broker.objects.all().delete()

        deleted_count, _ = User.objects.filter(is_superuser=False).delete()
        self.stdout.write(
            self.style.WARNING(
                f"[reset] Deleted {deleted_count} non-superuser users and all TMS data."
            )
        )

    # ---------------------------
    # Users
    # ---------------------------

    def _create_users(self, User, groups, dispatchers, trackers, accounts, managers):
        def set_if_field(obj, field: str, value):
            try:
                obj._meta.get_field(field)
            except Exception:
                return
            setattr(obj, field, value)

        def make_user(username, email, first_name, last_name, group):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_active": True,
                },
            )
            # Optional fields on your custom User
            set_if_field(user, "phone", _rand_phone())
            # If you still use a role field anywhere, keep it consistent
            role_map = {
                "Dispatcher": "dispatcher",
                "Tracker": "tracking_agent",
                "Accounts": "accounts",
                "Manager": "manager",
            }
            set_if_field(user, "role", role_map.get(group.name))

            if created:
                user.set_password("password123")
                user.save()
            else:
                user.save()  # persist optional fields if present

            user.groups.add(group)
            return user

        for i in range(1, dispatchers + 1):
            make_user(
                f"dispatcher{i}",
                f"dispatcher{i}@example.com",
                f"Dispatch{i}",
                "User",
                groups["Dispatcher"],
            )

        for i in range(1, trackers + 1):
            make_user(
                f"tracker{i}",
                f"tracker{i}@example.com",
                f"Tracker{i}",
                "User",
                groups["Tracker"],
            )

        for i in range(1, accounts + 1):
            make_user(
                f"accounts{i}",
                f"accounts{i}@example.com",
                f"Accounts{i}",
                "User",
                groups["Accounts"],
            )

        for i in range(1, managers + 1):
            make_user(
                f"manager{i}",
                f"manager{i}@example.com",
                f"Manager{i}",
                "User",
                groups["Manager"],
            )

    # ---------------------------
    # Master data
    # ---------------------------

    def _create_brokers(self, count: int):
        created = 0
        for i in range(1, count + 1):
            mc_number = f"MC{80000 + i}"
            name = f"{random.choice(BROKER_NAME_LEFT)} {random.choice(BROKER_NAME_RIGHT)} {_slug(i, 'BRK')}"
            _obj, was_created = Broker.objects.get_or_create(
                mc_number=mc_number,
                defaults={
                    "name": name,
                    "primary_contact_name": f"{random.choice(['Sam', 'Alex', 'Jordan', 'Taylor', 'Casey'])} {random.choice(['Miller', 'Davis', 'Lopez', 'Singh', 'Patel'])}",
                    "primary_phone": _rand_phone(),
                    "primary_email": f"broker{i}@example.com",
                    "notes": "Seeded broker for dev testing.",
                    "credit_history": "Pays within terms.",
                    "average_payment_days": round(random.uniform(18, 45), 1),
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} brokers."))

    def _create_facilities(self, count: int):
        created = 0
        for i in range(1, count + 1):
            facility_type = (
                Facility.FacilityType.SHIPPER
                if i % 2 == 0
                else Facility.FacilityType.RECEIVER
            )
            name = f"{random.choice(FACILITY_BRANDS)} {random.choice(FACILITY_TYPES)} {_slug(i, 'FAC')}"

            _obj, was_created = Facility.objects.get_or_create(
                name=name,
                defaults={
                    "facility_type": facility_type,
                    "address_line1": f"{random.randint(100, 9999)} {random.choice(['Main', 'Industrial', 'Logistics', 'Dock', 'Freight'])} St",
                    "address_line2": "",
                    "city": _rand_city(),
                    "state": _rand_state(),
                    "zip_code": f"{random.randint(10000, 99999)}",
                    "contact_name": f"{random.choice(['Pat', 'Riley', 'Morgan', 'Jamie', 'Chris'])} {random.choice(['Brown', 'Wilson', 'Garcia', 'Nguyen', 'Khan'])}",
                    "phone": _rand_phone(),
                    "appointment_required": random.choice([True, True, False]),
                    "hours_of_operation": random.choice(
                        ["Mon-Fri 8am-5pm", "24/7", "Mon-Sat 6am-6pm"]
                    ),
                    "notes": "Seeded facility for dev testing.",
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} facilities."))

    def _create_carriers_with_assets(
        self, count: int, drivers_per_carrier: int, trucks_per_carrier: int, created_by
    ):
        carriers_created = drivers_created = trucks_created = 0

        for i in range(1, count + 1):
            carrier, created = Carrier.objects.get_or_create(
                mc_number=f"MC{90000 + i}",
                defaults={
                    "name": f"{random.choice(CARRIER_LEFT)} {random.choice(CARRIER_RIGHT)} {_slug(i, 'CAR')}",
                    "dot_number": f"DOT{91000 + i}",
                    "carrier_type": Carrier.CarrierType.COMPANY,
                    "primary_contact_name": f"{random.choice(['Ava', 'Noah', 'Mia', 'Liam', 'Zoe'])} {random.choice(['Smith', 'Johnson', 'Clark', 'Martin', 'Lee'])}",
                    "primary_phone": _rand_phone(),
                    "primary_email": f"carrier{i}@example.com",
                    "address_line1": f"{random.randint(10, 999)} {random.choice(['Logistics', 'Terminal', 'Carrier'])} Blvd",
                    "address_line2": "",
                    "city": _rand_city(),
                    "state": _rand_state(),
                    "zip_code": f"{random.randint(10000, 99999)}",
                    "notes": "Seeded carrier for dev testing.",
                    "carrier_has_insurance": True,
                    "created_by": created_by,
                    "commission_type": Carrier.CommissionType.PERCENTAGE,
                    "commission_value": Decimal(
                        str(random.choice([7.5, 10, 12.5, 15]))
                    ),
                },
            )
            if created:
                carriers_created += 1

            # trucks
            for t in range(1, trucks_per_carrier + 1):
                truck_no = f"T{carrier.id or i:03d}{t:03d}{random.randint(10, 99)}"
                Truck.objects.get_or_create(
                    carrier=carrier,
                    truck_number=truck_no,
                    defaults={
                        "trailer_number": f"TR{random.randint(10000, 99999)}",
                        "vin": _random_vin(),
                        "license_plate": f"{random.choice(STATES)}{random.randint(1000, 9999)}",
                        "equipment_type": random.choice(
                            [c[0] for c in Truck.EquipmentType.choices]
                        ),
                        "length_feet": random.choice([48, 53]),
                        "chassis_no": f"CH{random.randint(10000, 99999)}",
                        "current_status": Truck.TruckStatus.AVAILABLE,
                        "current_location_city": _rand_city(),
                        "current_location_state": _rand_state(),
                        "last_location_update": _now_minus(days=random.randint(0, 10)),
                        "truck_has_insurance": True,
                        "notes": "Seeded truck",
                    },
                )
                trucks_created += 1

            # drivers
            for d in range(1, drivers_per_carrier + 1):
                cdl = f"CDL{carrier.id or i:03d}{d:03d}{random.randint(1000, 9999)}"
                Driver.objects.get_or_create(
                    carrier=carrier,
                    cdl_number=cdl,
                    defaults={
                        "first_name": random.choice(
                            [
                                "John",
                                "Mike",
                                "Sara",
                                "Priya",
                                "Luis",
                                "Chen",
                                "Omar",
                                "Nina",
                                "Ishaan",
                            ]
                        ),
                        "last_name": random.choice(
                            [
                                "Davis",
                                "Thompson",
                                "Reed",
                                "Singh",
                                "Patel",
                                "Garcia",
                                "Khan",
                                "Smith",
                            ]
                        ),
                        "phone": _rand_phone(),
                        "email": f"driver_{carrier.id or i}_{d}@example.com",
                        "cdl_expiration": (
                            timezone.now().date()
                            + timedelta(days=random.randint(180, 1200))
                        ),
                        "hos_cycle": random.choice(["60_7", "70_8"]),
                        "current_truck": None,
                        "current_status": Driver.DriverStatus.AVAILABLE,
                        "notes": "Seeded driver",
                    },
                )
                drivers_created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {carriers_created} carriers."))
        self.stdout.write(self.style.SUCCESS(f"Created {trucks_created} trucks."))
        self.stdout.write(self.style.SUCCESS(f"Created {drivers_created} drivers."))

    # ---------------------------
    # Loads
    # ---------------------------

    def _create_loads(
        self, count: int, seq_start: int, dispatcher, tracker, manager
    ) -> int:
        brokers = Broker.objects.all()
        facilities = Facility.objects.all()
        carriers = Carrier.objects.all()

        if not brokers.exists() or not facilities.exists() or not carriers.exists():
            self.stdout.write(
                self.style.ERROR("Missing master data (brokers/facilities/carriers).")
            )
            return 0

        created = 0

        # Status bucket distribution
        buckets = [
            ("booked_no_rc", 0.15),
            ("booked_has_rc_not_ready", 0.10),
            ("booked_ready_to_handover", 0.15),
            ("dispatched", 0.15),
            ("in_transit", 0.20),
            ("delivered", 0.15),
            ("completed", 0.07),
            ("cancelled", 0.03),
        ]

        for n in range(seq_start, seq_start + count):
            broker = _pick_one(brokers)
            carrier = _pick_one(carriers)

            # Choose stops (2..4)
            stop_count = random.choice([2, 2, 3, 4])
            stop_facilities = list(facilities.order_by("?")[:stop_count])

            planned_eta = timezone.now() + timedelta(hours=random.randint(6, 120))

            # Create BOOKED base load
            load_id = f"LD-{timezone.now().strftime('%y%m%d')}-{_slug(n, 'L')}"
            load = Load.objects.create(
                load_id=load_id,
                broker=broker,
                dispatcher=dispatcher,
                status=Load.Status.BOOKED,
                commodity_type=random.choice(
                    ["General Freight", "Food", "Electronics", "Paper", "Auto Parts"]
                ),
                weight=random.choice([12000, 18000, 24000, 36000, 42000]),
                miles=random.choice([250, 420, 780, 1200, 1650]),
                deadhead_miles=random.choice([0, 25, 50, 90, 140]),
                rate=Decimal(str(random.choice([1200, 1500, 1800, 2200, 3000, 4200]))),
                planned_eta=planned_eta,
            )

            # Stops: ensure first is pickup and last is delivery
            for i, fac in enumerate(stop_facilities, start=1):
                if i == 1:
                    stop_type = LoadStop.StopType.PICKUP
                elif i == stop_count:
                    stop_type = LoadStop.StopType.DELIVERY
                else:
                    stop_type = random.choice(
                        [LoadStop.StopType.PICKUP, LoadStop.StopType.DELIVERY]
                    )

                appt_type = random.choice(["fcfs", "fcfs", "appt"])
                appt_start = appt_end = None
                if appt_type == "appt":
                    appt_start = timezone.now() + timedelta(hours=random.randint(1, 36))
                    appt_end = appt_start + timedelta(hours=random.choice([2, 4, 6]))

                LoadStop.objects.create(
                    load=load,
                    facility=fac,
                    stop_type=stop_type,
                    sequence=i,
                    appointment_type=appt_type,
                    appt_start=appt_start,
                    appt_end=appt_end,
                    status=LoadStop.StopStatus.PENDING,
                )

            # Select bucket
            r = random.random()
            cumulative = 0.0
            bucket = buckets[0][0]
            for name, p in buckets:
                cumulative += p
                if r <= cumulative:
                    bucket = name
                    break

            if bucket == "booked_no_rc":
                created += 1
                continue

            # Attach RC
            self._attach_load_doc(
                load, LoadDocument.DocumentType.RC, f"RC_{load.load_id}.txt"
            )

            if bucket == "booked_has_rc_not_ready":
                # Intentionally leave assignment empty -> can_handover False
                created += 1
                continue

            # For remaining buckets, we want assignment + can_handover True
            truck = (
                Truck.objects.filter(
                    carrier=carrier, current_status=Truck.TruckStatus.AVAILABLE
                )
                .order_by("?")
                .first()
            )
            driver = (
                Driver.objects.filter(
                    carrier=carrier, current_status=Driver.DriverStatus.AVAILABLE
                )
                .order_by("?")
                .first()
            )

            if not truck or not driver:
                # Not enough assets; keep as RC uploaded but not ready
                created += 1
                continue

            # Assign to load (still BOOKED until services run)
            load.carrier = carrier
            load.truck = truck
            load.driver = driver
            load.dispatched_at = timezone.now() - timedelta(hours=random.randint(1, 72))
            load.save()

            if bucket == "booked_ready_to_handover":
                created += 1
                continue

            # DISPATCHED+
            try:
                handover_to_tracking(
                    load=load,
                    tracking_agent=tracker,
                    from_agent=dispatcher,
                    instructions=random.choice(
                        [
                            "Check in every 2 hours",
                            "Strict ETA updates required",
                            "Receiver is appointment only; confirm day-of",
                            "Do not arrive before appointment window",
                        ]
                    ),
                )
            except ServiceError:
                created += 1
                continue

            if bucket == "dispatched":
                created += 1
                continue

            # IN_TRANSIT+
            try:
                start_transit(load)
            except ServiceError:
                created += 1
                continue

            self._create_tracking_updates(load, tracker, count=random.randint(2, 6))

            # Add a few accessorials to create approval edge-cases
            if random.random() < 0.35:
                self._maybe_create_accessorial(
                    load, created_by=tracker, manager=manager
                )

            if bucket == "in_transit":
                created += 1
                continue

            # DELIVERED / COMPLETED: mark delivery stops completed + docs POD/BOL
            self._complete_delivery_stops(load)

            self._attach_load_doc(
                load, LoadDocument.DocumentType.POD, f"POD_{load.load_id}.txt"
            )
            self._attach_load_doc(
                load, LoadDocument.DocumentType.BOL, f"BOL_{load.load_id}.txt"
            )

            try:
                mark_delivered(load)
            except ServiceError:
                created += 1
                continue

            if bucket == "delivered":
                created += 1
                continue

            if bucket == "completed":
                try:
                    complete_load(load)
                except ServiceError:
                    pass
                created += 1
                continue

            if bucket == "cancelled":
                # Cancel a dispatched/in_transit load sometimes; or cancel directly after dispatched
                try:
                    # sometimes bring it back to DISPATCHED for realistic "cancel before pickup"
                    if random.choice([True, False]):
                        Load.objects.filter(pk=load.pk).update(
                            status=Load.Status.DISPATCHED,
                            cancelled_at=None,
                            delivered_at=None,
                            completed_at=None,
                        )
                        load.refresh_from_db()
                    cancel_load(
                        load,
                        reason=random.choice(
                            [
                                "Customer canceled",
                                "No freight ready",
                                "Truck breakdown",
                                "Broker rebooked",
                            ]
                        ),
                    )
                except ServiceError:
                    pass
                created += 1
                continue

            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} loads in this batch."))
        return created

    # ---------------------------
    # Child record helpers
    # ---------------------------

    def _attach_load_doc(self, load: Load, doc_type: str, filename: str):
        content = ContentFile(
            _fake_doc_bytes(f"{doc_type} for {load.load_id}"), name=filename
        )
        LoadDocument.objects.create(
            load=load,
            document_type=doc_type,
            file=content,
            original_filename=filename,
            description=f"Seeded {doc_type} doc",
        )

    def _complete_delivery_stops(self, load: Load):
        now = timezone.now()
        for stop in load.stops.filter(stop_type=LoadStop.StopType.DELIVERY):
            stop.status = LoadStop.StopStatus.COMPLETED
            stop.arrived_at = now - timedelta(hours=random.randint(3, 12))
            stop.departed_at = stop.arrived_at + timedelta(
                hours=random.choice([1, 2, 3, 5])
            )
            stop.save(
                update_fields=["status", "arrived_at", "departed_at", "updated_at"]
            )

    def _create_tracking_updates(self, load: Load, tracker_user, count: int):
        methods = [c[0] for c in TrackingUpdate.TrackingMethod.choices]
        delay_reasons = [c[0] for c in TrackingUpdate.RescheduleReason.choices]

        for i in range(count):
            is_delayed = random.random() < 0.25
            new_eta = None
            delay_reason = ""
            if is_delayed:
                delay_reason = random.choice(delay_reasons)
                if load.planned_eta:
                    new_eta = load.planned_eta + timedelta(
                        hours=random.choice([1, 2, 4, 6])
                    )
                else:
                    new_eta = timezone.now() + timedelta(
                        hours=random.choice([4, 6, 10])
                    )

            tu = TrackingUpdate.objects.create(
                load=load,
                tracking_agent=tracker_user,
                current_location=f"{_rand_city()}, {_rand_state()}",
                tracking_method=random.choice(methods),
                is_delayed=is_delayed,
                delay_reason=delay_reason,
                new_eta=new_eta,
                notes=random.choice(
                    [
                        "Driver confirmed rolling.",
                        "Stopped for fuel.",
                        "Traffic near metro; monitoring.",
                        "Facility slow; updated ETA.",
                        "Driver rest break; next check-call scheduled.",
                        "No issues; on track.",
                    ]
                ),
            )

            # Backdate created_at for realism (BaseModel auto_now_add)
            created_at = timezone.now() - timedelta(
                hours=(count - i) * random.randint(1, 4)
            )
            TrackingUpdate.objects.filter(pk=tu.pk).update(created_at=created_at)

    def _maybe_create_accessorial(self, load: Load, created_by, manager):
        charge_types = [c[0] for c in Accessorial.ChargeType.choices]
        charge_type = random.choice(charge_types)

        amount = None
        if random.random() < 0.6:
            amount = Decimal(str(random.choice([50, 75, 100, 150, 250, 300])))

        acc = Accessorial.objects.create(
            load=load,
            charge_type=charge_type,
            amount=amount,
            description="Seeded accessorial for workflow testing.",
            manager_approved=random.choice([False, True]),
            broker_approved=random.choice([False, True]),
            created_by=created_by,
        )

        # If detention, add times
        if charge_type == Accessorial.ChargeType.DETENTION:
            start = timezone.now() - timedelta(hours=random.randint(6, 36))
            end = start + timedelta(hours=random.choice([1, 2, 3, 4, 6]))
            acc.detention_start = start
            acc.detention_end = end
            acc.detention_billed_hours = Decimal(
                str(round((end - start).total_seconds() / 3600.0, 2))
            )
            acc.save(
                update_fields=[
                    "detention_start",
                    "detention_end",
                    "detention_billed_hours",
                    "updated_at",
                ]
            )
