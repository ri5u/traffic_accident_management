"""
Role → Django Group mapping (syllabus Unit V: "Adding groups and users, Users and Permissions").

Each TAMS role has a matching auth Group carrying model-level permissions. The groups
are created automatically after every `migrate` (post_migrate signal in core/apps.py),
and a user's group membership is synced from their `role` field whenever they are saved
(User.save in core/models.py). Views can then use Django's standard permission system,
e.g. @permission_required("core.view_auditlog") on the audit-log CSV export.
"""

ROLE_GROUPS = {
    "citizen": "Citizens",
    "field_authority": "Field Authorities",
    "desk_admin": "Desk Admins",
}

# group name -> list of "app_label.codename" permissions
GROUP_PERMISSIONS = {
    "Citizens": [
        "core.add_incident", "core.view_incident",
        "core.add_confirmation", "core.view_confirmation",
        "core.add_subscription", "core.delete_subscription", "core.view_subscription",
        "core.view_zone", "core.view_blockage",
    ],
    "Field Authorities": [
        "core.add_incident", "core.change_incident", "core.view_incident",
        "core.add_blockage", "core.change_blockage", "core.view_blockage",
        "core.add_confirmation", "core.view_confirmation", "core.view_zone",
    ],
    "Desk Admins": [
        "core.view_user", "core.change_user",
        "core.view_incident", "core.change_incident",
        "core.view_blockage", "core.view_confirmation",
        "core.view_zone", "core.add_zone", "core.change_zone",
        "core.view_subscription", "core.view_notification",
        "core.view_auditlog",
    ],
}


def ensure_role_groups(**kwargs):
    """Create/refresh the three role groups and their permissions (idempotent)."""
    from django.contrib.auth.models import Group, Permission

    for group_name, perms in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        perm_objs = []
        for dotted in perms:
            app_label, codename = dotted.split(".")
            perm = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
            if perm:
                perm_objs.append(perm)
        group.permissions.set(perm_objs)


def sync_user_group(user):
    """Put the user in exactly one role group, matching user.role."""
    from django.contrib.auth.models import Group

    role_group_names = set(ROLE_GROUPS.values())
    target = ROLE_GROUPS.get(user.role)
    current = set(user.groups.filter(name__in=role_group_names).values_list("name", flat=True))
    if current == {target}:
        return
    user.groups.remove(*user.groups.filter(name__in=role_group_names))
    if target:
        group, _ = Group.objects.get_or_create(name=target)
        user.groups.add(group)
