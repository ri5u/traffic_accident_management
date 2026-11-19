"""Crowdsourced verification: thresholds, reputation weighting, uniqueness, reputation settlement."""
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.conf import settings

from core import services
from core.models import Confirmation, Incident, Notification, User

from .factories import make_user, make_zone

K = Confirmation.Kind


class ConfirmationThresholdTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.reporter = make_user("reporter")
        self.subscriber = make_user("sub")
        self.subscriber.subscriptions.create(zone=self.zone)
        self.inc = services.report_incident(self.reporter, type="accident", lat=18.52, lng=73.85,
                                            zone=self.zone, description="Crash at the junction")

    def test_verified_at_threshold_of_normal_users(self):
        self.assertEqual(settings.TAMS["VERIFICATION_THRESHOLD"], 3)
        for i in range(2):
            services.confirm_incident(self.inc, make_user(f"u{i}"), K.STILL_ACTIVE)
            self.inc.refresh_from_db()
            self.assertEqual(self.inc.status, Incident.Status.REPORTED)
        services.confirm_incident(self.inc, make_user("u3"), K.STILL_ACTIVE)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, Incident.Status.VERIFIED)
        self.assertIsNotNone(self.inc.verified_at)

    def test_verification_notifies_zone_subscribers(self):
        for i in range(3):
            services.confirm_incident(self.inc, make_user(f"u{i}"), K.STILL_ACTIVE)
        self.assertEqual(Notification.objects.filter(user=self.subscriber, incident=self.inc, kind="incident_verified").count(), 1)

    def test_trusted_user_counts_double(self):
        services.confirm_incident(self.inc, make_user("trusted", reputation=25), K.STILL_ACTIVE)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, Incident.Status.REPORTED)
        services.confirm_incident(self.inc, make_user("normal"), K.STILL_ACTIVE)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, Incident.Status.VERIFIED)

    def test_low_reputation_user_counts_zero(self):
        for i in range(5):
            services.confirm_incident(self.inc, make_user(f"low{i}", reputation=1), K.STILL_ACTIVE)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, Incident.Status.REPORTED)
        self.assertEqual(self.inc.still_active_score, 0)

    @override_settings(TAMS={**settings.TAMS, "VERIFICATION_THRESHOLD": 1})
    def test_threshold_is_configurable(self):
        services.confirm_incident(self.inc, make_user("one"), K.STILL_ACTIVE)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, Incident.Status.VERIFIED)

    def test_duplicate_confirmation_is_idempotent(self):
        u = make_user("dup")
        _, created1 = services.confirm_incident(self.inc, u, K.STILL_ACTIVE)
        _, created2 = services.confirm_incident(self.inc, u, K.STILL_ACTIVE)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(self.inc.confirmations.count(), 1)

    def test_unique_together_enforced_in_db(self):
        u = make_user("dbdup")
        Confirmation.objects.create(incident=self.inc, user=u, kind=K.STILL_ACTIVE)
        with self.assertRaises(IntegrityError):
            Confirmation.objects.create(incident=self.inc, user=u, kind=K.STILL_ACTIVE)

    def test_reporter_cannot_confirm_own_report(self):
        with self.assertRaises(services.PermissionDenied):
            services.confirm_incident(self.inc, self.reporter, K.STILL_ACTIVE)

    def test_cleared_reports_mark_incident_stale_early(self):
        for i in range(3):
            services.confirm_incident(self.inc, make_user(f"c{i}"), K.CLEARED)
        self.inc.refresh_from_db()
        self.assertEqual(self.inc.status, Incident.Status.STALE)


class ReputationTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.officer = make_user("off", role=User.Role.FIELD_AUTHORITY)
        self.reporter = make_user("rep")
        self.yes = make_user("yes")
        self.no = make_user("no")
        self.inc = services.report_incident(self.reporter, type="accident", lat=18.52, lng=73.85,
                                            zone=self.zone, description="Crash at the junction")
        services.confirm_incident(self.inc, self.yes, K.STILL_ACTIVE)
        services.confirm_incident(self.inc, self.no, K.CLEARED)

    def _rep(self, u):
        u.refresh_from_db()
        return u.reputation_score

    def test_false_report_lowers_reporter_and_rewards_correct_confirmers(self):
        services.resolve_incident(self.inc, self.officer, outcome=Incident.Outcome.FALSE_REPORT)
        self.assertEqual(self._rep(self.reporter), 7)
        self.assertEqual(self._rep(self.yes), 9)
        self.assertEqual(self._rep(self.no), 11)

    def test_genuine_report_rewards_reporter_and_matching_confirmers(self):
        services.assign_incident(self.inc, self.officer, self.officer)
        services.resolve_incident(self.inc, self.officer, outcome=Incident.Outcome.GENUINE)
        self.assertEqual(self._rep(self.reporter), 12)
        self.assertEqual(self._rep(self.yes), 11)
        self.assertEqual(self._rep(self.no), 9)  # said "cleared" before an officer even took the case

    def test_settlement_happens_only_once(self):
        services.resolve_incident(self.inc, self.officer, outcome=Incident.Outcome.GENUINE)
        services.settle_reputation(self.inc)
        self.assertEqual(self._rep(self.reporter), 12)
