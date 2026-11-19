from django.conf import settings


def tams(request):
    ctx = {"POLL_MS": settings.TAMS["NOTIFICATION_POLL_MS"]}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["unread_count"] = user.notifications.unread().count()
    return ctx
