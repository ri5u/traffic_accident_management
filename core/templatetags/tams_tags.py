from django import template
from django.utils import timezone

register = template.Library()

STATUS_CLASSES = {
    # incidents
    "reported": "warning text-dark",
    "verified": "danger",
    "assigned": "primary",
    "resolved": "success",
    "stale": "secondary",
    # blockages
    "active": "danger",
    "needs_reconfirmation": "warning text-dark",
    "cleared": "success",
}
SEVERITY_CLASSES = {"low": "info text-dark", "medium": "warning text-dark", "high": "danger", "closed": "dark"}
ROLE_CLASSES = {"citizen": "secondary", "field_authority": "primary", "desk_admin": "dark"}


@register.filter
def status_class(status):
    return STATUS_CLASSES.get(status, "light text-dark")


@register.filter
def severity_class(sev):
    return SEVERITY_CLASSES.get(sev, "light text-dark")


@register.filter
def role_class(role):
    return ROLE_CLASSES.get(role, "secondary")


@register.filter
def duration(td):
    """timedelta → '1h 05m' / '12m'."""
    if td is None:
        return ""
    total = int(td.total_seconds())
    if total <= 0:
        return "expired"
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


@register.filter
def is_past(dt):
    return dt is not None and dt < timezone.now()


@register.simple_tag(takes_context=True)
def qs_page(context, page_number):
    params = context.get("params", "")
    return f"?{params + '&' if params else ''}page={page_number}"
