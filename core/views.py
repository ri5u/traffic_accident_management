from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import services
from .forms import (
    BlockageForm,
    ClearBlockageForm,
    DispatchForm,
    ExtendBlockageForm,
    IncidentFilterForm,
    IncidentForm,
    ResolveIncidentForm,
    SavedRouteForm,
    SignUpForm,
    UserAdminForm,
)
from .models import (
    AuditLog,
    Blockage,
    Confirmation,
    Incident,
    InvalidTransition,
    Notification,
    SavedRoute,
    Subscription,
    User,
    Zone,
)

CITIZEN = User.Role.CITIZEN
AUTHORITY = User.Role.FIELD_AUTHORITY
DESK = User.Role.DESK_ADMIN
ALL_ROLES = (CITIZEN, AUTHORITY, DESK)


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #
def role_required(*roles):
    """Login required + user.role must be one of ``roles`` (403 otherwise)."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied("Your role does not have access to this page.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _action(request, fn, *args, success=None, **kwargs):
    """Run a service call, turning domain errors into flash messages."""
    try:
        result = fn(*args, **kwargs)
    except (InvalidTransition, services.PermissionDenied, ValueError) as exc:
        messages.error(request, str(exc))
        return None, False
    if success:
        messages.success(request, success)
    return result, True


def _back(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    from django.utils.http import url_has_allowed_host_and_scheme

    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback)


# --------------------------------------------------------------------------- #
# Public
# --------------------------------------------------------------------------- #
def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    stats = {
        "active_incidents": Incident.objects.active().count(),
        "active_blockages": Blockage.objects.current().count(),
        "zones": Zone.objects.count(),
    }
    return render(request, "core/home.html", {"stats": stats})


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        services.audit(user, "user.signed_up", user)
        login(request, user)
        messages.success(request, "Welcome! Subscribe to zones to receive alerts.")
        return redirect("zone_list")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def dashboard(request):
    return redirect({CITIZEN: "citizen_dashboard", AUTHORITY: "authority_dashboard", DESK: "control_room"}[request.user.role])


# --------------------------------------------------------------------------- #
# Dashboards
# --------------------------------------------------------------------------- #
@role_required(CITIZEN)
def citizen_dashboard(request):
    user = request.user
    subs = user.subscriptions.select_related("zone")
    zones = Zone.objects.all()

    # Location: browser geolocation (lat/lng in querystring) → chosen zone → first subscribed zone.
    origin, origin_label = None, ""
    try:
        lat, lng = float(request.GET["lat"]), float(request.GET["lng"])
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            origin, origin_label = (lat, lng), "your current location"
    except (KeyError, ValueError):
        pass
    selected_zone = None
    if origin is None:
        zone_id = request.GET.get("zone")
        selected_zone = zones.filter(pk=zone_id).first() if zone_id and zone_id.isdigit() else None
        selected_zone = selected_zone or (subs[0].zone if subs else zones.first())
        if selected_zone:
            origin, origin_label = (selected_zone.center_lat, selected_zone.center_lng), f"centre of {selected_zone}"

    nearby = services.nearby_incidents(*origin)[:15] if origin else []
    context = {
        "my_reports": user.reported_incidents.select_related("zone")[:10],
        "subscriptions": subs,
        "nearby": nearby,
        "origin": origin,
        "origin_label": origin_label,
        "zones": zones,
        "selected_zone": selected_zone,
        "radius_km": settings.TAMS["NEARBY_RADIUS_KM"],
        "route_status": services.blocked_routes_for(user),
    }
    return render(request, "core/dashboard_citizen.html", context)


@role_required(AUTHORITY)
def authority_dashboard(request):
    user = request.user
    my_zones = user.assigned_zones.all()
    zone_filter = Q(zone__in=my_zones) if my_zones else Q()
    incidents = (
        Incident.objects.open().filter(zone_filter).select_related("zone", "reporter", "assigned_to")
        .order_by("status", "-created_at")
    )
    blockages = Blockage.objects.current().filter(zone_filter).select_related("zone", "set_by")
    context = {
        "my_zones": my_zones,
        "incidents": incidents,
        "my_assigned": user.assigned_incidents.filter(status=Incident.Status.ASSIGNED).select_related("zone"),
        "blockages": blockages,
        "needs_reconfirm": blockages.filter(status=Blockage.Status.NEEDS_RECONFIRMATION),
        "blockage_form": BlockageForm(officer=user, initial={"zone": my_zones.first()}),
        "resolve_form": ResolveIncidentForm(),
    }
    return render(request, "core/dashboard_authority.html", context)


@role_required(DESK)
def control_room(request):
    status_counts = {row["status"]: row["n"] for row in Incident.objects.values("status").annotate(n=Count("id"))}
    statuses = [(value, label, status_counts.get(value, 0)) for value, label in Incident.Status.choices]
    blockage_counts = {row["status"]: row["n"] for row in Blockage.objects.values("status").annotate(n=Count("id"))}
    zone_rows = Zone.objects.prefetch_related("officers").annotate(
        open_incidents=Count("incidents", filter=~Q(incidents__status=Incident.Status.RESOLVED), distinct=True),
        current_blockages=Count("blockages", filter=~Q(blockages__status=Blockage.Status.CLEARED), distinct=True),
        subscribers=Count("subscriptions", distinct=True),
    )
    context = {
        "statuses": statuses,
        "blockage_counts": [(v, l, blockage_counts.get(v, 0)) for v, l in Blockage.Status.choices],
        "zone_rows": zone_rows,
        "unassigned": Incident.objects.filter(status=Incident.Status.VERIFIED).select_related("zone")[:10],
        "audit": AuditLog.objects.select_related("actor")[:15],
        "users": User.objects.order_by("role", "username")[:12],
        "user_count": User.objects.count(),
        "dispatch_form": DispatchForm(),
    }
    return render(request, "core/control_room.html", context)


# --------------------------------------------------------------------------- #
# Incidents
# --------------------------------------------------------------------------- #
@login_required
def incident_list(request):
    form = IncidentFilterForm(request.GET or None)
    qs = Incident.objects.select_related("zone", "reporter", "assigned_to")
    if form.is_valid():
        d = form.cleaned_data
        if d["status"]:
            qs = qs.filter(status=d["status"])
        if d["type"]:
            qs = qs.filter(type=d["type"])
        if d["zone"]:
            qs = qs.filter(zone=d["zone"])
        if d["q"]:
            qs = qs.filter(description__icontains=d["q"])
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "core/incident_list.html", {"form": form, "page": page, "params": params.urlencode()})


@login_required
def incident_detail(request, pk):
    incident = get_object_or_404(Incident.objects.select_related("zone", "reporter", "assigned_to", "resolved_by"), pk=pk)
    user = request.user
    my_kinds = set(incident.confirmations.filter(user=user).values_list("kind", flat=True))
    context = {
        "incident": incident,
        "confirmations": incident.confirmations.select_related("user"),
        "my_kinds": my_kinds,
        "can_confirm": incident.is_open and incident.reporter_id != user.pk,
        "threshold": settings.TAMS["VERIFICATION_THRESHOLD"],
        "resolve_form": ResolveIncidentForm(),
        "dispatch_form": DispatchForm(),
        "history": AuditLog.objects.filter(target_type="incident", target_id=incident.pk).select_related("actor"),
        "blockages": incident.blockages.select_related("zone"),
    }
    return render(request, "core/incident_detail.html", context)


@login_required
def incident_create(request):
    form = IncidentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        incident = services.report_incident(
            request.user, type=d["type"], lat=d["lat"], lng=d["lng"], zone=d["zone"],
            description=d["description"], photo=d.get("photo"),
        )
        messages.success(request, f"Incident #{incident.pk} reported. Others nearby can now confirm it.")
        return redirect(incident)
    zones = list(Zone.objects.values("id", "name", "center_lat", "center_lng", "radius_m"))
    return render(request, "core/incident_form.html", {"form": form, "zones": zones})


@require_POST
@login_required
def incident_confirm(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    kind = request.POST.get("kind")
    if kind not in Confirmation.Kind.values:
        messages.error(request, "Unknown confirmation type.")
        return redirect(incident)
    result, ok = _action(request, services.confirm_incident, incident, request.user, kind)
    if ok:
        _conf, created = result
        if created:
            messages.success(request, "Thanks — your confirmation was recorded.")
        else:
            messages.info(request, "You already sent that confirmation.")
    return _back(request, incident.get_absolute_url())


@require_POST
@role_required(AUTHORITY, DESK)
def incident_verify(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    _action(request, services.verify_incident, incident, request.user, reason="manual", success="Incident verified.")
    return _back(request, incident.get_absolute_url())


@require_POST
@role_required(AUTHORITY, DESK)
def incident_assign(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    if request.user.is_field_authority:
        officer = request.user
    else:
        form = DispatchForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose an officer to dispatch.")
            return _back(request, incident.get_absolute_url())
        officer = form.cleaned_data["officer"]
    _action(request, services.assign_incident, incident, officer, request.user,
            success=f"Incident #{incident.pk} assigned to {officer.username}.")
    return _back(request, incident.get_absolute_url())


@require_POST
@role_required(AUTHORITY)
def incident_resolve(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    form = ResolveIncidentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid resolution.")
        return _back(request, incident.get_absolute_url())
    _action(request, services.resolve_incident, incident, request.user,
            outcome=form.cleaned_data["outcome"], note=form.cleaned_data["note"],
            success=f"Incident #{incident.pk} resolved.")
    return _back(request, incident.get_absolute_url())


# --------------------------------------------------------------------------- #
# Blockages
# --------------------------------------------------------------------------- #
@login_required
def blockage_list(request):
    show = request.GET.get("show", "current")
    qs = Blockage.objects.select_related("zone", "set_by", "cleared_by")
    if show == "current":
        qs = qs.current()
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "core/blockage_list.html", {"page": page, "show": show})


@login_required
def blockage_detail(request, pk):
    blockage = get_object_or_404(Blockage.objects.select_related("zone", "set_by", "cleared_by", "related_incident"), pk=pk)
    context = {
        "blockage": blockage,
        "extend_form": ExtendBlockageForm(),
        "clear_form": ClearBlockageForm(),
        "history": AuditLog.objects.filter(target_type="blockage", target_id=blockage.pk).select_related("actor"),
    }
    return render(request, "core/blockage_detail.html", context)


@role_required(AUTHORITY)
def blockage_create(request):
    initial = {}
    if request.GET.get("incident", "").isdigit():
        inc = Incident.objects.filter(pk=request.GET["incident"]).first()
        if inc:
            initial = {"related_incident": inc, "zone": inc.zone, "reason": f"{inc.get_type_display()}: {inc.description[:200]}"}
    form = BlockageForm(request.POST or None, officer=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        blockage, ok = _action(
            request, services.create_blockage, request.user, zone=d["zone"], reason=d["reason"],
            severity=d["severity"], expected_end=d["expected_end"], related_incident=d.get("related_incident"),
            success="Blockage recorded and subscribers notified.",
        )
        if ok:
            return redirect(blockage)
    return render(request, "core/blockage_form.html", {"form": form})


@require_POST
@role_required(AUTHORITY)
def blockage_extend(request, pk):
    blockage = get_object_or_404(Blockage, pk=pk)
    form = ExtendBlockageForm(request.POST)
    if form.is_valid():
        _action(request, services.extend_blockage, blockage, request.user, form.cleaned_data["expected_end"],
                note=form.cleaned_data["note"], success="Blockage re-confirmed / extended.")
    else:
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
    return _back(request, blockage.get_absolute_url())


@require_POST
@role_required(AUTHORITY)
def blockage_clear(request, pk):
    blockage = get_object_or_404(Blockage, pk=pk)
    form = ClearBlockageForm(request.POST)
    note = form.cleaned_data["note"] if form.is_valid() else ""
    _action(request, services.clear_blockage, blockage, request.user, note=note, success="Blockage cleared.")
    return _back(request, blockage.get_absolute_url())


# --------------------------------------------------------------------------- #
# Zones & subscriptions
# --------------------------------------------------------------------------- #
@login_required
def zone_list(request):
    zones = Zone.objects.annotate(
        open_incidents=Count("incidents", filter=Q(incidents__status__in=Incident.ACTIVE_STATUSES), distinct=True),
        current_blockages=Count("blockages", filter=~Q(blockages__status=Blockage.Status.CLEARED), distinct=True),
    )
    subscribed = set(request.user.subscriptions.values_list("zone_id", flat=True))
    return render(request, "core/zone_list.html", {"zones": zones, "subscribed": subscribed})


@require_POST
@login_required
def zone_subscribe(request, pk):
    zone = get_object_or_404(Zone, pk=pk)
    sub, created = Subscription.objects.get_or_create(user=request.user, zone=zone)
    if created:
        services.audit(request.user, "subscription.created", zone)
        messages.success(request, f"Subscribed to {zone}. You will be alerted about verified incidents and blockages.")
    else:
        sub.delete()
        services.audit(request.user, "subscription.deleted", zone)
        messages.info(request, f"Unsubscribed from {zone}.")
    return _back(request, reverse("zone_list"))


# --------------------------------------------------------------------------- #
# Notifications (polling, no websockets)
# --------------------------------------------------------------------------- #
@login_required
def notifications(request):
    qs = request.user.notifications.select_related("incident", "blockage")
    if request.GET.get("filter") == "unread":
        qs = qs.unread()
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "core/notifications.html", {"page": page, "filter": request.GET.get("filter", "")})


@require_POST
@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(n.target_url)


@require_POST
@login_required
def notifications_mark_all(request):
    updated = request.user.notifications.unread().update(read_at=timezone.now())
    messages.success(request, f"Marked {updated} notification(s) as read.")
    return _back(request, reverse("notifications"))


@require_GET
def api_notifications(request):
    """Polled every 30s by base.html. Returns unread count + latest unread items."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication required"}, status=401)
    unread = request.user.notifications.unread()
    latest = [
        {"id": n.id, "kind": n.kind, "message": n.message, "created_at": n.created_at.isoformat()}
        for n in unread[:5]
    ]
    return JsonResponse({"unread": unread.count(), "latest": latest})


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
@login_required
def map_view(request):
    return render(request, "core/map.html")


