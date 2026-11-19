# Viva Preparation — Traffic & Accident Management System (TAMS)

This file prepares you for the viva. It is organised **by syllabus unit**. For every topic it gives:

- **Q:** the likely question.
- **A:** a short answer you can say out loud.
- **Where:** the exact file and line in this project. Open it in your editor when the examiner says "show me the code".
- **Code:** the relevant excerpt, copied from the project.
- **Show it:** how to demonstrate it live in the browser or terminal.

After the six units come project-specific questions, general Django and Python viva questions, and a command cheat-sheet.

> Line numbers refer to the current `main` branch. If you edit a file, re-check them with `grep -n`.

---

## 0. Before the viva

### 0.1 Start the project
```bash
source venv/bin/activate        # Windows: venv\Scripts\activate
python manage.py migrate
python manage.py seed --flush
python manage.py runserver
```
The demo logins are `citizen`, `field` and `desk`; all use the password `demo12345`. The login page also has one-click demo buttons.

### 0.2 The project in 60 seconds (say this first)
> "TAMS is a Django web application for coordinating traffic incidents between citizens and the authorities. It is not a navigation app; it is the management layer.
>
> **Citizens** report accidents, blockages and hazards on a map. Other citizens confirm them with *still active* or *cleared* votes. Once the reputation-weighted score reaches a threshold, the incident is **verified**.
>
> Every report has a **freshness window**. If nobody re-confirms it, the report becomes **stale**.
>
> **Field officers** take ownership of incidents, resolve them, and record **road blockages**. A blockage is an audited record with an expected end time; it is never just a yes/no switch.
>
> The **Desk Admin** has a control-room dashboard with live counts, a map, dispatch, user management and a full **audit log**.
>
> Users subscribe to **zones** and get in-app notifications, delivered by polling every 30 seconds.
>
> It uses a custom user model with roles, Django forms with validation, the ORM with foreign keys, Django admin, sessions, cookies, groups and permissions, and 54 automated tests."

### 0.3 Two-minute live demo script
1. **Report an incident.** Log in as `citizen3` → **Report incident** → click on the map → submit.
2. **Confirm it.** Log out, log in as `citizen` → open that incident → **Still active**.
3. **Verify it.** Log in as `citizen2`, a trusted user whose vote counts ×2 → **Still active**. The incident becomes **Verified** and the zone's subscribers are notified; the bell count goes up.
4. **Act on it as an officer.** Log in as `field2` → open the incident → **Take ownership** → **Set blockage** → then **Mark resolved**.
5. **Review it.** Log in as `desk` → **Control room** → **Audit log** → **Export CSV**. Then open `/admin/`.

### 0.4 Map of the project ("what does what")

| Path | What it does |
|---|---|
| `manage.py` | Command-line entry point (`runserver`, `migrate`, `test`, `seed`, …). It sets `DJANGO_SETTINGS_MODULE=config.settings`. |
| `config/settings.py` | All configuration: installed apps, middleware, templates, database, authentication, static/media files, logging and domain settings (`TAMS = {...}`). |
| `config/urls.py` | Root URLconf. It includes `core.urls`, admin, media serving and the custom error handlers. |
| `config/wsgi.py`, `config/asgi.py` | Entry points for production web servers. |
| `core/` | The single Django **app** with all the domain logic. |
| `core/models.py` | Database tables: `User`, `Zone`, `Incident`, `Confirmation`, `Blockage`, `Subscription`, `Notification`, `AuditLog`, `SavedRoute`, plus the state machines. |
| `core/services.py` | Business logic. Every state change goes through here, which writes the audit log, sends notifications and updates reputation. |
| `core/views.py` | Function-based views, one class-based view, JSON endpoints and error handlers. |
| `core/urls.py` | App URL patterns (`path` and `re_path`). |
| `core/forms.py` | Django forms and ModelForms with validation. |
| `core/admin.py` | Django admin registration for every model. |
| `core/roles.py` | Maps each role to a Django **Group** with permissions. |
| `core/apps.py` | App config; connects the `post_migrate` signal that creates the groups. |
| `core/middleware.py` | Custom middleware: the lazy expiry sweep. |
| `core/context_processors.py` | Adds the unread-notification count to every template. |
| `core/templatetags/tams_tags.py` | Custom template filters and tags. |
| `core/geo.py` | Haversine distance and point-to-route maths. |
| `core/management/commands/` | Custom `manage.py` commands: `seed` and `expire_stale`. |
| `core/migrations/` | Migration files generated from the models. |
| `core/tests/` | Automated tests (54). |
| `templates/` | Project-level templates: `base.html`, login, sign-up, 403/404/500. |
| `core/templates/core/` | App templates (dashboards, incidents, blockages, …). |
| `static/` | CSS and JavaScript (`tams.css`, `tams.js`). |
| `requirements.txt` | Pinned dependencies (`pip freeze`). |
| `.env.example` | Example environment variables; secrets are not kept in code. |

### 0.5 How a request flows through Django (draw this if asked)
```
Browser ──HTTP──▶ WSGI server (runserver)
   ▶ MIDDLEWARE (security, session, CSRF, auth, messages, LazyExpiryMiddleware)
   ▶ URL resolver: config/urls.py → core/urls.py → matches a pattern
   ▶ VIEW function/class in core/views.py
        ├─ reads request.GET / request.POST / request.session / request.COOKIES / request.user
        ├─ uses FORMS (validation) and SERVICES (business logic)
        ├─ uses MODELS via the ORM → SQL → database (SQLite)
        └─ returns render(template, context) / redirect() / JsonResponse / HttpResponse
   ▶ TEMPLATE engine renders HTML (base.html + child template, context processors add data)
   ◀ MIDDLEWARE (response phase: cookies, security headers)
Browser ◀── HTTP response
```

---

## UNIT I — Introduction to Django

**Q1. What is Django? Why did you choose it?**
A: Django is a high-level Python web framework that follows the **MVT** (Model–View–Template) pattern. It is "batteries included": an ORM, an admin site, authentication, forms, sessions, CSRF protection, migrations and a test framework are built in. A management system like this one needs all of them (users with roles, many related tables, an admin back office and an audit trail), so Django lets us focus on the domain logic.

**Q2. What is MVT? How does it differ from MVC?**
A:
- **Model** is the data layer: `core/models.py`.
- **View** is the request-handling logic: `core/views.py`.
- **Template** is the presentation layer: the `*.html` files.

In MVC the "controller" handles the request. In Django the framework itself (the URL dispatcher) plays that role, and Django's "view" corresponds to MVC's controller.

**Q3. How did you install Python and Django and set up the project?**
A: We created a virtual environment, installed Django, and froze the exact versions into `requirements.txt`.
```bash
python -m venv venv
source venv/bin/activate
pip install "Django>=5.1,<5.2" Pillow python-dotenv
pip freeze > requirements.txt
django-admin startproject config .
python manage.py startapp core
```
**Where:** `requirements.txt`:
```
Django==5.1.15
pillow==13.0.0
python-dotenv==1.2.4
```

