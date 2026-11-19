from django.conf import settings


def tams(request):
    ctx = {
        "POLL_MS": settings.TAMS["NOTIFICATION_POLL_MS"],
        "MAP_TILE_URL": settings.MAP_TILE_URL,
        "MAP_TILE_ATTRIBUTION": settings.MAP_TILE_ATTRIBUTION,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["unread_count"] = user.notifications.unread().count()
    return ctx