@login_required
@require_GET
def api_map_data(request):
    include_resolved = request.GET.get("resolved") == "1"
    inc_qs = Incident.objects.select_related("zone")
    if not include_resolved:
        inc_qs = inc_qs.open()
    incidents = [
        {
            "id": i.id, "type": i.type, "type_label": i.get_type_display(), "status": i.status,
            "status_label": i.get_status_display(), "lat": i.lat, "lng": i.lng, "zone": i.zone.name,
            "description": i.description[:160], "created_at": i.created_at.isoformat(),
            "fresh": i.is_fresh, "url": i.get_absolute_url(),
        }
        for i in inc_qs[:500]
    ]
    blockages = [
        {
            "id": b.id, "zone": b.zone.name, "lat": b.zone.center_lat, "lng": b.zone.center_lng,
            "radius_m": b.zone.radius_m, "severity": b.severity, "severity_label": b.get_severity_display(),
            "status": b.status, "status_label": b.get_status_display(), "reason": b.reason,
            "expected_end": b.expected_end.isoformat(), "url": b.get_absolute_url(),
        }
        for b in Blockage.objects.current().select_related("zone")
    ]
    zones = list(Zone.objects.values("id", "name", "center_lat", "center_lng", "radius_m"))
    routes = [{"name": r.name, "points": r.points} for r in request.user.saved_routes.all()]
    return JsonResponse({"incidents": incidents, "blockages": blockages, "zones": zones, "routes": routes})


