"""
Business logic for TAMS.

Every state-changing operation goes through a function in this module so that
the audit log, notifications and reputation updates can never be forgotten by
a view. Views stay thin; tests exercise these functions directly.
"""
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .geo import haversine_m, point_to_polyline_m
from .models import (
    AuditLog,
    Blockage,
    Confirmation,
    Incident,
    Notification,
    SavedRoute,
    Subscription,
    User,
)


def _cfg(key):
    return settings.TAMS[key]


class PermissionDenied(Exception):
    pass


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def audit(actor, action, target, **metadata):
    target_type = target.__class__.__name__.lower() if target is not None else ""
    return AuditLog.objects.create(
        actor=actor if (actor is not None and actor.pk) else None,
        action=action,
        target_type=target_type,
        target_id=getattr(target, "pk", None),
        metadata=metadata,
    )


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def notify_zone_subscribers(zone, kind, message, *, incident=None, blockage=None, exclude=None):
    """Create one Notification per subscriber of ``zone`` (geofenced fan-out)."""
    exclude_ids = {u.pk for u in (exclude or []) if u is not None}
    user_ids = (
        Subscription.objects.filter(zone=zone, user__is_active=True)
        .exclude(user_id__in=exclude_ids)
        .values_list("user_id", flat=True)
    )
    rows = [
        Notification(user_id=uid, kind=kind, message=message[:255], incident=incident, blockage=blockage)
        for uid in user_ids
    ]
    Notification.objects.bulk_create(rows)
    return len(rows)


def notify_user(user, kind, message, *, incident=None, blockage=None):
    if user is None:
        return None
    return Notification.objects.create(user=user, kind=kind, message=message[:255], incident=incident, blockage=blockage)


def notify_route_owners(blockage):
    """Stretch feature: alert users whose saved route passes through a new blockage."""
    buffer_m = _cfg("ROUTE_BUFFER_M")
    zone = blockage.zone
    count = 0
    for route in SavedRoute.objects.filter(notify=True).select_related("user"):
        if route.user_id == blockage.set_by_id:
            continue
        d = point_to_polyline_m(zone.center_lat, zone.center_lng, route.points)
        if d <= zone.radius_m + buffer_m:
            notify_user(
                route.user,
                Notification.Kind.ROUTE_BLOCKED,
                f"Your usual route '{route.name}' is affected: {blockage.get_severity_display()} in {zone}.",
                blockage=blockage,
            )
            count += 1
    return count


def blocked_routes_for(user):
    """Return [(route, [blockages on it])] for the user's saved routes."""
    buffer_m = _cfg("ROUTE_BUFFER_M")
    current = list(Blockage.objects.current().select_related("zone"))
    result = []
    for route in user.saved_routes.all():
        hits = [
            b for b in current
            if point_to_polyline_m(b.zone.center_lat, b.zone.center_lng, route.points) <= b.zone.radius_m + buffer_m
        ]
        result.append((route, hits))
    return result


# --------------------------------------------------------------------------- #
# Reputation
# --------------------------------------------------------------------------- #
def _adjust_reputation(user_id, delta):
    if delta:
        User.objects.filter(pk=user_id).update(reputation_score=F("reputation_score") + delta)


def settle_reputation(incident):
    """
    Once an incident is resolved with a known outcome, reward users whose
    signal matched the outcome and penalise those whose signal did not.
      * genuine:      reporter +2, still_active +1, cleared (before resolve) -1
      * false_report: reporter -3, still_active -1, cleared +1
    Field Authority / Desk Admin accounts are not scored.
    """
    if incident.reputation_settled or not incident.outcome:
        return
    genuine = incident.outcome == Incident.Outcome.GENUINE
    match, mismatch = _cfg("REPUTATION_MATCH_DELTA"), _cfg("REPUTATION_MISMATCH_DELTA")

    if incident.reporter.is_citizen:
        _adjust_reputation(
            incident.reporter_id,
            _cfg("REPUTATION_GOOD_REPORT_DELTA") if genuine else _cfg("REPUTATION_FALSE_REPORT_DELTA"),
        )
    for c in incident.confirmations.select_related("user"):
        if not c.user.is_citizen:
            continue
        if c.kind == Confirmation.Kind.STILL_ACTIVE:
            _adjust_reputation(c.user_id, match if genuine else mismatch)
        else:
            # "cleared" on a genuine incident is only wrong if it was claimed
            # while the incident was still being handled (i.e. before resolve
            # and before it was assigned to an officer).
            if genuine:
                if incident.assigned_at and c.created_at < incident.assigned_at:
                    _adjust_reputation(c.user_id, mismatch)
            else:
                _adjust_reputation(c.user_id, match)
    incident.reputation_settled = True
    incident.save(update_fields=["reputation_settled"])


