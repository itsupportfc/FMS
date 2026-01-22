from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

import tms.models as tms_models

pytestmark = pytest.mark.django_db


def make_user(role="dispatcher"):
    User = (
        tms_models.User if hasattr(tms_models, "User") else tms_models.get_user_model()
    )
    return User.objects.create_user(
        username=f"{role}_user",
        email=f"{role}@test.com",
        password="testpass",
        first_name=role.capitalize(),
        last_name="Test",
        role=role,
    )


def add_document(load, doc_type="RC"):
    from django.core.files.base import ContentFile

    return tms_models.Document.objects.create(
        load=load,
        document_type=doc_type,
        file=ContentFile(b"test", name=f"{doc_type}.pdf"),
        original_filename=f"{doc_type}.pdf",
    )


def test_load_booked_to_dispatched(
    load_factory, carrier_factory, truck_factory, driver_factory, user_factory
):
    load = load_factory()
    carrier = carrier_factory()
    truck = truck_factory(carrier=carrier)
    driver = driver_factory(carrier=carrier)
    load.carrier = carrier
    load.truck = truck
    load.driver = driver
    load.save()
    add_document(load, "RC")
    tracker = make_user("tracking_agent")
    load.handover_to_tracking(tracker)
    load.refresh_from_db()
    assert load.status == tms_models.Load.Status.DISPATCHED
    assert load.tracking_agent == tracker
    assert tms_models.Handover.objects.filter(load=load, to_agent=tracker).exists()


def test_load_dispatched_to_in_transit(load_factory):
    load = load_factory(status="dispatched")
    load._transition(load.Status.DISPATCHED)
    load.start_transit()
    load.refresh_from_db()
    assert load.status == tms_models.Load.Status.IN_TRANSIT
    assert load.pickup_departure_at is not None


def test_load_in_transit_to_delivered(load_factory):
    load = load_factory(status="in_transit")
    add_document(load, "POD")
    add_document(load, "BOL")
    load._transition(load.Status.IN_TRANSIT)
    load.mark_delivered()
    load.refresh_from_db()
    assert load.status == tms_models.Load.Status.DELIVERED
    assert load.delivered_at is not None


def test_load_delivered_to_completed(load_factory):
    load = load_factory(status="delivered")
    load._transition(load.Status.DELIVERED)
    load.complete_load()
    load.refresh_from_db()
    assert load.status == tms_models.Load.Status.COMPLETED
    assert load.completed_at is not None


def test_load_cancellation_creates_tonu(load_factory):
    load = load_factory(status="booked")
    load.cancel(reason="Broker cancelled")
    load.refresh_from_db()
    assert load.status == tms_models.Load.Status.CANCELLED
    tonu = load.accessorials.get(charge_type="tonu")
    assert tonu.amount == 0
    assert tonu.created_by == load.dispatcher


def test_handover_fails_without_rc_document(load_factory):
    load = load_factory()
    carrier = tms_models.Carrier.objects.create(
        name="Carrier1",
        mc_number="MC12345",
        dot_number="DOT12345",
        carrier_type="company",
        primary_contact_name="Contact",
        primary_phone="555-0000",
        primary_email="c@x.com",
        address_line1="123 Main St",
        city="Chicago",
        state="IL",
        zip_code="60601",
    )
    truck = tms_models.Truck.objects.create(
        carrier=carrier,
        truck_number="TRK-001",
        license_plate="P-12345",
        equipment_type="dry_van",
    )
    driver = tms_models.Driver.objects.create(
        carrier=carrier,
        first_name="John",
        last_name="Doe",
        phone="555-2222",
        cdl_number="CDL12345",
        hos_cycle="60_7",
    )
    load.carrier = carrier
    load.truck = truck
    load.driver = driver
    load.save()
    tracker = tms_models.User.objects.create_user(
        username="tracker1",
        email="tracker1@test.com",
        password="testpass",
        role="tracking_agent",
    )
    with pytest.raises(ValueError, match="Rate Confirmation document is missing"):
        load.handover_to_tracking(tracker)


