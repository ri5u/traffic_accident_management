from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/signup/", views.signup, name="signup"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/citizen/", views.citizen_dashboard, name="citizen_dashboard"),
    path("dashboard/field/", views.authority_dashboard, name="authority_dashboard"),
    path("dashboard/control-room/", views.control_room, name="control_room"),

    path("incidents/", views.incident_list, name="incident_list"),
    path("incidents/report/", views.incident_create, name="incident_create"),
    path("incidents/<int:pk>/", views.incident_detail, name="incident_detail"),
    path("incidents/<int:pk>/confirm/", views.incident_confirm, name="incident_confirm"),
    path("incidents/<int:pk>/verify/", views.incident_verify, name="incident_verify"),
    path("incidents/<int:pk>/assign/", views.incident_assign, name="incident_assign"),
    path("incidents/<int:pk>/resolve/", views.incident_resolve, name="incident_resolve"),

    path("blockages/", views.blockage_list, name="blockage_list"),
    path("blockages/new/", views.blockage_create, name="blockage_create"),
    path("blockages/<int:pk>/", views.blockage_detail, name="blockage_detail"),
    path("blockages/<int:pk>/extend/", views.blockage_extend, name="blockage_extend"),
    path("blockages/<int:pk>/clear/", views.blockage_clear, name="blockage_clear"),

    path("zones/", views.zone_list, name="zone_list"),
    path("zones/<int:pk>/subscribe/", views.zone_subscribe, name="zone_subscribe"),

    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:pk>/open/", views.notification_open, name="notification_open"),
    path("notifications/mark-all-read/", views.notifications_mark_all, name="notifications_mark_all"),

    path("map/", views.map_view, name="map"),

    path("control-room/audit/", views.audit_log, name="audit_log"),
    path("control-room/users/", views.user_list, name="user_list"),
    path("control-room/users/<int:pk>/", views.user_edit, name="user_edit"),

    path("routes/", views.route_list, name="route_list"),
    path("routes/new/", views.route_create, name="route_create"),
    path("routes/<int:pk>/delete/", views.route_delete, name="route_delete"),

    path("api/notifications/", views.api_notifications, name="api_notifications"),
    path("api/map-data/", views.api_map_data, name="api_map_data"),
]
