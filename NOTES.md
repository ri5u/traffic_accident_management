# NOTES — design reasoning log

This file records the research behind the design, every non-obvious decision,
the explicit non-goals, and what was deferred. The brief was "build the
coordination layer that consumer navigation apps deliberately don't build", so
every decision below is judged against that, not against a navigation app.

---

## 1. Domain research (done before building) and how it shaped the design

**Traffic Incident Management (TIM) workflow (US FHWA).** FHWA's TIM guidance
describes an incident as moving through *detection → verification → response
→ clearance → recovery*. Its performance measures put timestamps on each step
(first awareness, verification, responder arrival, all lanes open, normal flow).
It also says plainly that *detection and verification are different steps*:
a loop detector sees a slowdown but cannot verify its cause, while a camera
verifies but does not detect.
Sources: FHWA *Best Practices in Traffic Incident Management*
(ops.fhwa.dot.gov/publications/fhwahop10050) and the TIM performance measures pages.

→ *Design impact:*
- The incident lifecycle is `reported → verified → assigned → resolved`, which maps to detection → verification → response → clearance.
- Each step has its own timestamp column (`created_at`, `verified_at`, `assigned_at`, `resolved_at`), so clearance-time KPIs are a single query later.
- A citizen report is only *detection*. Verification has to come from either several independent confirmations or an authority.

**Crowdsourced staleness (Waze/Google Maps "Still there? / Not there").**
- Waze shows a report for a window that changes with how many drivers react. "Not there" votes shorten that window.
- Waze's partner data feed documents removal at a submitted end time, or once enough "not there" votes push a confidence score below zero.
- User forums complain about two things: reports that vanish overnight, and single troll votes that remove real hazards.
Sources: Waze Help ("Still there / Not there"), Waze for Cities data-feed docs, Waze forum and suggestion-box threads.

→ *Design impact:*
- Freshness is a first-class field (`expires_at`). Each `still_active` confirmation pushes it forward, and when it lapses the incident becomes `stale`. Stale incidents are greyed out, not deleted, and one new confirmation revives them.
- `cleared` votes can mark an incident stale early, but only when their weighted score reaches a threshold *and* beats the `still_active` score. One troll vote is not enough.
- Votes are weighted by reputation, which stops a single low-quality account from verifying or killing a report.
- Assigned incidents **do not decay**. Once an officer owns the case, the authority is the source of truth, not the crowd.

**Role models in municipal ops tools (CAD / 311 / traffic management centres).**
These systems usually separate:
- the public reporter;
- the field responder, who owns on-scene actions;
- the dispatcher / TMC operator, who has a city-wide view, dispatches, administers users and audits.

Road-closure tools treat a closure as a *permit-like record* with a start, an expected end and an accountable officer. A closure is not a map toggle, and it is never silently removed.

→ *Design impact:*
- Three roles: **Citizen**, **Field Authority** and **Desk Admin**.
- Blockages are audited records with `set_by`, `expected_end` and `cleared_by`. Clearing one is a state transition, never a delete.
- Overdue blockages flip to `needs_reconfirmation` instead of expiring silently, so a human must confirm that the road is still closed.
- The Desk Admin role can **dispatch** (assign to any officer) but cannot create blockages or resolve incidents. Those are on-scene decisions.

---

## 2. Architectural decisions