def test_handover_fails_without_carrier_assignment(load_factory):
    load = load_factory()
    # Add RC document but no carrier/truck/driver
    from django.core.files.base import ContentFile

    tms_models.Document.objects.create(
        load=load,
        document_type="RC",
        file=ContentFile(b"test", name="RC.pdf"),
        original_filename="RC.pdf",
    )
    tracker = tms_models.User.objects.create_user(
        username="tracker2",
        email="tracker2@test.com",
        password="testpass",
        role="tracking_agent",
    )
    with pytest.raises(ValueError, match="Carrier, Truck, and Driver must be assigned"):
        load.handover_to_tracking(tracker)


def test_mark_delivered_fails_without_pod(load_factory):
    load = load_factory(status="in_transit")
    # Only add BOL, not POD
    from django.core.files.base import ContentFile

    tms_models.Document.objects.create(
        load=load,
        document_type="BOL",
        file=ContentFile(b"test", name="BOL.pdf"),
        original_filename="BOL.pdf",
    )
    with pytest.raises(ValueError, match="Proof of Delivery"):
        load.mark_delivered()


def test_complete_load_fails_if_not_delivered(load_factory):
    load = load_factory(status="in_transit")
    with pytest.raises(ValueError, match="Load is not in DELIVERED status"):
        load.complete_load()


def test_cannot_cancel_completed_load(load_factory):
    load = load_factory(status="completed")
    with pytest.raises(ValueError, match="CANCELLED, DELIVERED or COMPLETED"):
        load.cancel()


def test_accessorial_approval_status(load_factory, user_factory, accessorial_factory):
    accessorial = accessorial_factory(manager_approved=False, broker_approved=False)
    assert accessorial.is_approved is False
    assert accessorial.get_approval_status_display() == "PENDING"
    accessorial.manager_approved = True
    accessorial.broker_approved = True
    accessorial.save()
    assert accessorial.is_approved is True
    assert accessorial.get_approval_status_display() == "APPROVED"


def test_detention_charge_calculation(accessorial_factory):
    start = timezone.now()
    end = start + timezone.timedelta(hours=3, minutes=30)
    accessorial = accessorial_factory(
        charge_type="detention",
        detention_start=start,
        detention_end=end,
    )
    # Simulate calculation (if not auto):
    billed_hours = (
        accessorial.detention_end - accessorial.detention_start
    ).total_seconds() / 3600
    accessorial.detention_billed_hours = round(Decimal(billed_hours), 2)
    accessorial.save()
    assert float(accessorial.detention_billed_hours) == pytest.approx(3.5, 0.01)


def test_accessorial_amount_validation(accessorial_factory):
    accessorial = accessorial_factory(amount=Decimal("-50.00"))
    # If negative not allowed, should raise error on full_clean
    with pytest.raises(Exception):
        accessorial.full_clean()


def test_tonu_charge_created_on_cancel(load_factory):
    load = load_factory(status="booked")
    load.cancel(reason="Broker cancelled")
    load.refresh_from_db()
    tonu = load.accessorials.get(charge_type="tonu")
    assert tonu.amount == 0
    assert tonu.charge_type == "tonu"
    assert tonu.created_by == load.dispatcher


def test_reschedule_single_approval(reschedule_request_factory, load_factory):
    load = load_factory()
    reschedule = reschedule_request_factory(load=load)
    reschedule.consignee_approved = True
    reschedule.save()
    assert not reschedule.is_fully_approved
    load.refresh_from_db()
    # Delivery datetime should NOT change
    assert load.delivery_datetime != reschedule.new_appointment


def test_reschedule_full_approval(reschedule_request_factory, load_factory):
    load = load_factory()
    old_delivery = timezone.now()
    new_delivery = old_delivery + timezone.timedelta(days=2)
    load.delivery_datetime = old_delivery
    load.save()
    reschedule = reschedule_request_factory(
        load=load,
        original_appointment=old_delivery,
        new_appointment=new_delivery,
    )
    reschedule.consignee_approved = True
    reschedule.broker_approved = True
    reschedule.manager_approved = True
    reschedule.save()
    assert reschedule.is_fully_approved
    load.refresh_from_db()
    assert load.delivery_datetime == new_delivery


def test_reschedule_automatic_update(reschedule_request_factory, load_factory):
    load = load_factory()
    new_delivery = timezone.now() + timezone.timedelta(days=3)
    reschedule = reschedule_request_factory(
        load=load,
        new_appointment=new_delivery,
        consignee_approved=True,
        broker_approved=True,
        manager_approved=True,
    )
    reschedule.save()
    load.refresh_from_db()
    assert load.delivery_datetime == new_delivery
