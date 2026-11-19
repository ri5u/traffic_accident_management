from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, Blockage, Confirmation, Incident, Notification, SavedRoute, Subscription, User, Zone


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "reputation_score", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "assigned_zones")
    search_fields = ("username", "email", "first_name", "last_name", "badge_number")
    filter_horizontal = ("assigned_zones", "groups", "user_permissions")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("TAMS", {"fields": ("role", "reputation_score", "badge_number", "assigned_zones")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("TAMS", {"fields": ("role",)}),)


class IncidentInline(admin.TabularInline):
    model = Incident
    fields = ("type", "status", "reporter", "created_at")
    readonly_fields = fields
    extra = 0
    show_change_link = True
    can_delete = False


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "center_lat", "center_lng", "radius_m", "incident_count", "subscriber_count")
    search_fields = ("name", "description")

    @admin.display(description="Incidents")
    def incident_count(self, obj):
        return obj.incidents.count()

    @admin.display(description="Subscribers")
    def subscriber_count(self, obj):
        return obj.subscriptions.count()


class ConfirmationInline(admin.TabularInline):
    model = Confirmation
    extra = 0
    readonly_fields = ("user", "kind", "weight", "created_at")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "zone", "status", "reporter", "assigned_to", "created_at", "expires_at", "outcome")
    list_filter = ("status", "type", "zone", "outcome", "created_at")
    search_fields = ("description", "reporter__username", "zone__name", "resolution_note")
    date_hierarchy = "created_at"
    raw_id_fields = ("reporter", "assigned_to", "resolved_by")
    readonly_fields = ("reputation_settled",)
    inlines = [ConfirmationInline]
    list_select_related = ("zone", "reporter", "assigned_to")


@admin.register(Confirmation)
class ConfirmationAdmin(admin.ModelAdmin):
    list_display = ("incident", "user", "kind", "weight", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("user__username", "incident__description")
    raw_id_fields = ("incident", "user")


@admin.register(Blockage)
class BlockageAdmin(admin.ModelAdmin):
    list_display = ("id", "zone", "severity", "status", "set_by", "started_at", "expected_end", "ended_at")
    list_filter = ("status", "severity", "zone")
    search_fields = ("reason", "zone__name", "set_by__username")
    date_hierarchy = "started_at"
    raw_id_fields = ("set_by", "cleared_by", "related_incident")
    list_select_related = ("zone", "set_by")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "zone", "created_at")
    list_filter = ("zone",)
    search_fields = ("user__username", "zone__name")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "message", "created_at", "read_at")
    list_filter = ("kind", ("read_at", admin.EmptyFieldListFilter))
    search_fields = ("user__username", "message")
    raw_id_fields = ("user", "incident", "blockage")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Append-only: the audit trail cannot be edited or deleted through the admin."""

    list_display = ("created_at", "actor", "action", "target_type", "target_id")
    list_filter = ("action", "target_type", "created_at")
    search_fields = ("action", "actor__username", "metadata")
    date_hierarchy = "created_at"
    readonly_fields = ("actor", "action", "target_type", "target_id", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SavedRoute)
class SavedRouteAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "notify", "created_at")
    list_filter = ("notify",)
    search_fields = ("name", "user__username")


admin.site.site_header = "TAMS administration"
admin.site.site_title = "TAMS admin"