# --------------------------------------------------------------------------- #
# Incident lifecycle
# --------------------------------------------------------------------------- #
@transaction.atomic
def report_incident(reporter, *, type, lat, lng, zone, description, photo=None):
    incident = Incident(
        reporter=reporter, type=type, lat=lat, lng=lng, zone=zone, description=description,
    )
    if photo:
        incident.photo = photo
    incident.refresh_freshness(incident.created_at)
    incident.save()
    audit(reporter, "incident.reported", incident, type=type, zone=zone.name, lat=lat, lng=lng)
    # Authorities/admins reporting are trusted: verify immediately.
    if not reporter.is_citizen:
        verify_incident(incident, actor=reporter, reason="reported by authority")
    return incident


def _verify(incident, actor, reason):
    incident.transition(Incident.Status.VERIFIED)
    now = timezone.now()
    incident.verified_at = incident.verified_at or now
    incident.refresh_freshness(now)
    incident.save()
    audit(actor, "incident.verified", incident, reason=reason, score=incident.still_active_score)
    notify_zone_subscribers(
        incident.zone,
        Notification.Kind.INCIDENT_VERIFIED,
        f"Verified {incident.get_type_display().lower()} in {incident.zone}: {incident.description[:120]}",
        incident=incident,
    )


@transaction.atomic
def verify_incident(incident, actor, reason="manual"):
    """Manual verification by a Field Authority / Desk Admin."""
    if actor is not None and actor.is_citizen:
        raise PermissionDenied("Citizens cannot verify incidents directly.")
    _verify(incident, actor, reason)
    return incident


@transaction.atomic
def confirm_incident(incident, user, kind):
    """
    Record a typed confirmation. Returns (confirmation, created: bool).

    * still_active refreshes freshness, revives stale incidents and may push the
      incident over the (reputation-weighted) verification threshold.
    * cleared may mark a not-yet-assigned incident stale early.
    """
    if not incident.is_open:
        raise PermissionDenied("This incident is already resolved.")
    if incident.reporter_id == user.pk:
        raise PermissionDenied("You cannot confirm your own report.")

    conf, created = Confirmation.objects.get_or_create(
        incident=incident, user=user, kind=kind, defaults={"weight": user.confirmation_weight}
    )
    if not created:
        return conf, False

    audit(user, f"confirmation.{kind}", incident, weight=conf.weight)
    now = timezone.now()

    if kind == Confirmation.Kind.STILL_ACTIVE:
        if incident.status == Incident.Status.STALE:
            incident.transition(Incident.Status.VERIFIED if incident.verified_at else Incident.Status.REPORTED)
            audit(None, "incident.revived", incident, by=user.username)
        if incident.status in Incident.FRESHNESS_STATUSES:
            incident.refresh_freshness(now)
        else:
            incident.last_confirmed_at = now
        incident.save()
        if incident.status == Incident.Status.REPORTED and incident.still_active_score >= _cfg("VERIFICATION_THRESHOLD"):
            _verify(incident, None, reason="confirmation threshold reached")
    else:
        if (incident.status in Incident.FRESHNESS_STATUSES
                and incident.cleared_score >= _cfg("CLEARED_THRESHOLD")
                and incident.cleared_score > incident.still_active_score):
            incident.transition(Incident.Status.STALE)
            incident.expires_at = now
            incident.save()
            audit(None, "incident.stale", incident, reason="community reports cleared")
    return conf, True


@transaction.atomic
def assign_incident(incident, officer, actor):
    if not officer.is_field_authority:
        raise PermissionDenied("Incidents can only be assigned to Field Authority users.")
    if actor.is_citizen:
        raise PermissionDenied("Citizens cannot assign incidents.")
    if actor.is_field_authority and actor.pk != officer.pk:
        raise PermissionDenied("Field Authority users can only assign incidents to themselves.")
    incident.transition(Incident.Status.ASSIGNED)
    incident.assigned_to = officer
    incident.assigned_at = timezone.now()
    if not incident.verified_at:
        incident.verified_at = incident.assigned_at
    incident.save()
    audit(actor, "incident.assigned", incident, officer=officer.username)
    if officer.pk != actor.pk:
        notify_user(officer, Notification.Kind.INCIDENT_ASSIGNED,
                    f"You were dispatched to incident #{incident.pk} in {incident.zone}.", incident=incident)
    return incident


@transaction.atomic
def resolve_incident(incident, actor, outcome=Incident.Outcome.GENUINE, note=""):
    if actor.is_citizen:
        raise PermissionDenied("Citizens cannot resolve incidents.")
    incident.transition(Incident.Status.RESOLVED)
    incident.resolved_at = timezone.now()
    incident.resolved_by = actor
    incident.outcome = outcome
    incident.resolution_note = note
    incident.save()
    audit(actor, "incident.resolved", incident, outcome=outcome, note=note)
    notify_user(incident.reporter, Notification.Kind.INCIDENT_RESOLVED,
                f"Your report #{incident.pk} was resolved ({incident.get_outcome_display().lower()}).",
                incident=incident)
    settle_reputation(incident)
    return incident


