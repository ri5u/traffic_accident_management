"""View-level tests: role-based access, forms, notifications polling, trip-intent filter."""
from django.test import TestCase
from django.urls import reverse

from core import services
from core.models import Blockage, Incident, Notification, SavedRoute, User

from .factories import in_future, make_user, make_zone

PW = "pw-test-12345"


class RoleAccessTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.citizen = make_user("cit")
        self.officer = make_user("off", role=User.Role.FIELD_AUTHORITY)
        self.desk = make_user("desk", role=User.Role.DESK_ADMIN)

    def login(self, user):
        self.client.login(username=user.username, password=PW)

    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse("citizen_dashboard"))
        self.assertRedirects(r, f"{reverse('login')}?next={reverse('citizen_dashboard')}")

    def test_dashboard_redirects_by_role(self):
        for user, target in [(self.citizen, "citizen_dashboard"), (self.officer, "authority_dashboard"), (self.desk, "control_room")]:
            self.login(user)
            self.assertRedirects(self.client.get(reverse("dashboard")), reverse(target))
            self.client.logout()

    def test_access_matrix(self):
        matrix = {
            "citizen_dashboard": {self.citizen: 200, self.officer: 403, self.desk: 403},
            "authority_dashboard": {self.citizen: 403, self.officer: 200, self.desk: 403},
            "control_room": {self.citizen: 403, self.officer: 403, self.desk: 200},
            "audit_log": {self.citizen: 403, self.officer: 403, self.desk: 200},
            "user_list": {self.citizen: 403, self.officer: 403, self.desk: 200},
            "blockage_create": {self.citizen: 403, self.officer: 200, self.desk: 403},
            "map": {self.citizen: 200, self.officer: 200, self.desk: 200},
        }
        for url_name, expectations in matrix.items():
            for user, code in expectations.items():
                self.login(user)
                self.assertEqual(self.client.get(reverse(url_name)).status_code, code, f"{user.role} → {url_name}")
                self.client.logout()

    def test_citizen_cannot_post_blockage_or_resolve(self):
        inc = services.report_incident(self.citizen, type="hazard", lat=18.52, lng=73.85, zone=self.zone, description="Debris on road")
        self.login(make_user("other"))
        r = self.client.post(reverse("blockage_create"), {"zone": self.zone.pk, "severity": "low", "reason": "x",
                                                          "expected_end": in_future(hours=1).strftime("%Y-%m-%dT%H:%M")})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post(reverse("incident_resolve", args=[inc.pk]), {"outcome": "genuine"}).status_code, 403)
        self.assertFalse(Blockage.objects.exists())
        inc.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.REPORTED)

    def test_officer_can_create_blockage_via_form(self):
        self.login(self.officer)
        r = self.client.post(reverse("blockage_create"), {"zone": self.zone.pk, "severity": "high", "reason": "Crash recovery",
                                                          "expected_end": in_future(hours=2).strftime("%Y-%m-%dT%H:%M")})
        b = Blockage.objects.get()
        self.assertRedirects(r, b.get_absolute_url())
        self.assertEqual(b.set_by, self.officer)

    def test_blockage_form_rejects_past_end(self):
        self.login(self.officer)
        r = self.client.post(reverse("blockage_create"), {"zone": self.zone.pk, "severity": "high", "reason": "x",
                                                          "expected_end": "2000-01-01T10:00"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "must be in the future")


class CitizenFlowTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.citizen = make_user("cit")
        self.client.login(username="cit", password=PW)

    def test_report_incident_autodetects_zone(self):
        r = self.client.post(reverse("incident_create"), {"type": "accident", "lat": "18.5205", "lng": "73.8505",
                                                          "description": "Car hit the divider, debris on road"})
        inc = Incident.objects.get()
        self.assertRedirects(r, inc.get_absolute_url())
        self.assertEqual(inc.zone, self.zone)
        self.assertEqual(inc.reporter, self.citizen)

    def test_report_outside_any_zone_is_rejected(self):
        r = self.client.post(reverse("incident_create"), {"type": "accident", "lat": "10.0", "lng": "10.0",
                                                          "description": "Somewhere far away from everything"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "not inside any managed zone")
        self.assertFalse(Incident.objects.exists())

    def test_confirm_via_post(self):
        other = make_user("other")
        inc = services.report_incident(other, type="hazard", lat=18.52, lng=73.85, zone=self.zone, description="Debris on road")
        self.client.post(reverse("incident_confirm", args=[inc.pk]), {"kind": "still_active"})
        self.assertEqual(inc.confirmations.filter(user=self.citizen).count(), 1)

    def test_subscribe_toggle_and_notification_polling(self):
        self.client.post(reverse("zone_subscribe", args=[self.zone.pk]))
        self.assertTrue(self.citizen.subscriptions.filter(zone=self.zone).exists())

        officer = make_user("off", role=User.Role.FIELD_AUTHORITY)
        services.create_blockage(officer, zone=self.zone, reason="Closure", severity="closed", expected_end=in_future(hours=1))
        data = self.client.get(reverse("api_notifications")).json()
        self.assertEqual(data["unread"], 1)

        n = Notification.objects.get(user=self.citizen)
        r = self.client.post(reverse("notification_open", args=[n.pk]))
        self.assertRedirects(r, n.target_url)
        self.assertEqual(self.client.get(reverse("api_notifications")).json()["unread"], 0)

        self.client.post(reverse("zone_subscribe", args=[self.zone.pk]))
        self.assertFalse(self.citizen.subscriptions.exists())

    def test_cannot_open_someone_elses_notification(self):
        other = make_user("other")
        n = Notification.objects.create(user=other, kind="incident_verified", message="x")
        self.assertEqual(self.client.post(reverse("notification_open", args=[n.pk])).status_code, 404)

    def test_poll_endpoint_requires_auth(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("api_notifications")).status_code, 401)

    def test_saved_route_blocked_alert(self):
        SavedRoute.objects.create(user=self.citizen, name="Commute", points=[[18.51, 73.85], [18.53, 73.85]])
        officer = make_user("off", role=User.Role.FIELD_AUTHORITY)
        services.create_blockage(officer, zone=self.zone, reason="Closure", severity="closed", expected_end=in_future(hours=1))
        self.assertTrue(Notification.objects.filter(user=self.citizen, kind="route_blocked").exists())
        r = self.client.get(reverse("citizen_dashboard"))
        self.assertContains(r, "Your usual route")