# --------------------------------------------------------------------------- #
# Desk Admin: audit log & users
# --------------------------------------------------------------------------- #
@role_required(DESK)
def audit_log(request):
    qs = AuditLog.objects.select_related("actor")
    action = request.GET.get("action", "")
    actor = request.GET.get("actor", "")
    target = request.GET.get("target_type", "")
    if action:
        qs = qs.filter(action=action)
    if actor == "system":
        qs = qs.filter(actor__isnull=True)
    elif actor:
        qs = qs.filter(actor__username=actor)
    if target:
        qs = qs.filter(target_type=target)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    context = {
        "page": page,
        "actions": AuditLog.objects.order_by("action").values_list("action", flat=True).distinct(),
        "target_types": AuditLog.objects.order_by("target_type").values_list("target_type", flat=True).distinct(),
        "f": {"action": action, "actor": actor, "target_type": target},
        "params": params.urlencode(),
    }
    return render(request, "core/audit_log.html", context)


@role_required(DESK)
def user_list(request):
    qs = User.objects.prefetch_related("assigned_zones").annotate(
        n_reports=Count("reported_incidents", distinct=True), n_confirmations=Count("confirmations", distinct=True)
    )
    role = request.GET.get("role", "")
    if role:
        qs = qs.filter(role=role)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    return render(request, "core/user_list.html", {"users": qs.order_by("role", "username"), "roles": User.Role.choices, "role": role, "q": q})


