"""
Populate demo data so the app is demoable right after `migrate && seed`.

All state changes go through core.services, so the audit log, notifications and
reputation all look exactly like real usage.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import services
from core.models import (
    AuditLog, Blockage, Confirmation, Incident, Notification, SavedRoute, Subscription, User, Zone,
)

PASSWORD = "demo12345"

# Demo city: central Pune, India (any city works — zones are editable in the admin).
ZONES = [
    ("Central Station", "Railway station approach roads and bus depot", 18.5286, 73.8742, 900),
    ("Old City Market", "Dense market streets, frequent deliveries", 18.5167, 73.8563, 800),
    ("University Circle", "University road junction and flyover", 18.5308, 73.8296, 1000),
    ("Riverside Bridge", "Bridge crossing and riverside road", 18.5250, 73.8470, 600),
    ("Airport Corridor", "Main arterial road towards the airport", 18.5520, 73.9000, 1500),
    ("Industrial Estate", "Truck routes and warehouse access", 18.5000, 73.8900, 1200),
]

USERS = [
    # username, first, last, role, reputation, staff/superuser, badge
    ("citizen", "Asha", "Citizen", User.Role.CITIZEN, 12, False, ""),
    ("citizen2", "Ravi", "Commuter", User.Role.CITIZEN, 22, False, ""),
    ("citizen3", "Meera", "Cyclist", User.Role.CITIZEN, 10, False, ""),
    ("citizen4", "Low", "Rep", User.Role.CITIZEN, 3, False, ""),
    ("field", "Officer", "Patil", User.Role.FIELD_AUTHORITY, 10, False, "TP-1042"),
    ("field2", "Officer", "Khan", User.Role.FIELD_AUTHORITY, 10, False, "TP-2210"),
    ("desk", "Control", "Room", User.Role.DESK_ADMIN, 10, True, ""),
]


class Command(BaseCommand):
    help = "Seed demo zones, users (one per role + extras), incidents, blockages, confirmations and notifications."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete existing TAMS data before seeding.")

    @transaction.atomic
    def handle(self, *args, flush=False, **options):
        if flush:
            for model in (Notification, Confirmation, AuditLog, SavedRoute, Subscription, Blockage, Incident):
                model.objects.all().delete()
            User.objects.filter(username__in=[u[0] for u in USERS]).delete()
            Zone.objects.all().delete()
        elif Zone.objects.exists() or User.objects.filter(username="citizen").exists():
            self.stdout.write(self.style.WARNING("Data already present. Re-run with --flush to reset."))
            return

        zones = {}
        for name, desc, lat, lng, r in ZONES:
            zones[name] = Zone.objects.create(name=name, description=desc, center_lat=lat, center_lng=lng, radius_m=r)

        u = {}
        for username, first, last, role, rep, staff, badge in USERS:
            user = User(username=username, first_name=first, last_name=last, role=role, reputation_score=rep,
                        is_staff=staff, is_superuser=staff, badge_number=badge, email=f"{username}@example.com")
            user.set_password(PASSWORD)
            user.save()
            u[username] = user
        u["field"].assigned_zones.set([zones["Central Station"], zones["Old City Market"], zones["Riverside Bridge"]])
        u["field2"].assigned_zones.set([zones["University Circle"], zones["Airport Corridor"], zones["Industrial Estate"]])

        for username, zone_names in {
            "citizen": ["Central Station", "Riverside Bridge"],
            "citizen2": ["Central Station", "University Circle"],
            "citizen3": ["Old City Market"],
            "desk": ["Central Station"],
        }.items():
            for zn in zone_names:
                Subscription.objects.create(user=u[username], zone=zones[zn])

        now = timezone.now()

        def report(who, zone, typ, desc, dlat=0.0, dlng=0.0, minutes_ago=5):
            z = zones[zone]
            inc = services.report_incident(u[who], type=typ, lat=z.center_lat + dlat, lng=z.center_lng + dlng,
                                           zone=z, description=desc)
            if minutes_ago:
                created = now - timedelta(minutes=minutes_ago)
                Incident.objects.filter(pk=inc.pk).update(created_at=created, expires_at=created + Incident.freshness_window())
                inc.refresh_from_db()
            return inc

        # 1) Fresh, just reported — 1 confirmation so far (waiting for community).
        i1 = report("citizen", "Central Station", Incident.Type.ACCIDENT,
                    "Two-car collision blocking the left lane near the station entrance.", 0.002, 0.001, 10)
        services.confirm_incident(i1, u["citizen3"], Confirmation.Kind.STILL_ACTIVE)

        # 2) Verified via community threshold (citizen2 is trusted → weight 2, + citizen3 weight 1 = 3).
        i2 = report("citizen", "Riverside Bridge", Incident.Type.HAZARD,
                    "Large pothole and debris on the bridge, bikes swerving into traffic.", -0.001, 0.0005, 25)
        services.confirm_incident(i2, u["citizen2"], Confirmation.Kind.STILL_ACTIVE)
        services.confirm_incident(i2, u["citizen3"], Confirmation.Kind.STILL_ACTIVE)

        # 3) Assigned to field officer, with an active blockage linked.
        i3 = report("citizen2", "Old City Market", Incident.Type.BLOCKAGE,
                    "Delivery truck broken down across the market road; traffic backed up.", 0.001, -0.001, 40)
        services.confirm_incident(i3, u["citizen"], Confirmation.Kind.STILL_ACTIVE)
        services.verify_incident(i3, u["field"], reason="seen on CCTV")
        services.assign_incident(i3, u["field"], u["field"])
        services.create_blockage(u["field"], zone=zones["Old City Market"], reason="Broken-down truck, tow requested",
                                 severity=Blockage.Severity.HIGH, expected_end=now + timedelta(hours=2), related_incident=i3)

        # 4) Stale — reported long ago, nobody re-confirmed.
        i4 = report("citizen3", "University Circle", Incident.Type.OTHER,
                    "Traffic signal flashing amber at the university junction.", 0.0015, 0.001, 180)
        # 5) Another stale hazard.
        report("citizen", "Airport Corridor", Incident.Type.HAZARD,
               "Oil spill on the inside lane heading towards the airport.", 0.003, -0.002, 240)

        # 6) Resolved genuine incident (reputation settled).
        i6 = report("citizen2", "Central Station", Incident.Type.ACCIDENT,
                    "Motorbike skid, rider being helped, one lane closed.", -0.002, -0.002, 120)
        services.confirm_incident(i6, u["citizen"], Confirmation.Kind.STILL_ACTIVE)
        services.assign_incident(i6, u["field"], u["desk"])
        services.resolve_incident(i6, u["field"], outcome=Incident.Outcome.GENUINE, note="Scene cleared, lane reopened.")

        # 7) Resolved false report (low-rep citizen4).
        i7 = report("citizen4", "Industrial Estate", Incident.Type.ACCIDENT,
                    "Huge crash with ten trucks!!! road totally closed", 0.001, 0.001, 90)
        services.confirm_incident(i7, u["citizen3"], Confirmation.Kind.CLEARED)
        services.resolve_incident(i7, u["field2"], outcome=Incident.Outcome.FALSE_REPORT, note="Nothing found on patrol.")

        # 8) Verified directly by an officer report, awaiting dispatch in the control room.
        report("field2", "University Circle", Incident.Type.ACCIDENT,
               "Bus and auto-rickshaw minor collision, vehicles still on carriageway.", -0.002, 0.002, 15)

        # Blockages: active (Central Station), overdue (→ needs re-confirmation), cleared (history).
        services.create_blockage(u["field"], zone=zones["Central Station"], reason="Lane closure for accident recovery",
                                 severity=Blockage.Severity.MEDIUM, expected_end=now + timedelta(minutes=90), related_incident=i1)
        overdue = services.create_blockage(u["field2"], zone=zones["Airport Corridor"], reason="Water main repair",
                                           severity=Blockage.Severity.CLOSED, expected_end=now + timedelta(hours=1))
        Blockage.objects.filter(pk=overdue.pk).update(started_at=now - timedelta(hours=5), expected_end=now - timedelta(minutes=20),
                                                      last_verified_at=now - timedelta(hours=5))
        old = services.create_blockage(u["field"], zone=zones["Riverside Bridge"], reason="Morning procession",
                                       severity=Blockage.Severity.LOW, expected_end=now + timedelta(hours=1))
        services.clear_blockage(old, u["field"], note="Procession passed.")

        # Saved route for the stretch trip-intent feature (passes through Old City Market & Central Station).
        SavedRoute.objects.create(user=u["citizen"], name="Home → Office", points=[
            [18.5105, 73.8480], [18.5167, 73.8563], [18.5240, 73.8650], [18.5286, 73.8742], [18.5350, 73.8820]])

        inc_n, blk_n = services.expire_stale()

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Zone.objects.count()} zones, {User.objects.count()} users, {Incident.objects.count()} incidents, "
            f"{Blockage.objects.count()} blockages, {Confirmation.objects.count()} confirmations, "
            f"{Notification.objects.count()} notifications ({inc_n} incidents marked stale, {blk_n} blockage needs re-confirmation)."
        ))
        self.stdout.write("Demo logins (password '%s'): citizen, citizen2, citizen3, citizen4, field, field2, desk" % PASSWORD)