| Decision | Choice | Why |
|---|---|---|
| Custom user | `core.User(AbstractUser)` with `role`, `reputation_score`, `assigned_zones`, `badge_number`, all in migration `0001` | Swapping the user model later is notoriously painful. Roles are a single field rather than Django Groups because each user has exactly one role and the role drives routing and UI. Groups would add indirection without benefit here. |
| App layout | One app, `core`, plus Django admin for low-level CRUD | As briefed. The domain is small and tightly coupled; splitting it into apps would add import cycles, not clarity. |
| Business logic | `core/services.py` holds every state change; models hold the state machine (`TRANSITIONS` and `transition()`) | Every mutation must write an audit row and may notify and adjust reputation. Centralising this means a view can't forget it, and tests can drive the domain without HTTP. |
| State machine | Explicit transition tables on `Incident` and `Blockage`; an illegal move raises `InvalidTransition`, which views turn into a flash message | Simple, testable, no third-party FSM library. |
| Geometry | Plain `FloatField` lat/lng + haversine (`core/geo.py`). **No GeoDjango/PostGIS.** | GDAL/GEOS/PostGIS install pain is the top reason course projects fail to run on a marker's machine. At city scale (tens of zones, hundreds of open incidents), a SQL bounding-box pre-filter plus exact haversine in Python is fast enough and fully portable. Zones are circles (centre + radius), which keeps containment trivial. If polygons or 10⁵+ rows are ever needed, move to PostGIS. |
| Database | SQLite in development | Zero setup. **Production recommendation: PostgreSQL.** SQLite serialises writes, and confirmations and polling are write- and read-heavy under concurrency. JSONField and indexes port unchanged. |
| Expiry mechanism | **Lazy sweep** (`LazyExpiryMiddleware`: at most once per 60 s, using an atomic `cache.add` lock) **plus** a `manage.py expire_stale` command for cron | The demo works with zero infrastructure (no Celery or Redis), yet production gets a deterministic scheduler. The sweep is idempotent, so both can run together. Note that LocMem cache is per-process; in multi-process production use a shared cache, or rely on cron alone. |
| Notifications | `Notification` rows fanned out with `bulk_create` per zone subscriber; delivered by **polling** `/api/notifications/` every 30 s | See §3. |
| Verification threshold | Reputation-weighted score ≥ `TAMS_VERIFICATION_THRESHOLD` (default 3) | Weights: rep < 5 → 0 (shadow-weighted, so they can still click but it doesn't count), 5–19 → 1, ≥ 20 (trusted) → 2, authority accounts → 2. The weight is snapshotted on the `Confirmation` row, which keeps it auditable. |
| Reputation | Settled once, when an officer resolves with an `outcome` (`genuine` / `false_report`) | The outcome is the "ground truth" the brief asks for. Genuine: reporter +2, `still_active` voters +1, and `cleared` voters −1 only if they voted before an officer took the case. False report: reporter −3, `still_active` −1, `cleared` +1. The `reputation_settled` flag makes this idempotent. Updates use `F()` expressions to avoid lost updates. |
| Confirmation uniqueness | `unique_together(incident, user, kind)` | As briefed. A user may legitimately say "still active" at 09:00 and "cleared" at 11:00. History is kept and both votes count. Reporters cannot confirm their own report. |
| Authority reports | Auto-verified | An on-duty officer's report is not crowdsourced data. |
| Status `outcome` vs extra status | Kept the 5 briefed statuses; a false report is `resolved` with `outcome=false_report` | Keeps the lifecycle as specified while still giving reputation a ground truth. |
| Sign-up | Public sign-up always creates a **Citizen**. Other roles are granted by a Desk Admin (in-app user editor or Django admin), and the change is audited. | Prevents self-escalation. |
| Access control | `role_required(*roles)` decorator. Unauthenticated users go to the login redirect; the wrong role gets **403** (not a redirect), so tests can assert it. The services layer re-checks permissions (defence in depth). | |
| AuditLog | Generic `(target_type, target_id)` + JSON metadata; **append-only in the admin** (no add, change or delete) | A GenericForeignKey was considered but rejected: audit rows must survive deletion of their target, and a plain id is simpler to query and export. `actor = NULL` means a system action (expiry). |
| CSS framework | **Bootstrap 5.3** (CDN) | Pico.css was considered. Pico is elegant for content sites but classless, and it lacks the components an ops console needs out of the box: responsive navbar collapse, badges, toasts (used for poll alerts), dense tables, input groups and dropdowns. Bootstrap gives all of these with no build step. |
| Maps | Leaflet 1.9.4 + OpenStreetMap tiles via CDN | No API key, no billing. Incidents are `circleMarker`s coloured by status (stale ones are smaller, translucent and dashed). Blockages are shaded `circle`s over their zone, coloured by severity and dashed when they need re-confirmation. Map data comes from one JSON endpoint (`/api/map-data/`). |
| Photos | `ImageField` (Pillow), max 5 MB, validated in the form | No image analysis (non-goal). |
| Config | Every secret and tunable comes from an environment variable (`.env` via python-dotenv) with development defaults; see `.env.example` | |
| Nearby incidents | Browser geolocation → `?lat=&lng=`; on failure or denial, a fallback zone selector (defaulting to the first subscribed zone) | Geolocation is attempted automatically once per browser session, then is opt-in through a button. The page never loops or nags. |
| Zone detection | An incident's zone is auto-detected from its point (nearest containing circle). If chosen manually it must be within 125 % of the radius. Points outside every zone are rejected. | An authority can only act on locations it manages. |

## 3. Considered and deferred: Django Channels / WebSockets

Real-time push would mean Channels, an ASGI server, a Redis channel layer and a
second deployment process. For this domain, alerts have minute-scale relevance:
a blockage matters for the next hour, not the next 200 ms. So a 30-second poll
of a cheap indexed query (`user_id, read_at IS NULL`) is good enough and
operationally trivial. The poll pauses while the tab is hidden and fires
immediately when the tab becomes visible again.

The `Notification` table is the durable source of truth either way. Adding
WebSockets or Web Push later would be a delivery-channel change on top of the
same rows, with no model change. **Deferred deliberately, not forgotten.**

## 4. Explicit non-goals (not built, by design)

- **Route prediction / turn-by-turn navigation.** That is the consumer-app domain this system explicitly is not.
- **Live third-party traffic feeds** (Google, TomTom, HERE, Waze CCP). These need contracts and API keys and would blur the "authority-of-record" positioning. The `Incident` model could ingest them later as a reporter type.
- **Native mobile app.** The web UI is responsive and was checked at iPhone 13 width with no horizontal overflow.
- **Background location tracking / "heading toward" detection.** This is a privacy-heavy, battery-heavy feature that needs a native app. It is replaced by the opt-in trip-intent filter (§5).
- **Django Channels / WebSockets.** See §3.
- **ML / image analysis of photos.** Photos are evidence for humans, not model input.
- **GeoDjango / PostGIS.** See §2.

## 5. Stretch features

- ✅ **Trip-intent filter (built).** Users save a "usual route" as a polyline, drawn by clicking the map (`SavedRoute.points` as JSON).
  - Any current blockage whose zone circle comes within `zone radius + TAMS_ROUTE_BUFFER_M` (default 300 m) of any route segment flags the route. Distance is point-to-segment, using a local equirectangular projection.
  - Users see the flag in a "Your usual route is blocked" banner on their dashboard and on the My routes page.
  - A `route_blocked` notification is also sent when a new blockage is created.
  - This gives "is my commute affected?" without tracking anyone.
- ✅ **Desk Admin dispatch.** The control room assigns verified incidents to any officer, and the officer is notified.
- ✅ **Early-stale from `cleared` votes.** The Waze-style "Not there" mechanic.
- ⏭ Skipped:
  - CSV export of the audit log;
  - KPI charts of clearance time (the timestamps exist);
  - polygon zones;
  - rate limiting of reports per user;
  - email/SMS delivery.

## 6. Known limitations and trade-offs

- **Lazy expiry sweep.** It runs at most once a minute per process. Between sweeps, `Incident.is_fresh` is computed live, so the UI is never wrong about freshness; only the stored `status` column lags by up to a minute.
- **Blockages are zone-wide.** A blockage covers its whole zone circle rather than a precise road segment. This matches how many cities publish closures by area, and it keeps the model honest without road-network data.
- **Nearby search on SQLite.** The bounding-box pre-filter runs in SQL, but the exact haversine runs in Python. That is fine at city scale; on Postgres it can move into SQL or PostGIS.
- **CDN dependency.** Bootstrap, Leaflet and OSM tiles load from CDNs, so the UI needs internet access; only the server side works offline. The automated tests don't depend on the CDNs.

## 7. What I would build next

1. **Celery beat (or cron) for `expire_stale`**, plus a shared cache (Redis) in production.
2. **Clearance-time KPIs** on the control room (median T(reported→verified), T(assigned→resolved)) using the existing timestamps.
3. **Polygon zones and segment-level blockages**, at which point PostGIS earns its keep.
4. **Web Push / email digests** as additional delivery channels for the existing `Notification` rows.
5. **Abuse controls:** rate-limit reports per user and per zone, and require photos for low-reputation reporters.
6. **Public read-only status page / open-data feed** (e.g. CIFS / WZDx format) of verified incidents and closures.