# --------------------------------------------------------------------------- #
# Blockage lifecycle
# --------------------------------------------------------------------------- #
def _require_authority(actor):
    if not actor.is_field_authority:
        raise PermissionDenied("Only Field Authority users can manage blockages.")


@transaction.atomic
def create_blockage(actor, *, zone, reason, severity, expected_end, related_incident=None):
    _require_authority(actor)
    now = timezone.now()
    blockage = Blockage(
        zone=zone, set_by=actor, reason=reason, severity=severity, started_at=now,
        expected_end=expected_end, last_verified_at=now, related_incident=related_incident,
    )
    blockage.full_clean()
    blockage.save()
    audit(actor, "blockage.created", blockage, zone=zone.name, severity=severity,
          expected_end=expected_end.isoformat())
    notify_zone_subscribers(
        zone, Notification.Kind.BLOCKAGE_CREATED,
        f"{blockage.get_severity_display()} in {zone}: {reason}", blockage=blockage, exclude=[actor],
    )
    notify_route_owners(blockage)
    return blockage


@transaction.atomic
def extend_blockage(blockage, actor, new_expected_end, note=""):
    """Extend (and implicitly re-confirm) a blockage."""
    _require_authority(actor)
    if new_expected_end <= timezone.now():
        raise ValueError("New expected end must be in the future.")
    old_end = blockage.expected_end
    blockage.transition(Blockage.Status.ACTIVE)
    blockage.expected_end = new_expected_end
    blockage.last_verified_at = timezone.now()
    blockage.save()
    audit(actor, "blockage.extended", blockage, old_expected_end=old_end.isoformat(),
          new_expected_end=new_expected_end.isoformat(), note=note)
    notify_zone_subscribers(
        blockage.zone, Notification.Kind.BLOCKAGE_EXTENDED,
        f"Blockage in {blockage.zone} extended until {timezone.localtime(new_expected_end):%H:%M %b %d}.",
        blockage=blockage, exclude=[actor],
    )
    return blockage


@transaction.atomic
def clear_blockage(blockage, actor, note=""):
    """Clearing is a state transition — the record and its history are kept."""
    _require_authority(actor)
    blockage.transition(Blockage.Status.CLEARED)
    blockage.ended_at = timezone.now()
    blockage.cleared_by = actor
    blockage.save()
    audit(actor, "blockage.cleared", blockage, note=note)
    notify_zone_subscribers(
        blockage.zone, Notification.Kind.BLOCKAGE_CLEARED,
        f"Blockage cleared in {blockage.zone}: {blockage.reason}", blockage=blockage, exclude=[actor],
    )
    return blockage


# --------------------------------------------------------------------------- #
# Expiry sweeps (lazy via middleware + `manage.py expire_stale` for cron)
# --------------------------------------------------------------------------- #
def expire_stale(now=None):
    """
    * fresh incidents past ``expires_at`` → ``stale``
    * active blockages past ``expected_end`` → ``needs_reconfirmation``
    Returns (incident_count, blockage_count).
    """
    now = now or timezone.now()
    n_inc = 0
    for incident in Incident.objects.due_to_go_stale(now):
        incident.transition(Incident.Status.STALE)
        incident.save(update_fields=["status"])
        audit(None, "incident.stale", incident, reason="freshness window expired",
              expired_at=incident.expires_at.isoformat())
        n_inc += 1

    n_blk = 0
    for blockage in Blockage.objects.due_for_reconfirmation(now).select_related("zone", "set_by"):
        blockage.transition(Blockage.Status.NEEDS_RECONFIRMATION)
        blockage.save(update_fields=["status"])
        audit(None, "blockage.needs_reconfirmation", blockage, expected_end=blockage.expected_end.isoformat())
        msg = f"Blockage #{blockage.pk} in {blockage.zone} passed its expected end — re-confirm or clear it."
        notify_user(blockage.set_by, Notification.Kind.BLOCKAGE_RECONFIRM, msg, blockage=blockage)
        for officer in blockage.zone.officers.exclude(pk=blockage.set_by_id):
            notify_user(officer, Notification.Kind.BLOCKAGE_RECONFIRM, msg, blockage=blockage)
        n_blk += 1
    return n_inc, n_blk


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def nearby_incidents(lat, lng, radius_km=None, qs=None):
    """Active incidents within ``radius_km`` sorted by haversine distance."""
    from .geo import bounding_box

    radius_m = (radius_km or _cfg("NEARBY_RADIUS_KM")) * 1000
    qs = qs if qs is not None else Incident.objects.filter(
        status__in=list(Incident.ACTIVE_STATUSES) + [Incident.Status.STALE]
    )
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_m)
    qs = qs.filter(lat__range=(min_lat, max_lat), lng__range=(min_lng, max_lng)).select_related("zone")
    out = []
    for inc in qs:
        d = haversine_m(lat, lng, inc.lat, inc.lng)
        if d <= radius_m:
            inc.distance_km_value = d / 1000.0
            out.append(inc)
    out.sort(key=lambda i: (i.status == Incident.Status.STALE, i.distance_km_value))
    return out
