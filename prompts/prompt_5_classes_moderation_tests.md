# PROMPT 5 of 5 - paste this ENTIRE file into the AI model

# SHARED CONTRACT (read fully before writing anything)

You are one of FIVE AI developers building ONE project in parallel. Everyone receives this same contract plus a different task. All outputs are merged into one repository and must start with `docker compose up --build` with zero manual glue. Therefore:

- Use the exact file paths, names, table/column names, function signatures, routes and CSS classes below. Never rename anything.
- Only create files you own (section 3). Never create a shared file that this contract does not list; anything extra goes into a file you own.
- If something is ambiguous, pick the simplest option and list it under "ASSUMPTIONS" at the end of your answer.
- Output every file you own COMPLETE (no "...", no "rest unchanged"), each in its own code block, preceded by a line with its path.
- Write production quality code: typed, small functions, short comments, no dead code, no TODO placeholders.

## 1. Product

Unofficial, private community site for students of the community site (Czech secondary school, domain spseiostrava.cz).
Only `@spseiostrava.cz` emails may log in. Everything except `/` (landing), `/login`, `/auth/*`, `/rules`, `/privacy`, `/takedown`, `/static/*`, `/healthz` requires login.
Features: memes feed (Pinterest-like masonry, infinite scroll), quotes ("citáty" - funny things students/teachers said), study resources, class profiles, and reporting + moderation on everything.
UI language: CZECH (all user-visible text, dates in cs-CZ format). Code, comments, identifiers: English.
Target: everything (Caddy + app + Postgres + backups) fits in about 1 GB RAM on Oracle Cloud free tier; up to ~2000 users.

## 2. Fixed stack

- Python 3.12, FastAPI, SYNCHRONOUS SQLAlchemy 2.0 (typed `Mapped[]`) + psycopg 3, plain `def` route handlers (no async DB code), Alembic, Pydantic v2 + pydantic-settings.
- Server-rendered Jinja2 (autoescape ON) + HTMX 1.9.x (served from `/static/vendor/htmx.min.js`) + plain CSS + minimal vanilla JS. No Node, no bundler, no CSS framework, no CDN at runtime.
- PostgreSQL 16, Caddy 2 (TLS, security headers, auth-gated media), gunicorn with uvicorn workers (2 workers). No Redis, no Celery. Background work: FastAPI `BackgroundTasks`. Email: stdlib `smtplib`.
- Allowed Python packages (nothing else): fastapi, uvicorn[standard], gunicorn, sqlalchemy, psycopg[binary], alembic, pydantic, pydantic-settings, jinja2, python-multipart, pillow, email-validator, httpx, pytest.
- Strict CSP is enforced by Caddy: `default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`. Therefore NO inline `<script>`, NO inline `style=""`, NO inline event handlers (`onclick=`...), NO external URLs for scripts/fonts/images. `hx-*` attributes are fine. Put JS/CSS in files under `static/`. `base.html` carries `<meta name="htmx-config" content='{"includeIndicatorStyles":false,"allowEval":false}'>`.

## 3. Repository layout and OWNERSHIP (P1..P5 = the five prompts)

```
docker-compose.yml, .env.example, Caddyfile, README.md      P1
backup/backup.sh, db/postgresql.conf                        P1
backend/Dockerfile, entrypoint.sh, requirements.txt          P1
backend/alembic.ini, alembic/env.py, alembic/versions/0001_initial.py   P1
backend/app/main.py                                          P1
backend/app/core/config.py, db.py, templates.py, flash.py, storage.py   P1
backend/app/models/*.py  (package; __init__ re-exports every model)     P1
backend/app/routers/home.py                                  P1
backend/app/templates/base.html, home.html, errors/{403,404,500}.html,
        components/{nav,flash,footer}.html                   P1
backend/app/static/css/app.css, static/js/app.js             P1

backend/app/core/deps.py, core/ratelimit.py                  P2
backend/app/services/sessions.py, services/mailer.py         P2
backend/app/routers/auth.py, templates/auth/*                P2

backend/app/services/images.py, routers/memes.py             P3
backend/app/templates/memes/*, static/css/memes.css, static/js/masonry.js   P3

backend/app/routers/quotes.py, routers/resources.py          P4
backend/app/templates/quotes/*, templates/resources/*, static/css/resources.css  P4

backend/app/routers/classes.py, reports.py, admin.py, legal.py   P5
backend/app/services/moderation.py, services/audit.py        P5
backend/app/templates/classes/*, admin/*, legal/*, components/report_button.html  P5
backend/tests/conftest.py, tests/test_smoke.py, docs/OPERATIONS.md   P5
Each owner also writes backend/tests/test_<own module>.py      each
```