@role_required(DESK)
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    before = {"role": target.role, "is_active": target.is_active, "reputation_score": target.reputation_score,
              "zones": sorted(target.assigned_zones.values_list("name", flat=True))}
    form = UserAdminForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        if target.pk == request.user.pk and (form.cleaned_data["role"] != DESK or not form.cleaned_data["is_active"]):
            messages.error(request, "You cannot demote or deactivate your own account.")
        else:
            user = form.save()
            after = {"role": user.role, "is_active": user.is_active, "reputation_score": user.reputation_score,
                     "zones": sorted(user.assigned_zones.values_list("name", flat=True))}
            changes = {k: [before[k], after[k]] for k in before if before[k] != after[k]}
            services.audit(request.user, "user.updated", user, changes=changes)
            messages.success(request, f"Updated {user.username}.")
            return redirect("user_list")
    return render(request, "core/user_form.html", {"form": form, "target": target})


# --------------------------------------------------------------------------- #
# Stretch: saved routes (trip-intent filter)
# --------------------------------------------------------------------------- #
@login_required
def route_list(request):
    return render(request, "core/route_list.html", {"route_status": services.blocked_routes_for(request.user)})


@login_required
def route_create(request):
    form = SavedRouteForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        route = form.save()
        services.audit(request.user, "route.created", route, points=len(route.points))
        messages.success(request, f"Route '{route.name}' saved.")
        return redirect("route_list")
    zones = list(Zone.objects.values("id", "name", "center_lat", "center_lng", "radius_m"))
    return render(request, "core/route_form.html", {"form": form, "zones": zones})


@require_POST
@login_required
def route_delete(request, pk):
    route = get_object_or_404(SavedRoute, pk=pk, user=request.user)
    route.delete()
    messages.info(request, "Route deleted.")
    return redirect("route_list")