**Q4. Why use a virtual environment?**
A: It isolates the project's packages from the system Python. Another project can use a different Django version, and `requirements.txt` lets anyone recreate the exact environment. `venv/` is listed in `.gitignore`.

**Q5. What is the difference between a Project and an App?**
A: A **project** (`config/`) is the whole website's configuration: settings, the root URLs and WSGI/ASGI. An **app** (`core/`) is a reusable module that does one job, with its own models, views, URLs, templates and admin. One project can contain many apps.

We used **one app (`core`)** on purpose because the domain is small and tightly connected (incidents, blockages and notifications all reference each other). Splitting it would only create circular imports.

**Q6. Explain the project structure.** → See table 0.4.

**Q7. Where is the app registered?**
**Where:** `config/settings.py:34`
```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]
```

**Q8. What is the difference between `django-admin` and `manage.py`?**
A: `django-admin` is the global command; we used it once for `startproject`. `manage.py` is created inside the project and does the same work, but it automatically points at this project's settings (`config.settings`), so we use it for everything else.

| Command | Purpose (used in this project) |
|---|---|
| `python manage.py runserver` | Development server |
| `python manage.py makemigrations` | Create migration files from model changes |
| `python manage.py migrate` | Apply migrations to the database |
| `python manage.py createsuperuser` | Create an admin user |
| `python manage.py shell` | Python shell with Django loaded |
| `python manage.py test` | Run the 54 tests |
| `python manage.py check` | System check for configuration errors |
| `python manage.py seed --flush` | **Custom command**: load demo data |
| `python manage.py expire_stale` | **Custom command**: expire old incidents and blockages |
| `python manage.py collectstatic` | Gather static files for production |

**Q9. Have you written your own `manage.py` command?**
A: Yes, two of them.
**Where:** `core/management/commands/seed.py:45` and `:49`, and `core/management/commands/expire_stale.py:9`
```python
class Command(BaseCommand):
    help = "Seed demo zones, users (one per role + extras), incidents, blockages, confirmations and notifications."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete existing TAMS data before seeding.")
```
**Show it:** run `python manage.py seed --flush`, then `python manage.py help seed`.

**Q10. What does an app folder contain?**
A: The app (`core/`) contains:
- `models.py`, `views.py`, `urls.py` (created by us), `forms.py`, `admin.py`, `apps.py`, `tests/`, `migrations/`, `templates/core/`;
- extras: `templatetags/`, `management/commands/`, `middleware.py`, `context_processors.py` and `services.py`.

**Q11. What is `apps.py` used for in your project?**
**Where:** `core/apps.py`. It configures the app and, in `ready()`, connects a **signal** that creates the role groups after every `migrate`.
```python
    def ready(self):
        # After `migrate`, make sure the role groups and their permissions exist.
        from .roles import ensure_role_groups

        post_migrate.connect(ensure_role_groups, sender=self)
```

**Q12. How do you keep secrets such as `SECRET_KEY` out of the code?**
A: The settings read environment variables, loaded from a `.env` file by `python-dotenv`, and fall back to safe development defaults. `.env` is git-ignored, and `.env.example` documents the variables.
**Where:** `config/settings.py:13`, `:27`, `:30`
```python
load_dotenv(BASE_DIR / ".env")
```
```python
DEBUG = env_bool("DJANGO_DEBUG", True)
```

---

## UNIT II — Views and URLs

**Q13. What is a view? Show one.**
A: A view is a Python function (or class) that takes an `HttpRequest` and returns an `HttpResponse`.
**Where:** `core/views.py:100` (`home`), the simplest view:
```python
def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
```
**Show it:** open `/`.

**Q14. How are views mapped to URLs?**
A: `config/urls.py` includes `core/urls.py`, which maps URL patterns to views and gives each one a **name**, so templates and views never hard-code paths.
**Where:** `config/urls.py:8` and `core/urls.py:7`
```python
    path("", include("core.urls")),
```
```python
    path("", views.home, name="home"),
```

**Q15. How do you pass parameters in a URL?**
A: With **path converters**. `<int:pk>` captures an integer and passes it to the view as the keyword argument `pk`.
**Where:** `core/urls.py:19` and `core/views.py:252`
```python
    path("incidents/<int:pk>/", views.incident_detail, name="incident_detail"),
```
```python
def incident_detail(request, pk):
```
In templates we build the URL with `{% url 'incident_detail' incident.pk %}`; in Python with `reverse("incident_detail", args=[pk])`, as in `core/models.py:216` (`get_absolute_url`).

