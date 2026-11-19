"""Lazy expiry: run the freshness sweep at most once per interval, piggy-backing on requests.

This keeps the demo working with zero infrastructure. In production, run
`python manage.py expire_stale` from cron / a scheduler instead (see NOTES.md).
"""
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
CACHE_KEY = "tams:last-expiry-sweep"


class LazyExpiryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        interval = settings.TAMS["EXPIRY_SWEEP_INTERVAL_SECONDS"]
        if interval > 0 and not request.path.startswith(("/static/", "/media/")):
            # cache.add is atomic: only one request per interval performs the sweep.
            if cache.add(CACHE_KEY, 1, timeout=interval):
                from .services import expire_stale

                try:
                    expire_stale()
                except Exception:  # never break a page view because of the sweep
                    logger.exception("Lazy expiry sweep failed")
        return self.get_response(request)
