"""
Tests for features that map to specific syllabus topics:
groups & permissions, cookies, sessions, regex URLs / class-based views,
hand-built HttpResponse (CSV), and custom error handling.
"""
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import services
from core.models import User

from .factories import make_user, make_zone

PW = "pw-test-12345"


class GroupsAndPermissionsTests(TestCase):
    def test_role_groups_created_by_post_migrate(self):
        names = set(Group.objects.values_list("name", flat=True))
        self.assertTrue({"Citizens", "Field Authorities", "Desk Admins"} <= names)
        self.assertTrue(Group.objects.get(name="Desk Admins").permissions.filter(codename="view_auditlog").exists())

    def test_user_group_follows_role(self):
        u = make_user("someone")
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Citizens"])
        u.role = User.Role.FIELD_AUTHORITY
        u.save()
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Field Authorities"])
        self.assertTrue(User.objects.get(pk=u.pk).has_perm("core.add_blockage"))
        self.assertFalse(User.objects.get(pk=u.pk).has_perm("core.view_auditlog"))


class CsvExportTests(TestCase):
    def test_desk_admin_downloads_csv_via_group_permission(self):
        desk = make_user("desk", role=User.Role.DESK_ADMIN)  # not a superuser: permission comes from the group
        services.audit(desk, "test.action", desk, hello="world")
        self.client.login(username="desk", password=PW)
        r = self.client.get(reverse("audit_log_csv"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("attachment;", r["Content-Disposition"])
        body = r.content.decode()
        self.assertIn("timestamp,actor,action", body)
        self.assertIn("test.action", body)

    def test_citizen_gets_403(self):
        make_user("cit")
        self.client.login(username="cit", password=PW)
        self.assertEqual(self.client.get(reverse("audit_log_csv")).status_code, 403)


class CookieAndSessionTests(TestCase):
    def setUp(self):
        self.zone_a = make_zone("A", 18.52, 73.85)
        self.zone_b = make_zone("B", 18.60, 73.95)
        self.citizen = make_user("cit")
        self.client.login(username="cit", password=PW)

    def test_zone_choice_is_remembered_in_cookie(self):
        r = self.client.get(reverse("citizen_dashboard"), {"zone": self.zone_b.pk})
        self.assertEqual(r.cookies["tams_zone"].value, str(self.zone_b.pk))
        # Next visit without ?zone= uses the cookie (the test client resends cookies automatically).
        r2 = self.client.get(reverse("citizen_dashboard"))
        self.assertEqual(r2.context["selected_zone"], self.zone_b)

    def test_recently_viewed_incidents_stored_in_session(self):
        other = make_user("other")
        i1 = services.report_incident(other, type="hazard", lat=18.52, lng=73.85, zone=self.zone_a, description="Debris on the road")
        i2 = services.report_incident(other, type="accident", lat=18.52, lng=73.85, zone=self.zone_a, description="Two cars collided")
        self.client.get(reverse("incident_detail", args=[i1.pk]))
        self.client.get(reverse("incident_detail", args=[i2.pk]))
        self.assertEqual(self.client.session["recently_viewed_incidents"], [i2.pk, i1.pk])
        r = self.client.get(reverse("citizen_dashboard"))
        self.assertEqual(r.context["recently_viewed"], [i2, i1])


class RegexUrlAndClassBasedViewTests(TestCase):
    def setUp(self):
        self.zone = make_zone()
        self.citizen = make_user("cit")
        self.client.login(username="cit", password=PW)

    def test_archive_lists_this_months_incidents(self):
        inc = services.report_incident(self.citizen, type="hazard", lat=18.52, lng=73.85, zone=self.zone, description="Oil on the road")
        now = timezone.localtime()
        url = reverse("incident_archive", kwargs={"year": f"{now.year}", "month": f"{now.month:02d}"})
        self.assertEqual(url, f"/incidents/archive/{now.year}/{now.month:02d}/")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn(inc, r.context["incidents"])

    def test_regex_rejects_bad_formats_and_view_rejects_month_13(self):
        self.assertEqual(self.client.get("/incidents/archive/26/11/").status_code, 404)   # regex: year needs 4 digits
        self.assertEqual(self.client.get("/incidents/archive/2026/13/").status_code, 404)  # view: invalid month

    def test_current_month_redirect(self):
        r = self.client.get(reverse("incident_archive_current"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/incidents/archive/", r["Location"])

    def test_archive_requires_login(self):
        self.client.logout()
        r = self.client.get("/incidents/archive/2026/11/")
        self.assertEqual(r.status_code, 302)


@override_settings(DEBUG=False)
class ErrorHandlerTests(TestCase):
    def test_custom_404_page(self):
        r = self.client.get("/this-road-does-not-exist/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "not found", status_code=404)
