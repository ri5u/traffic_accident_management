from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import Blockage, Incident, SavedRoute, User, Zone

DT_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}, format="%Y-%m-%dT%H:%M")


class BootstrapMixin:
    """Add Bootstrap classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")


class SignUpForm(BootstrapMixin, UserCreationForm):
    """Public sign-up always creates a Citizen. Other roles are granted by a Desk Admin."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CITIZEN
        if commit:
            user.save()
        return user


class IncidentForm(BootstrapMixin, forms.ModelForm):
    zone = forms.ModelChoiceField(
        queryset=Zone.objects.all(), required=False,
        help_text="Leave blank to detect the zone from the location.",
    )

    class Meta:
        model = Incident
        fields = ("type", "lat", "lng", "zone", "description", "photo")
        widgets = {
            "lat": forms.NumberInput(attrs={"step": "any"}),
            "lng": forms.NumberInput(attrs={"step": "any"}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "What is happening? Lanes affected?"}),
        }
        help_texts = {"lat": "Click the map or use your location.", "photo": "Optional, max 5 MB."}

    MAX_PHOTO_BYTES = 5 * 1024 * 1024

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > self.MAX_PHOTO_BYTES:
            raise forms.ValidationError("Photo must be 5 MB or smaller.")
        return photo

    def clean_description(self):
        desc = (self.cleaned_data.get("description") or "").strip()
        if len(desc) < 10:
            raise forms.ValidationError("Please describe the incident in at least 10 characters.")
        return desc

    def clean(self):
        cleaned = super().clean()
        lat, lng, zone = cleaned.get("lat"), cleaned.get("lng"), cleaned.get("zone")
        if lat is None or lng is None:
            return cleaned
        if zone is None:
            zone = Zone.for_point(lat, lng)
            if zone is None:
                raise forms.ValidationError(
                    "This location is not inside any managed zone. Pick a point inside a shaded zone on the map."
                )
            cleaned["zone"] = zone
        elif zone.distance_to_m(lat, lng) > zone.radius_m * 1.25:
            self.add_error("zone", f"The chosen point is outside the '{zone}' zone.")
        return cleaned

    def _post_clean(self):
        # Zone may have been auto-detected in clean(); sync before model validation.
        if self.cleaned_data.get("zone"):
            self.instance.zone = self.cleaned_data["zone"]
        super()._post_clean()


class ResolveIncidentForm(BootstrapMixin, forms.Form):
    outcome = forms.ChoiceField(choices=Incident.Outcome.choices, initial=Incident.Outcome.GENUINE)
    note = forms.CharField(required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2}))


class DispatchForm(BootstrapMixin, forms.Form):
    officer = forms.ModelChoiceField(queryset=User.objects.filter(role=User.Role.FIELD_AUTHORITY, is_active=True))


def _default_end():
    return (timezone.localtime() + timedelta(hours=2)).replace(second=0, microsecond=0)


class BlockageForm(BootstrapMixin, forms.ModelForm):
    expected_end = forms.DateTimeField(widget=DT_WIDGET, input_formats=["%Y-%m-%dT%H:%M"], initial=_default_end)

    class Meta:
        model = Blockage
        fields = ("zone", "severity", "reason", "expected_end", "related_incident")

    def __init__(self, *args, officer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_incident"].queryset = Incident.objects.open().select_related("zone")
        self.fields["related_incident"].required = False
        if officer is not None and officer.assigned_zones.exists():
            self.fields["zone"].help_text = "Your assigned zones: " + ", ".join(z.name for z in officer.assigned_zones.all())

    def clean_expected_end(self):
        end = self.cleaned_data["expected_end"]
        if end <= timezone.now():
            raise forms.ValidationError("Expected end must be in the future.")
        if end > timezone.now() + timedelta(days=30):
            raise forms.ValidationError("Blockages longer than 30 days should be planned closures, not incidents.")
        return end


class ExtendBlockageForm(BootstrapMixin, forms.Form):
    expected_end = forms.DateTimeField(widget=DT_WIDGET, input_formats=["%Y-%m-%dT%H:%M"], initial=_default_end)
    note = forms.CharField(required=False, max_length=255)

    def clean_expected_end(self):
        end = self.cleaned_data["expected_end"]
        if end <= timezone.now():
            raise forms.ValidationError("New expected end must be in the future.")
        return end


class ClearBlockageForm(BootstrapMixin, forms.Form):
    note = forms.CharField(required=False, max_length=255, widget=forms.TextInput(attrs={"placeholder": "Optional note"}))


class UserAdminForm(BootstrapMixin, forms.ModelForm):
    """Desk Admin in-app user management."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role", "badge_number", "assigned_zones", "reputation_score", "is_active")
        widgets = {"assigned_zones": forms.SelectMultiple(attrs={"size": 6})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") != User.Role.FIELD_AUTHORITY and cleaned.get("assigned_zones"):
            self.add_error("assigned_zones", "Only Field Authority users can have assigned zones.")
        return cleaned


class SavedRouteForm(BootstrapMixin, forms.ModelForm):
    points = forms.JSONField(widget=forms.HiddenInput(), help_text="Click the map to add route points.")

    class Meta:
        model = SavedRoute
        fields = ("name", "points", "notify")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["points"].widget.attrs.pop("class", None)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.user and SavedRoute.objects.filter(user=self.user, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("You already have a route with this name.")
        return name

    def _post_clean(self):
        if self.user:
            self.instance.user = self.user
        super()._post_clean()


class IncidentFilterForm(BootstrapMixin, forms.Form):
    status = forms.ChoiceField(choices=[("", "Any status")] + list(Incident.Status.choices), required=False)
    type = forms.ChoiceField(choices=[("", "Any type")] + list(Incident.Type.choices), required=False)
    zone = forms.ModelChoiceField(queryset=Zone.objects.all(), required=False, empty_label="Any zone")
    q = forms.CharField(required=False, widget=forms.TextInput(attrs={"placeholder": "Search description"}))
