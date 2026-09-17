# NoTox — Stage 1: Authentication & Identity

NoTox is a real-time social interaction moderation platform, being built in
incremental stages. **This repository currently contains Stage 1 only**:
project scaffolding, a custom user model, and JWT-based authentication.
Everything else (feed, chat, moderation, trust engine, streaming, etc.) is
intentionally not implemented yet — see "What's not in Stage 1" below.

---

## 1. Architecture overview

```
notox/
  backend/                  Django REST API
    config/                 Project settings, root URLs, ASGI/WSGI
    apps/
      accounts/              Custom user model + JWT auth (the only app so far)
    manage.py
    requirements.txt
    .env.example
  frontend/                 React (Vite) SPA
    src/
      components/            Reusable UI (Navbar, ProtectedRoute, LoadingSpinner)
      pages/                 Landing, Login, Register, Profile, Dashboard
      layouts/               MainLayout (navbar + page shell)
      services/              api.js (Axios client), authService.js
      context/               AuthContext (global auth state)
      hooks/                 useAuth()
      utils/                 Client-side form validators
    package.json
    .env.example
```

**Backend:** Django 5 + Django REST Framework + `djangorestframework-simplejwt`,
PostgreSQL, ASGI-ready (Channels/websockets are wired into `config/asgi.py`
in a later stage, not this one).

**Frontend:** React 18 + Vite + Tailwind CSS + Axios + React Router.

The backend is modular by design: every future feature (posts, comments,
moderation, chat, streaming, trust, reports, dashboard) gets its own app
under `backend/apps/`, following the same shape as `accounts/`. Nothing in
Stage 1 needs to be restructured for that to happen.

---

## 2. Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ running locally (or accessible via network)
- (Optional for this stage) Redis or Memurai — not required for auth to work

---

## 3. Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env: set SECRET_KEY, DB_NAME, DB_USER, DB_PASSWORD
```

### Create the PostgreSQL database

```bash
# adjust to your local Postgres setup
createdb notox
# or, from psql:
#   CREATE DATABASE notox;
#   CREATE USER notox_user WITH PASSWORD 'change-me';
#   GRANT ALL PRIVILEGES ON DATABASE notox TO notox_user;
```

### Migrate and run

```bash
python manage.py makemigrations accounts
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

The API is now at `http://localhost:8000/api/`.

### Run backend tests

```bash
python manage.py test apps.accounts
```

All 12 tests (registration, duplicates, login, `/me`, roles, defaults) are
included and pass against a real database connection.

---

## 4. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env    # VITE_API_BASE_URL defaults to http://localhost:8000/api
npm run dev
```

The app is now at `http://localhost:5173/`.

---

## 5. Environment variables

### Backend (`backend/.env`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key — generate a long random string |
| `DEBUG` | `True` locally, `False` in production |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | Reserved for later stages (Channels, caching, Bloom filter). Auth works without Redis running. |
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`, `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | Token lifetimes |
| `CORS_ALLOWED_ORIGINS` | Frontend origin(s) allowed to call the API |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` | Placeholder only — leave blank. Phone OTP is not implemented yet (see `apps/accounts/services.py`); the app runs fine without these. |

### Frontend (`frontend/.env`)

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Base URL of the backend API, e.g. `http://localhost:8000/api` |

---

## 6. API endpoints (Stage 1)

| Method | Endpoint | Auth required | Description |
|---|---|---|---|
| POST | `/api/auth/register/` | No | Create an account, returns user + JWT pair |
| POST | `/api/auth/login/` | No | Login with username or email + password |
| POST | `/api/auth/logout/` | Yes | Blacklists the given refresh token |
| POST | `/api/auth/token/refresh/` | No (needs refresh token) | Exchange a refresh token for a new access token |
| GET | `/api/auth/me/` | Yes | Return the authenticated user's profile |

---

## 7. Manual testing checklist

1. Start Postgres, then the backend (`python manage.py runserver`).
2. Start the frontend (`npm run dev`), visit `http://localhost:5173/`.
3. Landing page loads with **Sign up** / **Login** options.
4. Register a new account → redirected to `/dashboard`, shows your username, role, trust score, strikes.
5. Visit `/profile` → shows email, phone, trust score, strikes, restriction status, join date.
6. Log out → redirected to `/login`.
7. Try visiting `/dashboard` or `/profile` directly while logged out → redirected to `/login`.
8. Log back in with the same username/email + password.
9. Refresh the page while logged in → session persists (access token still valid, or silently refreshed).
10. Try registering the same username or email again → clear inline error, no crash.
11. Try logging in with a wrong password → clear inline error.
12. Stop the backend and try to log in → frontend shows "Can't reach the server," not a raw error/stack trace.

---

## 8. Known limitations (Stage 1)

- **Tokens are stored in `localStorage`**, not an httpOnly cookie. This is
  the simplest option for Stage 1 and is fine for local development, but it
  is more exposed to XSS than a cookie-based flow. Moving to httpOnly
  cookies is a reasonable hardening step for a later stage — it requires
  backend CSRF handling changes, so it wasn't bundled into Stage 1 to avoid
  scope creep on the auth flow itself.
- **Phone OTP is not implemented.** `is_phone_verified` exists on the model
  and a clean `OTPService` abstraction exists in
  `apps/accounts/services.py`, but no real Twilio calls are made. Registering
  without a phone number, or with an unverified one, is fully supported.
- **No rate limiting** on login/register endpoints yet. Add this before any
  public deployment.
- **No password reset flow.** Not requested for Stage 1.
- Redis/Memurai settings are wired up but unused — nothing currently
  depends on Redis being available.

---

## 9. What must NOT change in later stages

These were deliberately built to be extension points — later stages should
build *on* them, not replace them:

- `apps/accounts/models.py` — the `User` model's existing fields and
  defaults (`trust_score=100`, `strike_count=0`, `role=regular`, etc.).
  Add fields/methods; don't rename or remove existing ones.
- `apps/accounts/permissions.py` — `IsAdminRole` and `IsNotRestricted` are
  meant to be imported by future apps (posts, comments, chat), not
  reimplemented.
- `apps/accounts/services.py` — `get_otp_service()` is the only place that
  should ever construct an OTP backend; don't call Twilio directly from
  views/serializers in a later stage.
- `frontend/src/services/api.js` — the single Axios instance with its
  token-refresh interceptor. Every future service module should import
  `apiClient` from here rather than creating its own Axios instance.
- `frontend/src/context/AuthContext.jsx` — the shape of `user`,
  `isAuthenticated`, and `loading`, and the `login/register/logout/
  refreshToken/getCurrentUser` function names.
- The Django app-per-domain structure under `backend/apps/` — keep new
  features (posts, comments, moderation, chat, etc.) in their own apps
  rather than adding them into `accounts/`.

---

## 10. What's not in Stage 1

By design, none of the following exist yet: AI moderation, OpenAI/Perspective/
Toxic-BERT integration, Bloom filter pre-filtering, real-time chat/WebSockets,
posts, comments, live audio/video, Whisper, computer vision, strikes/
restrictions enforcement, trust score calculation, reports, or the admin/
moderator dashboard. These are future stages — say **"START STAGE 2"** when
ready to begin the next one.
