"""Seed demo data for brokers, carriers, trucks, drivers, and facilities."""

import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from factory import random as factory_random
from faker import Faker

from tms import factories


class Command(BaseCommand):
    help = "Seed demo data for brokers, carriers, trucks, drivers, and facilities"

    def add_arguments(self, parser):
        parser.add_argument("--brokers", type=int, default=5)
        parser.add_argument("--carriers", type=int, default=5)
        parser.add_argument("--trucks-per-carrier", type=int, default=2)
        parser.add_argument("--drivers-per-carrier", type=int, default=3)
        parser.add_argument("--facilities", type=int, default=8)
        parser.add_argument(
            "--seed", type=int, default=None, help="Seed for Faker/random"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        seed = options.get("seed")
        if seed is not None:
            random.seed(seed)
            factory_random.reseed_random(seed)
            Faker.seed(seed)
            self.stdout.write(self.style.NOTICE(f"Seeding randomness with seed={seed}"))

        brokers = options["brokers"]
        carriers = options["carriers"]
        trucks_per_carrier = options["trucks_per_carrier"]
        drivers_per_carrier = options["drivers_per_carrier"]
        facilities = options["facilities"]

        dispatcher = self._get_or_create_user("dispatcher", role="dispatcher")
        tracker = self._get_or_create_user("tracker", role="tracker")
        self.stdout.write(
            self.style.SUCCESS(
                f"Using users: {dispatcher.username}, {tracker.username}"
            )
        )

        self.stdout.write("Creating brokers...")
        brokers_created = factories.BrokerFactory.create_batch(brokers)

        self.stdout.write("Creating facilities...")
        facilities_created = factories.FacilityFactory.create_batch(facilities)

        self.stdout.write("Creating carriers with trucks and drivers...")
        carriers_created = []
        for _ in range(carriers):
            carrier = factories.CarrierFactory(created_by=dispatcher)
            carriers_created.append(carrier)
            factories.TruckFactory.create_batch(trucks_per_carrier, carrier=carrier)
            factories.DriverFactory.create_batch(drivers_per_carrier, carrier=carrier)

        self.stdout.write(self.style.SUCCESS("Seed complete."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Brokers: {len(brokers_created)}, Facilities: {len(facilities_created)}, "
                f"Carriers: {len(carriers_created)}, Trucks: {carriers * trucks_per_carrier}, "
                f"Drivers: {carriers * drivers_per_carrier}"
            )
        )

    def _get_or_create_user(self, username: str, role: str):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "role": role,
                "is_staff": True,
            },
        )
        if created:
            user.set_password("password123")
            user.save()
        return user
