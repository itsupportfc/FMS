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

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from .views import (
    accessorial_charge_type_fields,
    active_loads,
    broker_create,
    broker_edit,
    brokers_list,
    carrier_create,
    carrier_edit,
    carriers_list,
    change_status,
    create_accessorial,
    create_duty_log_view,
    create_load,
    create_load_note,
    create_reschedule_request,
    create_tracking_update,
    dashboard,
    delete_document,
    driver_create,
    driver_edit,
    driver_hos_summary,
    drivers_list,
    edit_accessorial,
    edit_reschedule_approvals,
    facilities_list,
    facility_create,
    facility_edit,
    load_carrier_assets,
    load_detail,
    load_lock_ping,
    load_lock_release,
    load_lock_takeover,
    load_stop_row,
    loads_list,
    my_loads,
    my_loads_export_excel,
    owner_operator_create,
    owner_operator_edit,
    owner_operators_list,
    search_brokers,
    search_facilities,
    stop_edit,
    truck_create,
    truck_edit,
    trucks_list,
    upload_document,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    # entity detail routes
    path("facilities/", facilities_list, name="facilities_list"),
    path("facilities/create/", facility_create, name="facilities_create"),
    path("brokers/", brokers_list, name="brokers_list"),
    path("brokers/create/", broker_create, name="brokers_create"),
    path("carriers/", carriers_list, name="carriers_list"),
    path("carriers/create/", carrier_create, name="carriers_create"),
    path("owner-operators/", owner_operators_list, name="owner_operators_list"),
    path(
        "owner-operators/create/",
        owner_operator_create,
        name="owner_operators_create",
    ),
    path("drivers/", drivers_list, name="drivers_list"),
    path("drivers/create/", driver_create, name="drivers_create"),
    path("trucks/", trucks_list, name="trucks_list"),
    path("trucks/create/", truck_create, name="trucks_create"),
    # edit routes
    path("facilities/<int:pk>/edit/", facility_edit, name="facility_edit"),
    path("brokers/<int:pk>/edit/", broker_edit, name="broker_edit"),
    path("carriers/<int:pk>/edit/", carrier_edit, name="carrier_edit"),
    path(
        "owner-operators/<int:pk>/edit/",
        owner_operator_edit,
        name="owner_operator_edit",
    ),
    path("drivers/<int:pk>/edit/", driver_edit, name="driver_edit"),
    path("trucks/<int:pk>/edit/", truck_edit, name="truck_edit"),
    # Specific load routes BEFORE the catch-all <str:load_id>/ route
    path("loads/carrier-assets/", load_carrier_assets, name="load-carrier-assets"),
    path("loads/active/", active_loads, name="active_loads"),
    path("loads/create/", create_load, name="create_load"),
    path("loads/stops/row/", load_stop_row, name="load_stop_row"),
    path("loads/search-brokers/", search_brokers, name="search_brokers"),
    path("loads/search-facilities/", search_facilities, name="search_facilities"),
    # Stop tracking - traditional form approach
    path("stops/<int:stop_id>/edit/", stop_edit, name="stop_edit"),
    path(
        "loads/<str:load_id>/hos/add/",
        create_duty_log_view,
        name="create_duty_log",
    ),
    path("loads/<str:load_id>/lock/ping/", load_lock_ping, name="load_lock_ping"),
    path(
        "loads/<str:load_id>/lock/takeover/",
        load_lock_takeover,
        name="load_lock_takeover",
    ),
    path(
        "loads/<str:load_id>/lock/release/",
        load_lock_release,
        name="load_lock_release",
    ),
    path("loads/<str:load_id>/notes/", create_load_note, name="create_load_note"),
    path(
        "drivers/<int:driver_id>/hos-summary/",
        driver_hos_summary,
        name="driver_hos_summary",
    ),
    path("loads/<str:load_id>/upload/", upload_document, name="upload_document"),
    path(
        "loads/<str:load_id>/documents/<int:doc_id>/delete/",
        delete_document,
        name="delete_document",
    ),
    path(
        "loads/<str:load_id>/tracking-update/",
        create_tracking_update,
        name="create_tracking_update",
    ),
    path(
        "loads/<str:load_id>/reschedule/new/",
        create_reschedule_request,
        name="create_reschedule_request",
    ),
    path(
        "loads/<str:load_id>/reschedule/<int:request_id>/edit/",
        edit_reschedule_approvals,
        name="edit_reschedule_approvals",
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
    # HTMX partial, to get accessorial charge type fields dynamically
    path(
        "accessorials/charge-type-fields/",
        accessorial_charge_type_fields,
        name="accessorial_charge_type_fields",
    ),
    path("loads/<str:load_id>/<str:action>/", change_status, name="change_status"),
    path("loads/<str:load_id>/", load_detail, name="load_detail"),
    # List views
    path("loads/", loads_list, name="loads_list"),
    path("my-loads/", my_loads, name="my_loads"),
    path("my-loads/export/", my_loads_export_excel, name="my_loads_export_excel"),
]