**Q16. Have you used regular expressions in URLs?**
A: Yes. The **monthly incident archive** uses `re_path` with **named groups**. The year must be exactly 4 digits and the month exactly 2 digits, otherwise the URL does not match and Django returns 404.
**Where:** `core/urls.py:22`
```python
    re_path(r"^incidents/archive/(?P<year>[0-9]{4})/(?P<month>[0-9]{2})/$",
            views.IncidentArchiveView.as_view(), name="incident_archive"),
```
**Show it:** open `/incidents/archive/2026/11/` (works), `/incidents/archive/26/11/` (404 from the regex) and `/incidents/archive/2026/13/` (404 from the view's validation).
**Test:** `core/tests/test_syllabus_features.py` → `test_regex_rejects_bad_formats_and_view_rejects_month_13`.

**Q17. What is the difference between `path()` and `re_path()`?**
A: `path()` uses simple converters (`<int:pk>`, `<slug:...>`, `<str:...>`) and is easier to read. `re_path()` takes a full regular expression, for patterns converters can't express, such as "exactly 4 digits".

**Q18. Explain the `HttpRequest` object. What do you read from it?**
A: Django creates one per request. We use:
- `request.method`: `"GET"` or `"POST"`.
- `request.GET`: query string, e.g. `?status=verified&zone=2` in `incident_list` (`core/views.py:232`).
- `request.POST`: form data.
- `request.FILES`: uploaded photo (`core/views.py:274`).
- `request.user`: the logged-in user, set by `AuthenticationMiddleware`.
- `request.session` and `request.COOKIES`: see Unit VI.

**Where:** `core/views.py:142`, which reads query parameters from `request.GET`:
```python
        lat, lng = float(request.GET["lat"]), float(request.GET["lng"])
```

**Q19. What kinds of responses do you return?**

| Response | Where | Use |
|---|---|---|
| `render()` → HTML | almost every view | pages |
| `redirect()` → 302 | `core/views.py:283` | Post/Redirect/Get after a form |
| `JsonResponse` | `core/views.py:520`, `:558` | notification polling and map data for JavaScript |
| `HttpResponse` built by hand | `core/views.py:598` | **CSV download** of the audit log |
| `HttpResponse(status=401)` via `JsonResponse(..., status=401)` | `core/views.py:514` | API needs login |
| `Http404` | `core/views.py:302` | invalid month in the archive |

**Q20. Show a response you built manually.**
**Where:** `core/views.py:591–605`, the audit-log CSV export:
```python
@login_required
@permission_required("core.view_auditlog", raise_exception=True)
def audit_log_csv(request):
```
```python
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="tams-audit-{timezone.localdate():%Y%m%d}.csv"'
    writer = csv.writer(response)
```
A: `HttpResponse` behaves like a file, so `csv.writer` can write into it. The `Content-Disposition: attachment` header tells the browser to download the file instead of displaying it.
**Show it:** log in as `desk` → Audit log → **Export CSV**.

**Q21. Show a JSON API view.**
**Where:** `core/views.py:510–520`. The browser polls it every 30 seconds.
```python
@require_GET
def api_notifications(request):
```
```python
    return JsonResponse({"unread": unread.count(), "latest": latest})
```

**Q22. Function-based view vs class-based view: did you use both?**
A: Yes.
- Most views are **FBVs**, because they are explicit and easy to read in a viva.
- `IncidentArchiveView` is a **CBV**: a generic `ListView` with `LoginRequiredMixin` that gives pagination for free.
- The login and logout pages use Django's built-in CBVs, `LoginView` and `LogoutView`.

**Where:** `core/views.py:288` and `core/urls.py:8`
```python
class IncidentArchiveView(LoginRequiredMixin, ListView):
```
```python
    model = Incident
    template_name = "core/incident_archive.html"
    context_object_name = "incidents"
    paginate_by = 25
```

**Q23. How do you restrict a view to POST only?**
A: With the `@require_POST` decorator. A GET request receives **405 Method Not Allowed**. Every action that changes data (confirm, verify, assign, resolve, clear, subscribe) is POST-only.
**Where:** `core/views.py:325–327`
```python
@require_POST
@login_required
def incident_confirm(request, pk):
```

**Q24. How do you handle errors?** Django gives several layers:
1. **`get_object_or_404`** returns a 404 when a record does not exist. **Where:** `core/views.py:328`:
   ```python
       incident = get_object_or_404(Incident, pk=pk)
   ```
2. **`raise Http404`** for invalid input (`core/views.py:302`).
3. **`PermissionDenied` → 403** for the wrong role (`core/views.py:68`).
4. **Domain errors turned into friendly messages.** An illegal state change raises `InvalidTransition`; the helper `_action` catches it and shows an error message instead of crashing. **Where:** `core/views.py:76`
   ```python
   def _action(request, fn, *args, success=None, **kwargs):
   ```
5. **Custom error pages.** **Where:** `config/urls.py:14–16`; the views are at `core/views.py:674–684`; the templates are `templates/404.html`, `403.html` and `500.html`.
   ```python
   handler404 = "core.views.page_not_found"
   handler403 = "core.views.permission_denied"
   handler500 = "core.views.server_error"
   ```
   These handlers are only used when `DEBUG=False`; in debug mode Django shows its yellow error page. **Test:** `ErrorHandlerTests` in `core/tests/test_syllabus_features.py`.

**Q25. What is `reverse()`, and why not hard-code URLs?**
A: `reverse("incident_detail", args=[5])` returns `/incidents/5/`. If a URL ever changes, only `urls.py` changes, because templates use `{% url %}` and Python code uses `reverse()`.
**Where:** `core/models.py:216`
```python
    def get_absolute_url(self):
        return reverse("incident_detail", args=[self.pk])
```

---

## UNIT III — Templates, Debugging and Testing

**Q26. Where are the templates, and how does Django find them?**
A: `TEMPLATES` in settings has `DIRS` (project-level `templates/`) and `APP_DIRS: True`, which also searches `core/templates/`. App templates are namespaced as `core/...` to avoid name clashes between apps.
**Where:** `config/settings.py:58`
```python
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
```

**Q27. What is template inheritance? Show it.**
A: `base.html` defines the layout (sidebar, top bar, scripts) with `{% block %}` placeholders. Child templates use `{% extends "base.html" %}` and fill in the blocks.
**Where:** `templates/base.html:81` (the parent) and `core/templates/core/incident_list.html:1` (a child)
```django
      {% block content %}{% endblock %}
```
```django
{% extends "base.html" %}
```
The landing and login pages override a bigger block, `{% block shell %}`, to use a completely different layout while still inheriting the `<head>` and scripts.

**Q28. Show `{% include %}` (reusable partial templates).**
**Where:** `core/templates/core/incident_list.html:15`. The incident table is reused on the list, the dashboard and the archive pages.
```django
<div class="card"><div class="card-body p-0">{% include "core/_incident_table.html" with incidents=page.object_list %}</div></div>
```

**Q29. Show a `for` loop and `if/else` in DTL.**
**Where:** `core/templates/core/_incident_table.html:5–15`
```django
  {% for i in incidents %}
  <tr class="{% if i.status == 'stale' %}is-stale{% endif %}">
```
```django
  {% empty %}<tr><td colspan="7" class="text-muted text-center py-3">{{ empty_text|default:"No incidents." }}</td></tr>
```
`{% empty %}` renders when the list is empty. The same file uses `{% if %}…{% elif %}…{% else %}…{% endif %}` on line 13.

**Q30. What are template variables and filters?**
A: `{{ incident.zone }}` prints a variable, and the dot looks up an attribute, dictionary key or method. Filters transform values:
- `{{ i.created_at|timesince }}` gives "10 minutes ago";
- `|floatformat:1`;
- `|default:"…"`;
- `|date:"M d H:i"`;
- `|length`.

**Where:** `core/templates/core/_incident_table.html:11`
```django
    <td class="nowrap small text-muted"><span title="{{ i.created_at }}">{{ i.created_at|timesince }} ago</span></td>
```

**Q31. Have you written custom template tags or filters?**
A: Yes, in `core/templatetags/tams_tags.py`, loaded with `{% load tams_tags %}`.
- The `duration` filter formats time left as "1h 05m".
- The `qs_page` simple tag builds pagination links that keep the current filters.

**Where:** `core/templatetags/tams_tags.py:37` and `:55`
```python
@register.filter
def duration(td):
```
```python
@register.simple_tag(takes_context=True)
def qs_page(context, page_number):
```
Used in `_incident_table.html:13`: `{{ i.freshness_remaining|duration }} left`.

**Q32. What is a context processor? Did you write one?**
A: A context processor is a function that adds variables to **every** template's context. Ours adds the unread-notification count used by the bell badge on every page, plus the map tile settings.
**Where:** `core/context_processors.py:4`, registered in `config/settings.py` under `TEMPLATES → OPTIONS → context_processors`.
```python
def tams(request):
```

**Q33. How are static files handled?**
A: `{% load static %}` then `{% static 'css/tams.css' %}`. `STATIC_URL` and `STATICFILES_DIRS` are set in settings. Static files are our own CSS and JS; **media** files are user uploads (incident photos), stored in `MEDIA_ROOT` and served from `MEDIA_URL`.
**Where:** `templates/base.html:1` and `:13`; `config/settings.py:114`, `:117`

**Q34. What makes your templates "dynamic"?**
A: The same template shows different content depending on the context and the user:
- `{% if user.is_desk_admin %}` shows admin menu items only to Desk Admins (`templates/base.html`);
- `{% if perms.core.view_auditlog %}` shows the CSV button only to users who have that permission (`core/templates/core/audit_log.html`);
- incident pages show different action buttons for each status and role.

**Q35. Does DTL protect against XSS?**
A: Yes. Django **auto-escapes** every `{{ variable }}`, so a description containing `<script>` is shown as text and not executed. We never mark user input as `|safe`. In our JavaScript, map popups also escape text with an `escapeHtml()` function (`static/js/tams.js`).

**Q36. How did you debug the application?**
- **`DEBUG=True`** shows detailed error pages with the traceback and local variables. It is set from the environment at `config/settings.py:30`.
- **`python manage.py check`** validates the configuration.
- **Logging:** a `LOGGING` config (`config/settings.py:166`) sends every domain event to the console via `logger.info` (`core/services.py:28`, used inside `audit()` at `:42`). While `runserver` runs, you see lines such as `INFO core.services: field2 incident.assigned incident#34`.
- **`python manage.py shell`** to inspect data (see Unit V).
- **Browser DevTools** (Network tab) to inspect the 30-second polling requests to `/api/notifications/`.
- **Tests** to reproduce bugs (see below).

**Q37. How did you test the application? How many tests are there?**
A: There are **54 tests** using Django's `TestCase`, in `core/tests/`. Each test runs inside a transaction against a temporary test database, which is rolled back afterwards.

| File | What it tests |
|---|---|
| `test_models.py` | Incident lifecycle (reported → verified → assigned → resolved), invalid transitions, freshness → stale, revival, blockage auto-expiry, clearing keeps the history |
| `test_confirmations.py` | Verification threshold, reputation weighting (×0, ×1, ×2), uniqueness, reporters can't confirm their own report, reputation settlement |
| `test_views.py` | Role-based access matrix (200/403/302), form validation, notification polling, saved-route alerts, map referrer header |
| `test_syllabus_features.py` | Groups and permissions, CSV export, cookies, sessions, regex URLs, class-based views, custom 404 |

**Show it:** `python manage.py test`, which ends with `Ran 54 tests … OK`.

**Q38. Show one test.**
**Where:** `core/tests/test_confirmations.py`, `test_verified_at_threshold_of_normal_users`
```python
    def test_verified_at_threshold_of_normal_users(self):
        self.assertEqual(settings.TAMS["VERIFICATION_THRESHOLD"], 3)
        for i in range(2):
            services.confirm_incident(self.inc, make_user(f"u{i}"), K.STILL_ACTIVE)
            self.inc.refresh_from_db()
            self.assertEqual(self.inc.status, Incident.Status.REPORTED)
```

**Q39. How do you test a view?**
A: With Django's **test client** (`self.client`), which makes requests without a browser.
**Where:** `core/tests/test_views.py`, `test_access_matrix`: it logs in as each role, requests every page, and asserts the status code (200, 403, or a redirect to the login page).

---

## UNIT IV — Forms

**Q40. Why use Django forms instead of plain HTML forms?**
A: Django forms render the fields, **validate** the data, convert it to Python types (`cleaned_data`), show error messages, and protect against bad input. A **ModelForm** builds its fields from a model automatically.

**Q41. Show a ModelForm.**
**Where:** `core/forms.py:42` (`IncidentForm`)
```python
class IncidentForm(BootstrapMixin, forms.ModelForm):
```
```python
    class Meta:
        model = Incident
        fields = ("type", "lat", "lng", "zone", "description", "photo")
```
Other forms:
- `SignUpForm` (extends `UserCreationForm`), `forms.py:27`;
- `BlockageForm`, `forms.py:110`;
- `UserAdminForm`, `forms.py:148`;
- `SavedRouteForm`, `forms.py:163`;
- plain `forms.Form` classes: `ResolveIncidentForm`, `DispatchForm`, `ExtendBlockageForm`, `IncidentFilterForm`.

**Q42. Show data validation.**
A: There are three levels:
1. **Field-level `clean_<field>()`.** **Where:** `core/forms.py:66`
   ```python
       def clean_description(self):
           desc = (self.cleaned_data.get("description") or "").strip()
           if len(desc) < 10:
               raise forms.ValidationError("Please describe the incident in at least 10 characters.")
   ```
   Also `clean_photo` (at most 5 MB, `:60`) and `BlockageForm.clean_expected_end` (must be in the future, `:124`).
2. **Form-level `clean()` across several fields.** **Where:** `core/forms.py:72`. It auto-detects the zone from lat/lng and rejects points outside every zone; `add_error()` attaches an error to one field (`:85`).
3. **Model-level validators.** **Where:** `core/models.py:177`. Latitude has `MinValueValidator(-90)` / `MaxValueValidator(90)`; `Incident.clean()` (`:229`) checks the point is inside the zone.

**Show it:** submit the report form with a 3-character description, or a point outside the map's zones.
**Test:** `test_report_outside_any_zone_is_rejected`, `test_blockage_form_rejects_past_end`.

**Q43. GET vs POST: where do you use each?**
A:
- **GET** is for reading, filtering and searching. It is safe and bookmarkable. Example: the incident filter form (`core/templates/core/incident_list.html:8`, `<form method="get">`), read by `IncidentFilterForm(request.GET)` at `core/views.py:233`.
- **POST** is for anything that changes data: reporting, confirming, resolving and blockages, for example `core/templates/core/incident_form.html:10`.

**Q44. Show a view that processes a form (the standard pattern).**
**Where:** `core/views.py:273–285` (`incident_create`)
```python
def incident_create(request):
    form = IncidentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
```
```python
        messages.success(request, f"Incident #{incident.pk} reported. Others nearby can now confirm it.")
        return redirect(incident)
```
A: On a GET request we show an empty form. On a POST request we bind the data and validate it. If it is valid, we save and **redirect**; if it is invalid, we re-render the same page with the errors.

**Q45. What is Post/Redirect/Get, and where did you implement it?**
A: After a successful POST we **redirect** instead of rendering a page. This prevents the "resubmit form?" warning and duplicate records when the user presses refresh. Every POST view in the project ends with `redirect(...)` (e.g. `core/views.py:283`, `return redirect(incident)`), and the success message is passed through the **messages framework**.

**Q46. What is CSRF?**
A: **Cross-Site Request Forgery**: a malicious site tricks a logged-in user's browser into submitting a request to our site, for example "resolve incident #5". The browser sends the user's cookies automatically, so without protection the request would succeed.

**Q47. How does Django protect against CSRF, and where is it in your project?**
A: `CsrfViewMiddleware` (`config/settings.py:45`, `MIDDLEWARE`) requires a secret token on every POST. In templates we add `{% csrf_token %}` inside each POST form, which renders a hidden input with the token. Requests without a valid token get **403 Forbidden**.
**Where:** for example `core/templates/core/incident_detail.html:58`
```django
        <form method="post" action="{% url 'incident_confirm' incident.pk %}" class="flex-fill">{% csrf_token %}<input type="hidden" name="kind" value="still_active">
```
The logout form in `templates/base.html:54` also posts with a token: in Django 5, logout must be a POST request. Our JavaScript polling only does **GET** requests, so it needs no token.

**Q48. How are form errors shown?**
**Where:** `core/templates/core/_form_fields.html`, a reusable partial that loops over `form`, prints each field, its label, its help text and `field.errors`.

---

## UNIT V — Models, Migrations, ORM and Django Admin

**Q49. Show a model. Explain the field types.**
**Where:** `core/models.py:145` (`Incident`)
```python
class Incident(models.Model):
```
```python
    zone = models.ForeignKey(Zone, on_delete=models.PROTECT, related_name="incidents")
```
```python
    photo = models.ImageField(upload_to="incidents/%Y/%m/", blank=True)
```
Field types used in the project:
- `CharField` with `choices`;
- `FloatField` with validators;
- `TextField`, `ImageField`, `DateTimeField`;
- `ForeignKey`, `ManyToManyField`;
- `JSONField` (`AuditLog.metadata`);
- `BooleanField`, `PositiveIntegerField`.

**Q50. What models are there, and how are they related?**

| Model | Key relationships |
|---|---|
| `User` (custom) | M2M `assigned_zones` → `Zone` |
| `Zone` | ← `Incident.zone`, ← `Blockage.zone`, ← `Subscription.zone` |
| `Incident` | FK `zone`, FK `reporter` → User, FK `assigned_to` → User, FK `resolved_by` → User |
| `Confirmation` | FK `incident`, FK `user`; unique (incident, user, kind) |
| `Blockage` | FK `zone`, FK `set_by` → User, FK `cleared_by` → User, FK `related_incident` → Incident |
| `Subscription` | FK `user`, FK `zone`; unique (user, zone) |
| `Notification` | FK `user`, FK `incident` (nullable), FK `blockage` (nullable) |
| `AuditLog` | FK `actor` (nullable = system), plus `target_type`/`target_id` |
| `SavedRoute` | FK `user`, `points` stored as JSON |

**Q51. What does `on_delete` do? Why did you choose different values?**
A: It decides what happens to rows that point at a deleted row:
- `PROTECT` (e.g. `Incident.zone`, `Incident.reporter`): **blocks** the delete. You must not lose an incident's history by deleting its zone or reporter.
- `CASCADE` (e.g. `Confirmation.incident`): deleting the incident also deletes its confirmations.
- `SET_NULL` (e.g. `Incident.assigned_to`, `AuditLog.actor`): keeps the row and clears the link, so audit entries survive even if a user is deleted.

**Q52. What is `related_name`?**
A: The name used for the reverse relation. `zone.incidents.all()` gives all incidents in a zone, and `user.reported_incidents.all()` gives all reports by a user. Without it, the reverse names would be `incident_set` and so on.

**Q53. Explain `class Meta` options you used.**
**Where:** `core/models.py:294–296` (`Confirmation`)
```python
    class Meta:
        ordering = ["-created_at"]
        unique_together = [("incident", "user", "kind")]
```
Also `indexes` (`:211`, a database index on `status` + `expires_at` for the expiry query) and `ordering` on every model.

**Q54. Why a custom user model? How did you create it?**
A: We needed a `role` and a `reputation_score` on every user. Django strongly recommends defining a custom user **before the first migration**, because swapping it later is very hard. We extended `AbstractUser`, so we keep all the built-in authentication features (password hashing, login, permissions).
**Where:** `core/models.py:35` and `config/settings.py:100`
```python
class User(AbstractUser):
    class Role(models.TextChoices):
        CITIZEN = "citizen", "Citizen"
        FIELD_AUTHORITY = "field_authority", "Field Authority"
        DESK_ADMIN = "desk_admin", "Desk Admin"
```
```python
AUTH_USER_MODEL = "core.User"
```

**Q55. What are migrations? Walk me through your workflow.**
A: Migrations are version-controlled Python files that describe changes to the database schema.
1. Edit `models.py`.
2. Run `python manage.py makemigrations`. Django compares the models with the previous migrations and writes `core/migrations/0001_initial.py`.
3. Run `python manage.py migrate`, which runs the SQL and records it in the `django_migrations` table.

Other useful commands:
- `python manage.py showmigrations` lists what has been applied;
- `python manage.py sqlmigrate core 0001` shows the actual SQL;
- `python manage.py makemigrations --check` tells you whether any model change still needs a migration (we use it to verify everything is in sync).

**Q56. Use the Django shell to insert, update and delete data.**
Open `python manage.py shell`, then:
```python
from core.models import Zone, Incident, User

# INSERT
z = Zone.objects.create(name="Viva Zone", center_lat=18.52, center_lng=73.85, radius_m=500)
u = User.objects.get(username="citizen")
inc = Incident.objects.create(type="hazard", lat=18.52, lng=73.85, zone=z,
                              description="Created from the shell", reporter=u)

# READ / FILTER (ORM → SQL)
Incident.objects.filter(status="verified").count()
Incident.objects.filter(zone__name="Central Station").order_by("-created_at")[:5]
u.reported_incidents.all()                     # reverse FK via related_name
z.incidents.count()

# UPDATE
inc.description = "Updated from the shell"
inc.save()
Incident.objects.filter(pk=inc.pk).update(type="other")   # bulk UPDATE, no save()

# DELETE
inc.delete()
z.delete()

# See the SQL Django generates
print(Incident.objects.filter(status="stale").query)
```
> In the real app, state changes should go through `core/services.py` (for example `services.resolve_incident(...)`) so that the audit log and notifications are written. The shell is useful for exploring data.

**Q57. What is the ORM? Show some queries from the project.**
A: The Object-Relational Mapper lets us write Python instead of SQL. The queries are database-independent, and they are protected from SQL injection because values are parameterised.

Examples from the project:
- **Aggregation, GROUP BY:** `core/views.py:207`
  ```python
      status_counts = {row["status"]: row["n"] for row in Incident.objects.values("status").annotate(n=Count("id"))}
  ```
- **Avoiding N+1 queries:** `select_related` (SQL JOIN for foreign keys), `core/views.py:234`; `prefetch_related` for many-to-many, `core/views.py:210`.
- **Custom QuerySet methods:** `Incident.objects.open()`, `.active()` and `.due_to_go_stale()` at `core/models.py:132`.
- **Atomic increment with `F()` expressions** (no race conditions): `core/services.py:119`
  ```python
          User.objects.filter(pk=user_id).update(reputation_score=F("reputation_score") + delta)
  ```
- **`Q` objects for OR conditions:** `core/views.py`, `user_list` search.
- **`bulk_create`** for notification fan-out (one INSERT for many rows): `core/services.py:70`.
- **Transactions:** `@transaction.atomic` on every service function (`core/services.py:161`, …), so either everything is saved or nothing is.

**Q58. Explain Django admin and how you customised it.**
A: Django admin is an automatically generated back office. Every model is registered in `core/admin.py` with:
- `list_display` columns;
- `list_filter` sidebars;
- `search_fields`;
- `date_hierarchy`;
- **inlines** (confirmations shown inside an incident);
- a **read-only** audit log: adding, changing and deleting are all disabled, so nobody can tamper with it.

**Where:** `core/admin.py:48` and `:93–111`
```python
@admin.register(Incident)
```
```python
    def has_delete_permission(self, request, obj=None):
        return False
```
**Show it:** open `/admin/` as `desk`.

**Q59. How do you add groups and users? How do permissions work?**
A: Django creates 4 permissions for each model automatically: `add_`, `change_`, `delete_` and `view_`. Permissions can be given to **users** directly or to **groups**.
- We map each role to a group: Citizens, Field Authorities, Desk Admins.
- The groups are created with their permissions after every `migrate` by a `post_migrate` signal (`core/roles.py`, `core/apps.py`).
- When a user is saved, they are automatically placed in the group that matches their role (`User.save()` at `core/models.py:57`).
- The CSV export view is protected by `@permission_required`, so a Desk Admin who is **not** a superuser can still use it, because the permission comes from the group.

**Where:** `core/roles.py` and `core/models.py:57`
```python
def ensure_role_groups(**kwargs):
    """Create/refresh the three role groups and their permissions (idempotent)."""
```
```python
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
```
Check a user's permission with `user.has_perm("core.view_auditlog")`. In templates, use `{% if perms.core.view_auditlog %}`.
**Show it:**
- in `/admin/` → **Groups**, open "Desk Admins" to see its permissions;
- in `/admin/` → **Users**, open `field` to see the group "Field Authorities";
- or in the app: `/control-room/users/` → edit a user and change their role.

**Test:** `GroupsAndPermissionsTests` in `core/tests/test_syllabus_features.py`.

**Q60. Show the database configuration and how to change databases.**
**Where:** `config/settings.py:80–98`. SQLite is the default (zero setup). Setting `DB_ENGINE=postgres` and the `DB_*` variables switches to PostgreSQL without any code change.
```python
if os.environ.get("DB_ENGINE", "sqlite").lower() in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
```
A: SQLite is fine for development and demos. PostgreSQL is recommended in production because it handles many simultaneous writers. Because we use the ORM, the code doesn't change; only the settings do.

---

## UNIT VI — Cookies, Sessions, Users and Authentication

**Q61. What is a cookie? Where do you create one?**
A: A cookie is a small piece of data stored **in the browser** and sent back with every request. The citizen dashboard remembers the zone you picked for 30 days: when you choose a zone, we set a cookie; on your next visit we read it.
**Where:** `core/views.py:150` (read) and `:172` (set)
```python
        zone_id = request.GET.get("zone") or request.COOKIES.get(ZONE_COOKIE)
```
```python
        response.set_cookie(ZONE_COOKIE, str(selected_zone.pk), max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
```
`httponly=True` stops JavaScript from reading the cookie, and `samesite="Lax"` limits cross-site sending.
**Show it:** pick a zone on the citizen dashboard, then look in DevTools → Application → Cookies → `tams_zone`. Reload the dashboard and the same zone is still selected.
**Test:** `test_zone_choice_is_remembered_in_cookie`.

**Q62. What is a session? Where do you use one?**
A: A session stores data **on the server**, linked to the browser by a `sessionid` cookie. Django's `SessionMiddleware` provides `request.session`, which works like a dictionary. We use it for:
1. **Login state**: Django's authentication system stores the user id in the session.
2. **"Recently viewed" incidents**: each time you open an incident, its id is added to `request.session`, and the citizen dashboard lists the last 5.

**Where:** `core/views.py:256–257` and `:176–180`
```python
    recent = [i for i in request.session.get(RECENT_SESSION_KEY, []) if i != incident.pk]
    request.session[RECENT_SESSION_KEY] = [incident.pk] + recent[: RECENT_MAX - 1]
```
3. **Flash messages** (the messages framework).

**Test:** `test_recently_viewed_incidents_stored_in_session`.

**Q63. What is the difference between cookies and sessions?**

| Cookie | Session |
|---|---|
| Stored in the browser | Stored on the server (in the `django_session` table) |
| The user can see and edit it | The user only holds a random session ID |
| Size limit of about 4 KB | Size limited only by the database |
| Good for non-sensitive preferences (our `tams_zone`) | Good for login state and private data (our "recently viewed") |

**Q64. How are users created and managed?**
A: There are several ways:
- **Public sign-up** (`/accounts/signup/`) always creates a **Citizen**. `SignUpForm.save()` forces `role=CITIZEN`, so nobody can make themselves an admin. **Where:** `core/forms.py:27` and `:34`, and `core/views.py:112` (`signup`).
- A **Desk Admin** changes roles, assigns zones and deactivates accounts in the app at `/control-room/users/<id>/` (`core/views.py:622`, `user_edit`). Every change is audited.
- **Django admin** (`/admin/`), or `python manage.py createsuperuser`.
- The **seed command** creates the demo users with `set_password()`, so passwords are **hashed**, never stored as plain text.

**Q65. Where are the login and logout URLs?**
**Where:** `core/urls.py:8–10`
```python
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/signup/", views.signup, name="signup"),
```
Related settings, `config/settings.py:122–123`:
```python
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
```
The login template is `templates/registration/login.html`.

**Q66. How do you log a user in from your own view?**
A: After sign-up we call `django.contrib.auth.login()`, so the new user doesn't have to log in again.
**Where:** `core/views.py:112–122`
```python
def signup(request):
```
```python
        login(request, user)
```

**Q67. How do you protect views so only logged-in users, or only certain roles, can see them?**
A: There are three mechanisms:
1. `@login_required`: anonymous users are redirected to `LOGIN_URL?next=...`.
2. **A custom decorator, `@role_required(...)`.** It checks login, then the user's role, and raises 403 if the role doesn't match. **Where:** `core/views.py:60–73`
   ```python
   def role_required(*roles):
   ```
   ```python
               if request.user.role not in roles:
                   raise PermissionDenied("Your role does not have access to this page.")
   ```
   It is used like `@role_required(DESK)` on `control_room` (`core/views.py:205`).
3. `@permission_required("core.view_auditlog")` uses Django's permission system (`core/views.py:592`). The class-based view uses `LoginRequiredMixin`.

There is **defence in depth**: the service layer checks permissions again (e.g. `services.create_blockage` refuses non-officers), so even a crafted request can't bypass them.

**Q68. How are passwords stored?**
A: Never as plain text. Django stores a salted **PBKDF2-SHA256** hash, in the format `algorithm$iterations$salt$hash`. `AUTH_PASSWORD_VALIDATORS` enforces minimum length, rejects common passwords and so on. (The test suite uses a faster hasher only during tests, `config/settings.py:187`.)

**Q69. What happens when a user logs in?** (Session + cookie together.)
1. `LoginView` validates the credentials with `authenticate()`.
2. `login()` stores the user's id in the **session**, saved server-side.
3. The browser receives a `sessionid` **cookie**.
4. On each later request, `AuthenticationMiddleware` reads the session and sets `request.user`.
5. Logging out (POST) flushes the session.

---

## 7. Project-specific questions (why did you design it this way?)

**Q70. What problem does your project solve? How is it different from Google Maps?**
A: Navigation apps show traffic, but they don't manage incidents. There is no case ownership, no audit trail, no officer workflow, and no structured verification. TAMS is the coordination layer between citizens and authorities. Route prediction and turn-by-turn navigation are explicit **non-goals** (see `NOTES.md` §4).

**Q71. Explain the incident lifecycle.**
A: `reported → verified → assigned → resolved`, plus `stale`.
- The allowed transitions are a dictionary on the model (`core/models.py:168`, `TRANSITIONS`).
- `transition()` raises `InvalidTransition` for illegal moves, such as resolved → verified.
- The design is based on the **FHWA Traffic Incident Management** timeline: detection → verification → response → clearance.

**Q72. What is "freshness"? What is a stale incident?**
A:
- Each incident has an `expires_at` time, set to now + 60 minutes and configurable.
- Each "still active" confirmation pushes it forward.
- If nobody confirms it in time, the incident becomes **stale** and is greyed out.
- One new confirmation revives it.
- Incidents assigned to an officer never go stale.
- This copies how crowdsourced apps like Waze handle out-of-date reports.

**Where:** `core/models.py:253` (`refresh_freshness`) and `core/services.py:353` (`expire_stale`).

**Q73. How does stale detection run without a background worker?**
A: There are two mechanisms:
1. **Custom middleware** (`core/middleware.py:15`) runs the expiry check at most once per minute, piggy-backing on normal web requests. An atomic `cache.add` lock makes sure only one request does it.
2. The `python manage.py expire_stale` command, for cron in production.

The expiry check is idempotent, so both can run safely together.

**Q74. How does crowdsourced verification work? What is reputation?**
A: Confirmations are typed ("still active" or "cleared"), not star ratings. Each user's vote is weighted by their reputation:
- reputation below 5 → weight 0;
- normal users → weight 1;
- 20 or more → weight 2;
- officers → weight 2.

When the weighted "still active" score reaches 3, the incident is verified. When an officer resolves it as *genuine* or *false report*, reputations are adjusted: matching voters gain, mismatching voters lose, and false reporters lose 3.

**Where:** `core/models.py:77` (`confirmation_weight`), `core/services.py:122` (`settle_reputation`) and `:202` (`confirm_incident`).

**Q75. Why is a blockage a record and not a boolean?**
A: Authorities need accountability: who closed the road, why, until when, and who reopened it. Clearing a blockage is a **state transition** (`active → cleared`), never a delete, so the history stays. An overdue blockage automatically becomes **needs re-confirmation** and the officer is notified.

**Q76. Why polling instead of WebSockets?**
A: Alerts matter on a timescale of minutes, so polling a cheap query every 30 seconds is enough. WebSockets would need Django Channels, Redis and an ASGI server, which is extra infrastructure for no real benefit here. The `Notification` table stays the source of truth, so push delivery could be added later without changing the models. This decision is recorded in `NOTES.md`.

**Q77. How do you calculate "nearby" incidents without GeoDjango?**
A: Coordinates are plain `FloatField`s.
1. A cheap **bounding-box** filter runs in SQL first.
2. Then the exact **haversine** great-circle distance is computed in Python (`core/geo.py`).

This is fast enough at city scale and avoids installing PostGIS/GDAL.

**Q78. What is the services layer, and why have one?**
A: `core/services.py` holds all business logic. Every state change must write an audit row, may send notifications, and may update reputation. Putting all of that in one place means no view can forget a step, and the tests can call the logic without HTTP. The views stay thin.

**Q79. How does the audit log work?**
A: `services.audit()` writes an `AuditLog` row for every action: actor, action, target and JSON metadata. A NULL actor means "system", for example an automatic expiry. The audit log is append-only in the admin, filterable in the control room, and exportable to CSV.

**Q80. How do zone notifications work?**
A:
1. A user subscribes to a zone (`Subscription`, unique per user and zone).
2. When an incident in that zone is verified, or a blockage is created there, `notify_zone_subscribers()` creates one `Notification` per subscriber with `bulk_create`.
3. The browser polls `/api/notifications/` and updates the bell badge, the banner and the toasts.

**Q81. What security measures did you implement?**
- CSRF tokens.
- XSS auto-escaping.
- ORM-parameterised queries (no SQL injection).
- Hashed passwords.
- Role and permission checks in both the views and the services.
- POST-only state changes.
- Secrets in environment variables.
- The `next`-redirect is validated with `url_has_allowed_host_and_scheme` (no open redirect).
- Users can only open their own notifications (`get_object_or_404(..., user=request.user)`).
- Photo size limit.
- Secure cookie flags when `DEBUG=False`.

**Q82. What would you improve with more time?** (See `NOTES.md` §7.)
- A Celery scheduler for expiry.
- Clearance-time charts.
- PostGIS polygon zones.
- Push or email notifications.
- Rate limiting of reports.
- An open-data feed.

**Q83. What was the hardest part?**
A good honest answer: getting the lifecycle rules right. For example:
- Should an assigned incident go stale? No.
- Can one "cleared" vote kill a report? No; it needs a weighted threshold **and** a higher score than "still active".
- Making reputation settle exactly once (the `reputation_settled` flag).

---

## 8. General Django viva questions (with short answers)

| # | Question | Answer |
|---|---|---|
| 1 | What is WSGI / ASGI? | Interfaces between a web server and a Python app. WSGI is synchronous; ASGI is asynchronous and needed for WebSockets. Both entry points are in `config/`. |
| 2 | What does `settings.DEBUG = True` do? | Shows detailed error pages and serves media files in development. It **must** be False in production. |
| 3 | What is `ALLOWED_HOSTS`? | The host names the site may serve; it blocks Host-header attacks. |
| 4 | What is middleware? | Hooks that process every request and response (session, auth, CSRF, security). We wrote `LazyExpiryMiddleware`. |
| 5 | What are signals? | Event hooks (`pre_save`, `post_save`, `post_migrate`…). We use `post_migrate` to create the groups. |
| 6 | QuerySets are lazy: meaning? | Building a QuerySet doesn't hit the database; it runs when you iterate over it, slice it, or call `count()`, `list()` and so on. |
| 7 | `select_related` vs `prefetch_related`? | `select_related` uses an SQL JOIN for FK/one-to-one fields. `prefetch_related` runs a separate query for M2M/reverse FKs and joins the results in Python. |
| 8 | `get()` vs `filter()`? | `get()` returns one object and raises `DoesNotExist` or `MultipleObjectsReturned`. `filter()` returns a QuerySet, which may be empty. |
| 9 | `null=True` vs `blank=True`? | `null` is about the database (the column may be NULL). `blank` is about validation (the form field may be empty). |
| 10 | What is `__str__` used for? | A human-readable name in the admin, the shell and templates. |
| 11 | What is `auto_now` vs `auto_now_add`? | Set on every save vs set only on creation. |
| 12 | What is `ModelForm` vs `Form`? | A ModelForm builds its fields from a model and can `save()`; a Form is standalone. |
| 13 | What is `cleaned_data`? | A dictionary of validated, type-converted values after `is_valid()`. |
| 14 | What is the messages framework? | One-time flash messages stored in the session or a cookie, shown on the next page. |
| 15 | What is `{% url %}` vs hard-coded links? | `{% url %}` uses `reverse()`, so URLs can change in one place. |
| 16 | What is `collectstatic`? | Copies all static files into `STATIC_ROOT` for the production web server. |
| 17 | What are static vs media files? | Static = developer assets (CSS/JS). Media = user uploads. |
| 18 | How does Django prevent SQL injection? | The ORM uses parameterised queries; never format SQL strings yourself. |
| 19 | What is the `Meta` class? | Model or form options: ordering, unique_together, indexes, verbose names, fields. |
| 20 | What is `AbstractUser` vs `AbstractBaseUser`? | `AbstractUser` keeps all the default fields (username, email…) and you add more. `AbstractBaseUser` starts from scratch. |
| 21 | What is a context processor? | A function that adds variables to every template (we have `core.context_processors.tams`). |
| 22 | What is `render()`? | A shortcut that loads a template, renders it with a context, and returns an `HttpResponse`. |
| 23 | What is the difference between `redirect()` and `render()`? | `redirect` sends a 302 so the browser makes a new GET request; `render` returns HTML directly. |
| 24 | What status codes do you return? | 200 OK, 302 redirect, 401 (API not logged in), 403 forbidden, 404 not found, 405 method not allowed, 500 error. |
| 25 | How do you run one test file? | `python manage.py test core.tests.test_models` |
| 26 | What is `makemigrations --check`? | It fails if model changes have no migration yet; useful in CI. |
| 27 | What is a fixture vs a seed command? | A fixture is a JSON/YAML dump loaded with `loaddata`. Our seed command builds data through the services, so audit logs and notifications look real. |
| 28 | How would you deploy this? | Set `DEBUG=False`, `SECRET_KEY` and `ALLOWED_HOSTS`; use PostgreSQL; run `collectstatic`; run gunicorn behind nginx with HTTPS; run `expire_stale` from cron. |
| 29 | What is `transaction.atomic`? | All database writes inside it succeed together or are rolled back together. |
| 30 | What is the N+1 query problem? | Looping over objects and querying a relation for each one. It is fixed with `select_related` or `prefetch_related`. |

## 9. Python questions that often come up

- **Decorator:** a function that wraps another function. Our `role_required` is a decorator factory (`core/views.py:60`), and it uses `functools.wraps` to keep the original function's name.
- **`*args` / `**kwargs`:** variable positional and keyword arguments, used in the decorators and `_action`.
- **List comprehension:** e.g. `[by_id[i] for i in ids if i in by_id]` in `_recently_viewed`.
- **Classes and inheritance / mixins:** `IncidentArchiveView(LoginRequiredMixin, ListView)` and `IncidentForm(BootstrapMixin, forms.ModelForm)`. With multiple inheritance, the MRO (method resolution order) decides which method runs.
- **`@property`:** used for computed attributes such as `Incident.is_fresh` and `User.confirmation_weight`.
- **`@staticmethod` / `@classmethod`:** `Incident.freshness_window()` and `Zone.for_point()`.
- **Exceptions:** `InvalidTransition` is a custom exception; `try/except` is used in `_action`.
- **Virtual environment and pip:** `python -m venv venv`, `pip install -r requirements.txt`.

## 10. Command cheat-sheet
```bash
python manage.py runserver                 # start
python manage.py check                     # config check
python manage.py makemigrations            # create migrations
python manage.py migrate                   # apply migrations
python manage.py showmigrations            # list migrations
python manage.py sqlmigrate core 0001      # show SQL
python manage.py createsuperuser           # admin user
python manage.py shell                     # ORM playground
python manage.py test                      # 54 tests
python manage.py test core.tests.test_views  # one file
python manage.py seed --flush              # demo data
python manage.py expire_stale              # expiry sweep
```

## 11. Quick "where is it?" index

| Syllabus topic | File : line |
|---|---|
| Project settings | `config/settings.py` |
| App registration | `config/settings.py:34` |
| Root URLconf / include | `config/urls.py:6–8` |
| URL with params `<int:pk>` | `core/urls.py:19` |
| Regex URL `re_path` | `core/urls.py:22` |
| Simple view | `core/views.py:100` |
| Class-based view | `core/views.py:288` |
| JSON response | `core/views.py:510` |
| Hand-built HttpResponse (CSV) | `core/views.py:591` |
| `Http404` / `get_object_or_404` | `core/views.py:302`, `:328` |
| Custom error handlers | `config/urls.py:14`, `core/views.py:674` |
| Template inheritance | `templates/base.html:81`, `core/templates/core/incident_list.html:1` |
| for / if / empty | `core/templates/core/_incident_table.html:5–15` |
| Custom filters / tags | `core/templatetags/tams_tags.py` |
| Context processor | `core/context_processors.py:4` |
| Logging (debugging) | `config/settings.py:166`, `core/services.py:28` |
| Tests | `core/tests/` (54 tests) |
| ModelForm | `core/forms.py:42` |
| Field validation | `core/forms.py:66` |
| Form-wide validation | `core/forms.py:72` |
| GET form | `core/templates/core/incident_list.html:8` |
| POST + CSRF | `core/templates/core/incident_detail.html:58` |
| POST/Redirect/GET | `core/views.py:276–283` |
| Custom user model | `core/models.py:35`, `config/settings.py:100` |
| ForeignKey examples | `core/models.py:179`, `:182`, `:288` |
| ManyToMany | `core/models.py:43` |
| Migrations | `core/migrations/0001_initial.py` |
| Admin customisation | `core/admin.py` |
| Groups & permissions | `core/roles.py`, `core/apps.py`, `core/models.py:57` |
| `@permission_required` | `core/views.py:592` |
| Database config | `config/settings.py:80` |
| Cookie set / read | `core/views.py:172` / `:150` |
| Session | `core/views.py:256–257` |
| Login / logout URLs | `core/urls.py:8–9` |
| `login()` in a view | `core/views.py:119` |
| `@login_required` / custom role decorator | `core/views.py:60` |
