"""
URL routing for TMS (Transportation Management System) app.

Pattern: Simple, RESTful-ish URLs
WHY: Easy to remember, predictable structure.

URL Design Philosophy:
- /loads/ → list all loads
- /loads/create/ → create new load
- /loads/"123-ABC"/ → view/edit specific load
- /loads/"123-ABC"/upload/ → upload document to load "123-ABC"
- /loads/"123-ABC"/handover/ → perform handover action on load "123-ABC"

Future: Can convert to REST API with Django REST Framework
by keeping same URL structure.
"""

from django.urls import path

from .views import (
    accessorial_charge_type_fields,
    active_loads,
    carriers_list,
    change_status,
    create_accessorial,
    create_duty_log_view,
    create_load,
    create_reschedule_request,
    create_tracking_update,
    dashboard,
    driver_hos_summary,
    drivers_list,
    edit_accessorial,
    load_carrier_assets,
    load_detail,
    loads_list,
    update_reschedule_approvals,
    upload_document,
)

urlpatterns = [
    path("dashboard/", dashboard, name="dashboard"),
    # Specific load routes BEFORE the catch-all <str:load_id>/ route
    path("loads/carrier-assets/", load_carrier_assets, name="load-carrier-assets"),
    path("loads/active/", active_loads, name="active_loads"),
    path("loads/create/", create_load, name="create_load"),
    path(
        "loads/<str:load_id>/hos/add/",
        create_duty_log_view,
        name="create_duty_log",
    ),
    path(
        "drivers/<int:driver_id>/hos-summary/",
        driver_hos_summary,
        name="driver_hos_summary",
    ),
    path("loads/<str:load_id>/upload/", upload_document, name="upload_document"),
    path(
        "loads/<str:load_id>/tracking-update/",
        create_tracking_update,
        name="create_tracking_update",
    ),
    path(
        "loads/<str:load_id>/reschedule/",
        create_reschedule_request,
        name="create_reschedule_request",
    ),
    path(
        "loads/<str:load_id>/reschedule/<int:request_id>/approvals/",
        update_reschedule_approvals,
        name="update_reschedule_approvals",
    ),
    path(
        "loads/<str:load_id>/accessorial/new",
        create_accessorial,
        name="create_accessorial",
    ),
    path(
        "loads/<str:load_id>/accessorial/<int:pk>/edit/",
        edit_accessorial,
        name="edit_accessorial",
    ),
    # HTMX partial
    path(
        "accessorials/charge-type-fields/",
        accessorial_charge_type_fields,
        name="accessorial_charge_type_fields",
    ),
    path("loads/<str:load_id>/<str:action>/", change_status, name="change_status"),
    path("loads/<str:load_id>/", load_detail, name="load_detail"),
    # List views
    path("loads/", loads_list, name="loads_list"),
    path("carriers/", carriers_list, name="carriers_list"),
    path("drivers/", drivers_list, name="drivers_list"),
]
