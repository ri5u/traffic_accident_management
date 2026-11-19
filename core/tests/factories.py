from datetime import timedelta

from django.utils import timezone

from core.models import User, Zone


def make_user(username, role=User.Role.CITIZEN, reputation=10, **kw):
    u = User(username=username, role=role, reputation_score=reputation, **kw)
    u.set_password("pw-test-12345")
    u.save()
    return u


def make_zone(name="Zone A", lat=18.52, lng=73.85, radius=1000):
    return Zone.objects.create(name=name, center_lat=lat, center_lng=lng, radius_m=radius)


def in_future(**kw):
    return timezone.now() + timedelta(**kw)
