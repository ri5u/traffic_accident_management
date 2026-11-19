"""
Domain models for the Traffic & Accident Management System.

State transitions live on the models as small guarded methods (a tiny explicit
state machine); orchestration that touches several models (audit log rows,
notifications, reputation) lives in ``core.services``.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .geo import haversine_m

LAT_VALIDATORS = [MinValueValidator(-90.0), MaxValueValidator(90.0)]
LNG_VALIDATORS = [MinValueValidator(-180.0), MaxValueValidator(180.0)]


def tams(key):
    return settings.TAMS[key]


class InvalidTransition(Exception):
    """Raised when a state change is not allowed by the lifecycle."""


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class User(AbstractUser):
    class Role(models.TextChoices):
        CITIZEN = "citizen", "Citizen"
        FIELD_AUTHORITY = "field_authority", "Field Authority"
        DESK_ADMIN = "desk_admin", "Desk Admin"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CITIZEN, db_index=True)
    reputation_score = models.IntegerField(default=10)
    assigned_zones = models.ManyToManyField(
        "Zone",
        blank=True,
        related_name="officers",
        help_text="Zones a Field Authority is responsible for.",
    )
    badge_number = models.CharField(max_length=30, blank=True, help_text="Field Authority badge / unit id.")

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

    @property
    def is_citizen(self):
        return self.role == self.Role.CITIZEN

    @property
    def is_field_authority(self):
        return self.role == self.Role.FIELD_AUTHORITY

    @property
    def is_desk_admin(self):
        return self.role == self.Role.DESK_ADMIN

    @property
    def confirmation_weight(self):
        """Reputation-weighted vote: low-rep users count 0, trusted users count 2."""
        if self.is_field_authority or self.is_desk_admin:
            return 2
        if self.reputation_score < tams("REPUTATION_LOW"):
            return 0
        if self.reputation_score >= tams("REPUTATION_TRUSTED"):
            return 2
        return 1

    @property
    def reputation_tier(self):
        if self.reputation_score < tams("REPUTATION_LOW"):
            return "low"
        if self.reputation_score >= tams("REPUTATION_TRUSTED"):
            return "trusted"
        return "normal"


# --------------------------------------------------------------------------- #
# Zones
# --------------------------------------------------------------------------- #
class Zone(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    center_lat = models.FloatField(validators=LAT_VALIDATORS)
    center_lng = models.FloatField(validators=LNG_VALIDATORS)
    radius_m = models.PositiveIntegerField(default=1000, validators=[MinValueValidator(50)])

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def contains(self, lat, lng):
        return haversine_m(self.center_lat, self.center_lng, lat, lng) <= self.radius_m

    def distance_to_m(self, lat, lng):
        return haversine_m(self.center_lat, self.center_lng, lat, lng)

    @classmethod
    def for_point(cls, lat, lng):
        """Return the nearest zone containing the point, or None."""
        best = None
        for zone in cls.objects.all():
            d = zone.distance_to_m(lat, lng)
            if d <= zone.radius_m and (best is None or d < best[0]):
                best = (d, zone)
        return best[1] if best else None


# --------------------------------------------------------------------------- #
# Incidents
# --------------------------------------------------------------------------- #
class IncidentQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(status=Incident.Status.RESOLVED)

    def active(self):
        """Open and fresh (or owned by an officer)."""
        return self.filter(status__in=Incident.ACTIVE_STATUSES)

    def due_to_go_stale(self, now=None):
        now = now or timezone.now()
        return self.filter(status__in=Incident.FRESHNESS_STATUSES, expires_at__lt=now)


class Incident(models.Model):
    class Type(models.TextChoices):
        ACCIDENT = "accident", "Accident"
        BLOCKAGE = "blockage", "Blockage"
        HAZARD = "hazard", "Hazard"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        REPORTED = "reported", "Reported"
        VERIFIED = "verified", "Verified"
        ASSIGNED = "assigned", "Assigned"
        RESOLVED = "resolved", "Resolved"
        STALE = "stale", "Stale"

    class Outcome(models.TextChoices):
        GENUINE = "genuine", "Genuine incident"
        FALSE_REPORT = "false_report", "False / unfounded report"

    # Statuses whose freshness clock is ticking. Assigned incidents are owned by
    # an officer and do not decay; resolved is terminal; stale already decayed.
    FRESHNESS_STATUSES = (Status.REPORTED, Status.VERIFIED)
    ACTIVE_STATUSES = (Status.REPORTED, Status.VERIFIED, Status.ASSIGNED)

    TRANSITIONS = {
        Status.REPORTED: {Status.VERIFIED, Status.ASSIGNED, Status.STALE, Status.RESOLVED},
        Status.VERIFIED: {Status.ASSIGNED, Status.STALE, Status.RESOLVED},
        Status.ASSIGNED: {Status.RESOLVED},
        Status.STALE: {Status.REPORTED, Status.VERIFIED, Status.ASSIGNED, Status.RESOLVED},
        Status.RESOLVED: set(),
    }

    type = models.CharField(max_length=20, choices=Type.choices, default=Type.ACCIDENT)
    lat = models.FloatField("latitude", validators=LAT_VALIDATORS)
    lng = models.FloatField("longitude", validators=LNG_VALIDATORS)
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="incidents")
    description = models.TextField(max_length=2000)
    photo = models.ImageField(upload_to="incidents/%Y/%m/", blank=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_incidents")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REPORTED, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_confirmed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_incidents",
        limit_choices_to={"role": User.Role.FIELD_AUTHORITY},
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_incidents"
    )
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    resolution_note = models.TextField(blank=True)
    reputation_settled = models.BooleanField(default=False)

    objects = IncidentQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "expires_at"])]

    def __str__(self):
        return f"#{self.pk} {self.get_type_display()} @ {self.zone} [{self.get_status_display()}]"

    def get_absolute_url(self):
        return reverse("incident_detail", args=[self.pk])

    # -- freshness ---------------------------------------------------------- #
    @staticmethod
    def freshness_window():
        return timedelta(minutes=tams("INCIDENT_FRESHNESS_MINUTES"))

    def save(self, *args, **kwargs):
        if self.expires_at is None:
            self.expires_at = (self.created_at or timezone.now()) + self.freshness_window()
        super().save(*args, **kwargs)

    def clean(self):
        if self.zone_id and self.lat is not None and self.lng is not None:
            # Allow a 25% tolerance so points on the edge of a zone are accepted.
            if self.zone.distance_to_m(self.lat, self.lng) > self.zone.radius_m * 1.25:
                raise ValidationError({"lat": f"This location is outside the '{self.zone}' zone."})

    @property
    def is_fresh(self):
        if self.status == self.Status.ASSIGNED:
            return True
        if self.status not in self.FRESHNESS_STATUSES:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    @property
    def is_open(self):
        return self.status != self.Status.RESOLVED

    @property
    def freshness_remaining(self):
        if self.status not in self.FRESHNESS_STATUSES or not self.expires_at:
            return None
        return max(self.expires_at - timezone.now(), timedelta(0))

    def refresh_freshness(self, when=None):
        when = when or timezone.now()
        self.last_confirmed_at = when
        self.expires_at = when + self.freshness_window()

    # -- lifecycle ----------------------------------------------------------- #
    def can_transition(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, set())

    def transition(self, new_status):
        if not self.can_transition(new_status):
            raise InvalidTransition(f"Cannot move incident #{self.pk} from {self.status} to {new_status}.")
        self.status = new_status

    # -- confirmation tallies ------------------------------------------------ #
    def weighted_score(self, kind):
        return sum(c.user.confirmation_weight for c in self.confirmations.filter(kind=kind).select_related("user"))

    @property
    def still_active_score(self):
        return self.weighted_score(Confirmation.Kind.STILL_ACTIVE)

    @property
    def cleared_score(self):
        return self.weighted_score(Confirmation.Kind.CLEARED)

    def distance_km(self, lat, lng):
        return haversine_m(self.lat, self.lng, lat, lng) / 1000.0


class Confirmation(models.Model):
    class Kind(models.TextChoices):
        STILL_ACTIVE = "still_active", "Still active"
        CLEARED = "cleared", "Cleared"

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="confirmations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="confirmations")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    weight = models.PositiveSmallIntegerField(default=1, help_text="Snapshot of the user's weight at vote time.")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("incident", "user", "kind")]

    def __str__(self):
        return f"{self.user.username}: {self.get_kind_display()} on #{self.incident_id}"


# --------------------------------------------------------------------------- #
# Blockages
# --------------------------------------------------------------------------- #
class BlockageQuerySet(models.QuerySet):
    def current(self):
        return self.exclude(status=Blockage.Status.CLEARED)

    def due_for_reconfirmation(self, now=None):
        now = now or timezone.now()
        return self.filter(status=Blockage.Status.ACTIVE, expected_end__lt=now)


class Blockage(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "Low – slow traffic"
        MEDIUM = "medium", "Medium – lanes reduced"
        HIGH = "high", "High – heavy disruption"
        CLOSED = "closed", "Full closure"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        NEEDS_RECONFIRMATION = "needs_reconfirmation", "Needs re-confirmation"
        CLEARED = "cleared", "Cleared"

    TRANSITIONS = {
        Status.ACTIVE: {Status.ACTIVE, Status.NEEDS_RECONFIRMATION, Status.CLEARED},
        Status.NEEDS_RECONFIRMATION: {Status.ACTIVE, Status.CLEARED},
        Status.CLEARED: set(),
    }

    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="blockages")
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="blockages_set",
        limit_choices_to={"role": User.Role.FIELD_AUTHORITY},
    )
    related_incident = models.ForeignKey(
        Incident, null=True, blank=True, on_delete=models.SET_NULL, related_name="blockages"
    )
    reason = models.CharField(max_length=255)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MEDIUM)
    started_at = models.DateTimeField(default=timezone.now)
    expected_end = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(default=timezone.now)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="blockages_cleared"
    )
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    objects = BlockageQuerySet.as_manager()

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Blockage #{self.pk} {self.zone} ({self.get_severity_display()}) [{self.get_status_display()}]"

    def get_absolute_url(self):
        return reverse("blockage_detail", args=[self.pk])

    def clean(self):
        if self.expected_end and self.started_at and self.expected_end <= self.started_at:
            raise ValidationError({"expected_end": "Expected end must be after the start time."})

    def transition(self, new_status):
        if new_status not in self.TRANSITIONS.get(self.status, set()):
            raise InvalidTransition(f"Cannot move blockage #{self.pk} from {self.status} to {new_status}.")
        self.status = new_status

    @property
    def is_current(self):
        return self.status != self.Status.CLEARED

    @property
    def is_overdue(self):
        return self.status == self.Status.ACTIVE and self.expected_end < timezone.now()


# --------------------------------------------------------------------------- #
# Subscriptions & notifications
# --------------------------------------------------------------------------- #
class Subscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name="subscriptions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "zone")]
        ordering = ["zone__name"]

    def __str__(self):
        return f"{self.user.username} → {self.zone}"


class NotificationQuerySet(models.QuerySet):
    def unread(self):
        return self.filter(read_at__isnull=True)


class Notification(models.Model):
    class Kind(models.TextChoices):
        INCIDENT_VERIFIED = "incident_verified", "Incident verified"
        INCIDENT_ASSIGNED = "incident_assigned", "Incident assigned"
        INCIDENT_RESOLVED = "incident_resolved", "Incident resolved"
        BLOCKAGE_CREATED = "blockage_created", "Blockage created"
        BLOCKAGE_EXTENDED = "blockage_extended", "Blockage extended"
        BLOCKAGE_CLEARED = "blockage_cleared", "Blockage cleared"
        BLOCKAGE_RECONFIRM = "blockage_reconfirm", "Blockage needs re-confirmation"
        ROUTE_BLOCKED = "route_blocked", "Saved route blocked"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    incident = models.ForeignKey(Incident, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    blockage = models.ForeignKey(Blockage, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"→{self.user.username}: {self.message}"

    @property
    def is_read(self):
        return self.read_at is not None

    @property
    def target_url(self):
        if self.incident_id:
            return reverse("incident_detail", args=[self.incident_id])
        if self.blockage_id:
            return reverse("blockage_detail", args=[self.blockage_id])
        return reverse("notifications")


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries",
        help_text="Empty = system action (e.g. automatic expiry).",
    )
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=40, db_index=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        who = self.actor.username if self.actor else "system"
        return f"{self.created_at:%Y-%m-%d %H:%M} {who} {self.action} {self.target_type}#{self.target_id}"

    @property
    def target_url(self):
        try:
            if self.target_type == "incident" and self.target_id:
                return reverse("incident_detail", args=[self.target_id])
            if self.target_type == "blockage" and self.target_id:
                return reverse("blockage_detail", args=[self.target_id])
        except Exception:  # pragma: no cover
            pass
        return ""


# --------------------------------------------------------------------------- #
# Stretch: trip-intent filter
# --------------------------------------------------------------------------- #
class SavedRoute(models.Model):
    """A user's usual route as a simple polyline of [lat, lng] points."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_routes")
    name = models.CharField(max_length=80)
    points = models.JSONField(help_text="List of [lat, lng] pairs, at least two.")
    notify = models.BooleanField(default=True, help_text="Notify me when a new blockage lies on this route.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("user", "name")]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    def clean(self):
        pts = self.points
        if not isinstance(pts, list) or len(pts) < 2:
            raise ValidationError({"points": "A route needs at least two points."})
        for p in pts:
            if (not isinstance(p, (list, tuple)) or len(p) != 2
                    or not all(isinstance(v, (int, float)) for v in p)
                    or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180)):
                raise ValidationError({"points": "Each point must be a [lat, lng] pair."})
