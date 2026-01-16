from django.contrib import admin

from .models import (
    Accessorial,
    # Appointment,
    Broker,
    Carrier,
    Document,
    Driver,
    DutyLog,
    Facility,
    Handover,
    Load,
    RescheduleRequest,
    TrackingUpdate,
    Truck,
)

# Register your models here.
admin.site.register(Broker)
admin.site.register(Facility)
admin.site.register(Carrier)
admin.site.register(Truck)
admin.site.register(Driver)
admin.site.register(Load)
admin.site.register(Accessorial)
admin.site.register(Document)
# admin.site.register(Appointment)
admin.site.register(RescheduleRequest)
admin.site.register(DutyLog)
admin.site.register(TrackingUpdate)
admin.site.register(Handover)