`main.py` (P1) imports every module in `app/routers/` (sorted by name) via `pkgutil`, calls `app.include_router(module.router)`, and then, if the module defines `setup(app: FastAPI) -> None`, calls it (used for middleware and exception handlers). Every router module therefore exposes `router = APIRouter()`.

## 4. Environment variables (defined in `.env.example` and `core/config.py`)

`ENV` (dev|prod), `DOMAIN` (Caddy site address, e.g. `example.cz` or `:80`), `BASE_URL` (e.g. `https://example.cz`), `SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` (`postgresql+psycopg://user:pass@db:5432/dbname`), `ALLOWED_EMAIL_DOMAIN` (default `spseiostrava.cz`), `ADMIN_EMAILS` (comma separated; these become role `admin` at login), `CONTACT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `UPLOAD_DIR` (default `/data/uploads`), `MAX_IMAGE_MB` (8), `MAX_RESOURCE_MB` (25), `AUTO_HIDE_REPORT_THRESHOLD` (3), `QUOTES_REQUIRE_APPROVAL` (true).
`settings` in `core/config.py` (pydantic-settings) exposes them as lowercase attributes (`settings.upload_dir`, `settings.admin_email_list` (parsed list), ...).

## 5. Database schema (authoritative; P1 implements models + one Alembic migration `0001_initial`)

Types: `id` = BIGINT identity PK; timestamps = `timestamptz` default `now()`; text "enums" are VARCHAR + CHECK constraint. Extensions created in migration: `citext`, `pg_trgm`, `unaccent`.

- `users`: id, email CITEXT UNIQUE NOT NULL (always stored lowercase), display_name VARCHAR(60) NOT NULL, role VARCHAR(12) NOT NULL default 'student' [student|teacher|moderator|admin], status VARCHAR(10) NOT NULL default 'active' [active|banned|deleted], created_at, last_login_at NULL, deleted_at NULL.
- `login_tokens`: id, email CITEXT NOT NULL, token_hash CHAR(64) UNIQUE NOT NULL, code_hash CHAR(64) NOT NULL, attempts INT NOT NULL default 0, expires_at, used_at NULL, ip VARCHAR(45), created_at. (hashes = HMAC-SHA256 hex with SECRET_KEY)
- `user_sessions`: id, token_hash CHAR(64) UNIQUE, user_id FK users ON DELETE CASCADE, created_at, last_seen_at, expires_at, ip VARCHAR(45), user_agent VARCHAR(255).
- `school_classes`: id, slug VARCHAR(40) UNIQUE, name VARCHAR(60), description VARCHAR(500) default '', created_by FK users, status VARCHAR(10) default 'pending' [pending|active|hidden], created_at.
- `class_members`: class_id FK CASCADE, user_id FK CASCADE, role VARCHAR(10) default 'member' [member|owner], status VARCHAR(10) default 'pending' [pending|approved], created_at; PK (class_id, user_id).
- `tags`: id, name VARCHAR(30) UNIQUE (lowercase).
- `memes`: id, author_id FK users, class_id FK school_classes NULL, caption VARCHAR(300) default '', image_path VARCHAR(200), thumb_path VARCHAR(200), width INT, height INT, likes_count INT default 0, status VARCHAR(10) default 'visible' [visible|hidden|deleted], created_at. Indexes: (status, id DESC), (class_id).
- `meme_tags`: meme_id FK CASCADE, tag_id FK CASCADE, PK both. `meme_likes`: meme_id FK CASCADE, user_id FK CASCADE, created_at, PK (meme_id, user_id).
- `quotes`: id, author_id FK users (submitter), class_id FK NULL, text VARCHAR(400), said_by VARCHAR(80) (free text, e.g. "p. uč. Novák"), context VARCHAR(200) default '', said_on DATE NULL, votes_count INT default 0, status VARCHAR(10) default 'pending' [pending|visible|hidden|deleted], created_at. Index (status, id DESC).
- `quote_votes`: quote_id FK CASCADE, user_id FK CASCADE, created_at, PK both.
- `resources`: id, author_id FK, class_id FK NULL, title VARCHAR(120), description VARCHAR(1000) default '', subject VARCHAR(40), school_year SMALLINT NULL (1-4), kind VARCHAR(10) [notes|test|exercises|link|other], url VARCHAR(500) NULL, file_path VARCHAR(200) NULL, file_name VARCHAR(200) NULL, file_size INT NULL, file_mime VARCHAR(100) NULL (CHECK: exactly one of url / file_path is non-null), upvotes_count INT default 0, downloads_count INT default 0, status VARCHAR(10) default 'visible' [visible|hidden|deleted], created_at, `search_vector` tsvector GENERATED ALWAYS AS (to_tsvector('simple', title || ' ' || description || ' ' || subject)) STORED + GIN index.
- `resource_votes`: resource_id FK CASCADE, user_id FK CASCADE, created_at, PK both. `resource_tags`: resource_id FK CASCADE, tag_id FK CASCADE, PK both.
- `reports`: id, reporter_id FK users, target_type VARCHAR(10) [meme|quote|resource|user|class], target_id BIGINT, reason VARCHAR(20) [spam|harassment|personal_info|inappropriate|copyright|other], details VARCHAR(500) default '', status VARCHAR(10) default 'open' [open|actioned|dismissed], handled_by FK users NULL, handled_at NULL, created_at; UNIQUE (reporter_id, target_type, target_id); index (status, target_type, target_id).
- `takedown_requests`: id, name VARCHAR(100), contact VARCHAR(200), target_url VARCHAR(500), message VARCHAR(2000), status VARCHAR(10) default 'open' [open|done], handled_by FK NULL, created_at.
- `audit_log`: id, actor_id FK users NULL, action VARCHAR(50), target_type VARCHAR(10) NULL, target_id BIGINT NULL, meta JSONB default '{}', created_at.

SQLAlchemy class names (all importable from `app.models`): `User, LoginToken, UserSession, SchoolClass, ClassMember, Tag, Meme, MemeLike, Quote, QuoteVote, Resource, ResourceVote, Report, TakedownRequest, AuditLog` (association tables `meme_tags`, `resource_tags` as `Table` objects). Relationships: `Meme.author, Meme.tags, Meme.school_class`, `Quote.author, Quote.school_class`, `Resource.author, Resource.tags, Resource.school_class`, `SchoolClass.members`, `ClassMember.user, ClassMember.school_class`.
Counters (`likes_count`, `votes_count`, `upvotes_count`, `downloads_count`) are updated atomically (`UPDATE ... SET x = x + 1`) by the route that owns the feature, in the same transaction as the row insert/delete.

Visibility rule everywhere: normal users see only `status='visible'` (schools_classes: `'active'`). Moderators/admins may also open hidden items (shown with a "skryto" badge). Authors additionally see their own `pending` quotes. Deleted items are never shown to anyone (404).

## 6. Shared Python interfaces (exact signatures)

- `app/core/config.py`: `settings` (see section 4).
- `app/core/db.py`: `Base` (DeclarativeBase), `engine`, `SessionLocal`, `def get_db() -> Iterator[Session]` (FastAPI dependency; commits are done explicitly by handlers with `db.commit()`).
- `app/core/templates.py`: `templates` (Jinja2Templates, directory = `app/templates`) and `def render(request: Request, template_name: str, status_code: int = 200, **ctx) -> HTMLResponse`. `render` always injects `request`, `user` (= `getattr(request.state, "user", None)`), `settings`, `flash` (read from flash cookie and cleared). Jinja filters/globals registered: `cs_date(dt)`, `cs_datetime(dt)`, `timeago(dt)` (Czech: "před 5 minutami"), `media_url(rel_path) -> "/media/" + rel_path`.
- `app/core/flash.py`: `def flash(response: Response, message: str, level: str = "info") -> None` (level: info|success|error).
- `app/core/storage.py`: `def save_bytes(subdir: str, data: bytes, ext: str) -> str` (returns relative path like `memes/3f/3f9c...uuid.webp`, random UUID names, 2-char shard dir, ext validated `[a-z0-9]{1,5}`), `def delete(rel_path: str | None) -> None` (silent if missing), `def abs_path(rel_path: str) -> Path` (raises `ValueError` on path traversal).
- `app/core/deps.py` (P2): `def current_user(request: Request) -> User | None`, `def require_user(request: Request) -> User`, `def require_mod(request: Request) -> User` (moderator or admin), `def require_admin(request: Request) -> User`. If not allowed: browser navigation gets 303 to `/login?next=<path>`, HTMX requests get 401 with header `HX-Redirect: /login`, insufficient role gets 403 page.
- `app/core/ratelimit.py` (P2): `def rate_limit(name: str, limit: int, seconds: int) -> Callable` returns a FastAPI dependency (in-process sliding window, keyed by user id if logged in else client IP); raises 429 with Czech message.
- `app/services/sessions.py` (P2): `SESSION_COOKIE = "session"`, `def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> str` (returns the raw cookie token; stores only its hash).
- `app/services/moderation.py` (P5): `def set_status(db, target_type: str, target_id: int, status: str, actor_id: int | None, reason: str = "") -> None`.
- `app/services/audit.py` (P5): `def log(db, actor_id: int | None, action: str, target_type: str | None = None, target_id: int | None = None, meta: dict | None = None) -> None`.
- Card macros (Jinja): `templates/memes/_card.html` -> `meme_card(meme, user)`; `templates/quotes/_card.html` -> `quote_card(quote, user)`; `templates/resources/_card.html` -> `resource_card(resource, user)`. Each card already calls the report macro.
- `templates/components/report_button.html` (P5) -> macro `report_button(target_type, target_id)` (usage: `{% from "components/report_button.html" import report_button %}`).
- Client IP: always `request.client.host` (gunicorn runs with proxy headers trusted, so this is the real IP behind Caddy).

## 7. Route map (owner in brackets)

- P1: `GET /` (landing for anonymous; dashboard with latest 8 meme thumbnails + 5 quotes for logged-in), `GET /healthz`.
- P2: `GET /login`, `POST /login` (field `email`), `GET /auth/verify?token=` (shows confirm page, does NOT consume), `POST /auth/verify` (field `token`), `POST /auth/code` (fields `email`, `code`), `POST /logout`, `GET /internal/auth-check` (204 if valid session cookie else 401, empty body, used by Caddy `forward_auth`), `GET /me`, `POST /me`, `POST /me/delete`.
- P3: `GET /memes`, `GET /memes/new`, `POST /memes`, `GET /memes/{id}`, `POST /memes/{id}/like`, `POST /memes/{id}/delete`.
- P4: `GET /quotes`, `GET /quotes/new`, `POST /quotes`, `POST /quotes/{id}/vote`, `POST /quotes/{id}/delete`; `GET /resources`, `GET /resources/new`, `POST /resources`, `GET /resources/{id}`, `GET /resources/{id}/download`, `POST /resources/{id}/vote`, `POST /resources/{id}/delete`.
- P5: `GET /classes`, `GET /classes/new`, `POST /classes`, `GET /c/{slug}`, `POST /c/{slug}/join`, `POST /c/{slug}/members/{user_id}/approve`, `POST /c/{slug}/members/{user_id}/remove`, `POST /c/{slug}/edit`; `POST /reports`; `GET /rules`, `GET /privacy`, `GET /takedown`, `POST /takedown`; `/admin` area (see P5 task).
- Media: files are served by Caddy at `/media/<relative path>` from `UPLOAD_DIR` ONLY after Caddy `forward_auth` to `web:8000/internal/auth-check` succeeds. Resource documents are NOT served via /media (they use `/resources/{id}/download`).

## 8. Conventions

- Feeds use cursor pagination: `?before=<last id>&limit=24` (default 24, max 60), ordered `id DESC`. When header `HX-Request: true` is present, return only the HTML fragment (cards + a sentinel `<div hx-get="...?before=ID" hx-trigger="revealed" hx-swap="outerHTML">`), otherwise the full page.
- POST handlers that change a whole page: validate, `db.commit()`, respond `303` redirect (with `flash(...)`). POST handlers triggered by small HTMX widgets (like/vote/report): return a small HTML fragment.
- Every POST/DELETE endpoint requires a logged-in user (via `Depends(require_user)`) except `/login`, `/auth/*`, `/takedown`. CSRF protection = SameSite=Lax cookies + Origin/Referer host check in P2's middleware; no tokens needed in forms.
- Validate all input on the server (length limits from the schema; return Czech error messages). Use SQLAlchemy parameters only. Never use `|safe` on user content.
- Author-only delete endpoints set `status='deleted'` and remove files via `storage.delete`. Moderators act through the admin area (P5), not through these endpoints.
- CSS: P1's `static/css/app.css` defines the design system. Available classes: `.container .stack .row .grid .card .btn .btn-primary .btn-danger .btn-ghost .input .textarea .select .form-field .form-error .badge .badge-warn .muted .pill .flash .flash-info .flash-success .flash-error .htmx-indicator .visually-hidden .empty-state`. CSS variables: `--bg --fg --muted --card --border --accent --danger --radius`, automatic dark mode via `prefers-color-scheme`. Modules may add their own stylesheet loaded through `{% block head_extra %}`.
- Template blocks in `base.html`: `title`, `head_extra`, `content`, `scripts` (scripts only via `<script src=...>`). Navigation (P1 `components/nav.html`) links to: `/memes`, `/quotes`, `/resources`, `/classes`, `/me`, `/admin` (moderators only), and `POST /logout`.
- Tests: pytest + `fastapi.testclient.TestClient`, run with `docker compose run --rm web pytest`. Fixtures provided by P5 in `tests/conftest.py`: `db` (Session), `client` (TestClient), `make_user(email=None, role="student", status="active") -> User`, `login(client, user) -> None` (uses `create_session` and sets the cookie). Tests must not need network or SMTP.
- Every file you write starts with a one-line comment stating its purpose.

---

# YOUR TASK: PROMPT 5 of 5 - Class profiles, reporting, moderation/admin, legal pages, tests, ops

You own everything marked P5. This part decides whether the site stays trouble-free: build it carefully. You also write the test fixtures and the smoke test that verifies the whole merged project.

## A. Class profiles (`routers/classes.py`, `templates/classes/*`)

- `GET /classes`: list of ACTIVE classes (name, member count) + button "Založit profil třídy".
- `GET /classes/new`, `POST /classes`: any logged-in user requests a class (`name` 2-60, `description` <= 500). Slug generated from the name (`^[a-z0-9-]{2,40}$`, transliterate Czech diacritics, ensure uniqueness with a numeric suffix). Created as status `pending` (an admin approves in the admin area); creator becomes `owner` with `approved` membership. Rate limit 3/day/user. A user may hold at most 3 approved memberships.
- `GET /c/{slug}`: header (name, description, member count), tabs/sections with the latest 12 VISIBLE memes, quotes and resources of the class (`class_id`), using the macros `meme_card`, `quote_card`, `resource_card` from the contract, plus links to the full filtered feeds (`/memes?class=slug`, `/quotes?class=slug`, `/resources?class=slug`). Members list (display names) for logged-in users. Pending classes are visible only to their owner and moderators; hidden -> moderators only.
- `POST /c/{slug}/join` (creates a `pending` membership; owner-less/auto-approve is NOT allowed), `POST /c/{slug}/members/{user_id}/approve|remove` (owner or moderator/admin), `POST /c/{slug}/edit` (owner: description only), members may leave via `remove` on themselves.

## B. Reporting (`routers/reports.py`, `templates/components/report_button.html`)

- Macro `report_button(target_type, target_id)`: renders a `<details class="report">` element (works WITHOUT JS and without inline handlers) containing a small form: reason `<select>` (spam, harassment, personal_info, inappropriate, copyright, other with Czech labels), optional details (<= 500), submit using `hx-post="/reports"` with `hx-target` = the details element and `hx-swap="outerHTML"`.
- `POST /reports`: fields `target_type` (meme|quote|resource|user|class), `target_id`, `reason`, `details`. Validate the target exists and is not deleted; users cannot report themselves/their own content; one report per (reporter, target) (unique constraint -> friendly "Už jsi nahlásil/a"); rate limit 20/hour/user. Returns a fragment "Děkujeme, moderátoři se na to podívají." After inserting, count DISTINCT reporters with open reports on the target; when the count reaches `settings.auto_hide_report_threshold` and the target type is meme/quote/resource/class, call `moderation.set_status(..., 'hidden', ...)` and write an audit entry `auto_hide`. Users are never auto-banned.

## C. Moderation core (`services/moderation.py`, `services/audit.py`)

- `TARGETS` mapping type -> model + valid statuses (`class` uses `active/hidden`, users use `active/banned`). `set_status(...)` validates and updates, `audit.log` records who/what/why. Helpers to fetch a target for previews.

## D. Admin area (`routers/admin.py`, `templates/admin/*`)

Access: `require_mod` for everything except role changes and class approval settings, which need `require_admin`. Czech UI, dense readable tables, works on mobile.
- `GET /admin`: dashboard counters (open reports, pending quotes, pending classes, open takedowns, users, banned users).
- `GET /admin/reports`: open reports GROUPED by target (count, reasons, latest details, preview of the reported content with its author), with actions via `POST /admin/reports/{target_type}/{target_id}/resolve` field `action` in `hide | restore | delete | dismiss | ban_author`. Each action updates all open reports on that target (`actioned`/`dismissed`, `handled_by`, `handled_at`), changes the target status, writes the audit log, and (for `ban_author`) sets the author `banned`, destroys their sessions and optionally hides all their content (checkbox). A moderator cannot ban admins or themselves.
- `GET /admin/quotes` pending quotes with `POST /admin/quotes/{id}/approve|reject` (approve -> `visible`, reject -> `deleted`).
- `GET /admin/classes` pending/hidden classes with approve/hide actions.
- `GET /admin/users`: search by email/name, paginated; ban/unban; role change (admin only, roles student/teacher/moderator/admin; cannot demote the last admin).
- `GET /admin/audit` paginated audit log. `GET /admin/takedowns` list + `POST /admin/takedowns/{id}/done`.

## E. Legal / trust pages (`routers/legal.py`, `templates/legal/*`)

- `GET /rules` (Czech community rules: respect, no harassment, no personal data or photos of people without consent, no illegal content, quotes must be harmless, moderators may remove anything, reports are handled by real people), `GET /privacy` (what is stored: school email, display name, content, IPs in login/session records, retention, deletion via /me, contact `settings.contact_email`, unofficial site not operated by the school), `GET /takedown` + `POST /takedown` (PUBLIC form for teachers/students/parents: name, contact, URL of the content, message; rate limit 3/hour/IP; stored in `takedown_requests`; confirmation page). Add a visible note in the page footer text of these pages that texts are a draft template that the operator should review.

## F. Tests and operations

- `tests/conftest.py`: creates a separate test database (name = main DB name + `_test`) using `DATABASE_URL`, runs `alembic upgrade head` once per session, rolls back/cleans between tests; fixtures exactly as in the contract (`db`, `client`, `make_user`, `login`).
- `tests/test_smoke.py` (the integration check for the merged project): (1) anonymous GET on every private route returns a redirect to `/login`, public routes return 200; (2) as student, moderator and admin, GET every route in the contract's route map that has no path parameters, none may return 500; (3) full journey: create user -> upload a meme -> create quote -> add resource link -> report each -> moderator hides -> content disappears for students.
- `tests/test_moderation.py`: auto-hide threshold, duplicate report rejected, own-content report rejected, ban flow, last-admin protection.
- `docs/OPERATIONS.md` (English): moderator handbook (daily routine, how to treat reports, what to do about a takedown request), backup/restore test procedure, how to update, how to delete a user on request, incident checklist (leaked content, spam wave: how to ban a wave and rate-limit at Cloudflare), and a list of the manual checks to run after the first deploy.

## Acceptance criteria

- Every report path works without JavaScript except the small HTMX enhancement, and never exposes reporter identity to normal users.
- All admin actions are audited; all admin routes reject normal users with 403.
- Only files you own are written; use only shared interfaces from the contract.
