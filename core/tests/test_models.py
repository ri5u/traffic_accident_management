"""Incident lifecycle, freshness/staleness and blockage auto-expiry."""
from datetime import timedelta

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from core import services
from core.geo import haversine_m, point_to_polyline_m
from core.models import AuditLog, Blockage, Confirmation, Incident, InvalidTransition, Notification, User

from .factories import in_future, make_user, make_zone


class GeoTests(TestCase):
    def test_haversine_known_distance(self):
        # 1 degree of latitude ≈ 111.2 km
        self.assertAlmostEqual(haversine_m(0, 0, 1, 0) / 1000, 111.19, places=1)
        self.assertEqual(haversine_m(18.5, 73.8, 18.5, 73.8), 0)

    def test_point_to_polyline(self):
        route = [[18.50, 73.80], [18.50, 73.90]]
        self.assertLess(point_to_polyline_m(18.50, 73.85, route), 1)
        self.assertGreater(point_to_polyline_m(18.52, 73.85, route), 2000)


class IncidentLifecycleTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.citizen = make_user("cit")
        self.officer = make_user("off", role=User.Role.FIELD_AUTHORITY)
        self.desk = make_user("desk", role=User.Role.DESK_ADMIN)

    def report(self, **kw):
        return services.report_incident(self.citizen, type="accident", lat=18.52, lng=73.85, zone=self.zone,
                                        description="Collision on main road", **kw)

    def test_full_lifecycle_reported_verified_assigned_resolved(self):
        inc = self.report()
        self.assertEqual(inc.status, Incident.Status.REPORTED)
        self.assertIsNotNone(inc.expires_at)
        self.assertTrue(inc.is_fresh)

        services.verify_incident(inc, self.officer)
        self.assertEqual(inc.status, Incident.Status.VERIFIED)
        self.assertIsNotNone(inc.verified_at)

        services.assign_incident(inc, self.officer, self.officer)
        self.assertEqual(inc.status, Incident.Status.ASSIGNED)
        self.assertEqual(inc.assigned_to, self.officer)

        services.resolve_incident(inc, self.officer, outcome=Incident.Outcome.GENUINE, note="cleared")
        inc.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.RESOLVED)
        self.assertEqual(inc.resolved_by, self.officer)
        self.assertTrue(inc.reputation_settled)

        actions = list(AuditLog.objects.filter(target_type="incident", target_id=inc.pk).values_list("action", flat=True))
        for a in ["incident.reported", "incident.verified", "incident.assigned", "incident.resolved"]:
            self.assertIn(a, actions)

    def test_resolved_is_terminal(self):
        inc = self.report()
        services.resolve_incident(inc, self.officer)
        with self.assertRaises(InvalidTransition):
            services.verify_incident(inc, self.officer)
        with self.assertRaises(services.PermissionDenied):
            services.confirm_incident(inc, make_user("other"), Confirmation.Kind.STILL_ACTIVE)

    def test_citizen_cannot_verify_assign_or_resolve(self):
        inc = self.report()
        other = make_user("other")
        with self.assertRaises(services.PermissionDenied):
            services.verify_incident(inc, other)
        with self.assertRaises(services.PermissionDenied):
            services.resolve_incident(inc, other)
        with self.assertRaises(services.PermissionDenied):
            services.assign_incident(inc, self.officer, other)

    def test_authority_report_is_verified_immediately(self):
        inc = services.report_incident(self.officer, type="hazard", lat=18.52, lng=73.85, zone=self.zone,
                                       description="Oil on the road surface")
        self.assertEqual(inc.status, Incident.Status.VERIFIED)

    @override_settings(TAMS={**settings.TAMS, "INCIDENT_FRESHNESS_MINUTES": 30})
    def test_freshness_window_is_configurable(self):
        inc = self.report()
        delta = inc.expires_at - inc.last_confirmed_at
        self.assertEqual(delta, timedelta(minutes=30))

    def test_unconfirmed_incident_goes_stale_after_window(self):
        inc = self.report()
        self.assertEqual(services.expire_stale(now=timezone.now()), (0, 0))
        later = inc.expires_at + timedelta(seconds=1)
        n_inc, _ = services.expire_stale(now=later)
        self.assertEqual(n_inc, 1)
        inc.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.STALE)
        self.assertFalse(inc.is_fresh)
        self.assertTrue(AuditLog.objects.filter(action="incident.stale", target_id=inc.pk, actor__isnull=True).exists())

    def test_still_active_confirmation_extends_freshness_and_revives_stale(self):
        inc = self.report()
        Incident.objects.filter(pk=inc.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        services.expire_stale()
        inc.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.STALE)

        services.confirm_incident(inc, make_user("witness"), Confirmation.Kind.STILL_ACTIVE)
        inc.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.REPORTED)
        self.assertGreater(inc.expires_at, timezone.now())

    def test_assigned_incident_does_not_go_stale(self):
        inc = self.report()
        services.assign_incident(inc, self.officer, self.desk)
        Incident.objects.filter(pk=inc.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        services.expire_stale()
        inc.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.ASSIGNED)

    def test_desk_dispatch_notifies_officer(self):
        inc = self.report()
        services.assign_incident(inc, self.officer, self.desk)
        self.assertTrue(Notification.objects.filter(user=self.officer, kind="incident_assigned").exists())

    def test_officer_cannot_assign_to_someone_else(self):
        inc = self.report()
        other_officer = make_user("off2", role=User.Role.FIELD_AUTHORITY)
        with self.assertRaises(services.PermissionDenied):
            services.assign_incident(inc, other_officer, self.officer)


class BlockageTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.officer = make_user("off", role=User.Role.FIELD_AUTHORITY)
        self.citizen = make_user("cit")
        self.citizen.subscriptions.create(zone=self.zone)

    def create(self, **kw):
        return services.create_blockage(self.officer, zone=self.zone, reason="Water main repair",
                                        severity=Blockage.Severity.HIGH, expected_end=kw.get("end", in_future(hours=1)))

    def test_only_field_authority_can_create(self):
        with self.assertRaises(services.PermissionDenied):
            services.create_blockage(self.citizen, zone=self.zone, reason="x", severity="low", expected_end=in_future(hours=1))

    def test_create_notifies_zone_subscribers_and_audits(self):
        b = self.create()
        self.assertEqual(b.status, Blockage.Status.ACTIVE)
        self.assertTrue(Notification.objects.filter(user=self.citizen, blockage=b, kind="blockage_created").exists())
        self.assertFalse(Notification.objects.filter(user=self.officer, blockage=b).exists())
        self.assertTrue(AuditLog.objects.filter(action="blockage.created", target_id=b.pk, actor=self.officer).exists())

    def test_auto_expires_to_needs_reconfirmation(self):
        b = self.create()
        self.assertEqual(services.expire_stale(), (0, 0))
        n_inc, n_blk = services.expire_stale(now=b.expected_end + timedelta(seconds=1))
        self.assertEqual(n_blk, 1)
        b.refresh_from_db()
        self.assertEqual(b.status, Blockage.Status.NEEDS_RECONFIRMATION)
        self.assertIsNone(b.ended_at)  # not cleared — just flagged
        self.assertTrue(Notification.objects.filter(user=self.officer, blockage=b, kind="blockage_reconfirm").exists())

    def test_extend_reconfirms(self):
        b = self.create()
        services.expire_stale(now=b.expected_end + timedelta(seconds=1))
        b.refresh_from_db()
        new_end = in_future(hours=3)
        services.extend_blockage(b, self.officer, new_end)
        b.refresh_from_db()
        self.assertEqual(b.status, Blockage.Status.ACTIVE)
        self.assertEqual(b.expected_end, new_end)

    def test_clear_is_a_transition_not_a_delete(self):
        b = self.create()
        services.clear_blockage(b, self.officer, note="done")
        self.assertTrue(Blockage.objects.filter(pk=b.pk).exists())
        b.refresh_from_db()
        self.assertEqual(b.status, Blockage.Status.CLEARED)
        self.assertEqual(b.cleared_by, self.officer)
        self.assertIsNotNone(b.ended_at)
        with self.assertRaises(InvalidTransition):
            services.extend_blockage(b, self.officer, in_future(hours=2))
        # Cleared blockages never get flagged again.
        self.assertEqual(services.expire_stale(now=b.expected_end + timedelta(hours=1))[1], 0)
