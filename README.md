# NoTox

**NoTox** is a real-time contextual and visual moderation platform designed for online chat, social communities, and livestreaming. The platform is being built incrementally across 14 developmental stages.

---

## Tech Stack

- **Backend:** Python 3.11+, Django 5, Django REST Framework, `djangorestframework-simplejwt`, PostgreSQL
- **Frontend:** React 18, Vite, Tailwind CSS, Axios, React Router
- **Real-Time Communication:** WebSockets using Django Channels
- **Architecture:** Modular Django app architecture with decoupled REST APIs and a responsive SPA frontend

---

## Project Structure

notox/

├── backend/
│   ├── config/              # Root settings, routing, WSGI/ASGI configurations
│   ├── apps/
│   │   ├── accounts/        # User accounts, authentication, profiles & trust score service
│   │   └── chat/            # Real-time global chat using Django Channels
│   ├── manage.py
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── components/      # Reusable UI components (Navbar, ProtectedRoute, LoadingSpinner)
    │   ├── context/         # AuthContext (global authentication & profile state)
    │   ├── hooks/           # useAuth hook
    │   ├── layouts/         # MainLayout shell
    │   ├── pages/           # Landing, Login, Register, Profile, Dashboard, GlobalChat
    │   ├── services/        # api.js (Axios client & interceptors), authService.js
    │   └── utils/           # Client-side form validators
    ├── package.json
    └── .env.example
```

---

## Stages Implemented

### Stage 1 — Project Foundation & Authentication
- **Custom User Model:** UUID-keyed `User` model inheriting from `AbstractBaseUser` and `PermissionsMixin`.
- **JWT Authentication:** Secure registration, login (via username or email), token rotation, silent token refreshing, and refresh token blacklisting on logout.
- **Frontend Auth Integration:** React authentication context, persistent tokens in storage with automatic Axios 401 interceptor retry, route protection, and form validation.
- **Database & Error Handling:** PostgreSQL integration with unified DRF exception responses.

### Stage 2 — User Profiles & Trust Score Foundation
- **User Profiles:** Extended user schema with `display_name`, `bio`, `avatar` (URL), `phone_number`, `role`, and `trust_score`.
- **Role System:** Defined role choices (`user`, `moderator`, `admin`) with reusable permission classes (`IsAdminRole`, `IsModeratorRole`).
- **Trust Score Engine Foundation:**
  - Initial score initialized to `100`.
  - Strict bounded range between `0` and `100`.
  - Centralized `TrustScoreService` (`clamp_score`, `set_trust_score`, `increase_trust_score`, `decrease_trust_score`, `reset_trust_score`).
- **Profile API:** Authenticated `GET` and `PATCH` endpoints on `/api/profile/` and `/api/auth/me/`. Users can update safe fields (`display_name`, `bio`, `avatar`), while system fields (`trust_score`, `role`, `strikes`, `restrictions`) are strictly immutable via the API.
- **Profile UI:** Interactive profile dashboard featuring avatar display, role badges, trust score meter (`████████████████████ 100/100`), status tier badges, and inline profile editing with live preview.
- **Automated Tests:** 24 unit and API tests validating authentication, profile retrieval/update, authorization boundaries, trust score clamping/mutations, and cross-user isolation.

### Stage 3A — Chat foundation (early)
- **ChatMessage Persistence:** UUID-keyed `ChatMessage` model with nullable `sender` FK, `content` (up to 2000 characters), and indexed `created_at` timestamp.
- **WebSocket Protocol & Lifecycle:** ASGI-routed WebSocket on `ws://localhost:8000/ws/chat/` with two-step handshake (`auth_required` -> `authenticate`).
- **Restriction-Aware Access:** Integrated `User.is_currently_restricted()` with lazy clearance of expired restrictions. Restricted users receive close code `4403` on connect and mid-session.
- **Token Expiry Enforcement:** Evaluates access token `exp` timestamp on incoming messages, terminating expired sessions with close code `4401`.
- **Pre-Broadcast Storage:** Messages are saved via `database_sync_to_async` before group broadcast, delivering consistent server `id` and ISO `created_at` timestamps to all clients.
- **Message History API:** `GET /api/chat/messages/` protected by `IsAuthenticated` and `IsNotRestricted`, returning the latest 50 messages oldest-first with `before` cursor ISO pagination.
- **Frontend Resilience:** Automatic WebSocket reconnection with capped exponential backoff, single silent token refresh retry on `4401`, clear restricted status banner, and historical message loading.
- **Channel Layer:** Configured with `InMemoryChannelLayer` for local development and testing (note: `channels-redis` is required for multi-process or production use).

### Stage 3B — Bloom Pre-Filter as Chat Moderation Layer 2
- **Three-Layer Moderation Pipeline:** `Keyword Filter (L1)` &rarr; `Bloom Pre-Check (L2)` &rarr; `AI Provider (L3)`.
  - **Layer 1:** Instant profanity blocking via keyword matcher with unique message IDs.
  - **Layer 2 (Bloom Pre-Filter):** Fast-path evaluation bypassing Layer 3 for clean messages with zero toxic token hits.
  - **Layer 3:** Asynchronous AI provider interface (`NullProvider` default, `MockProvider` with simulated latency and ground truth rules).
- **Fast-Path Eligibility:** Messages are only marked `clean` if:
  1. No toxic-set hit in Bloom filter.
  2. Sender `trust_score >= BLOOM_MIN_TRUST` (default 80).
  3. No URL detected.
  4. Content is mostly ASCII (&ge; 80%).
  5. Content length is within `BLOOM_MAX_LENGTH` (default 500 characters).
  Otherwise, messages are treated as `uncertain` and forwarded to Layer 3.
- **Normalization Invariant:** Generates lowercase, NFKC, zero-width stripped, collapsed repeats, de-leeted, and spaced-letter joined variants. Unigram and bigram lookup keys are combined monotonically as a set union — normalization only adds candidate keys and can only raise the uncertain rate, never turning an uncertain message into clean.
- **Backends & Sizing:**
  - `LocalBloomBackend`: In-memory bit array with Kirsch-Mitzenmacher double-hashing using SHA-256 slices ($m \approx 718\text{k bits} \approx 90\text{ KB}$, $k=10$ for $n=50\text{k}, p=0.001$).
  - `RedisBloomBackend`: High-concurrency backend using `redis.asyncio` with raw `execute_command("BF.MEXISTS", ...)` (one round trip per message).
- **Fail-Safe Resilience:** If Redis is down, the module is missing, or the call times out beyond `BLOOM_TIMEOUT_MS`, the message fails safe to `uncertain` and is sent to the provider. Failures are logged at most once per minute to avoid log spamming.
- **Audit Sampling & Measurement:** Configurable `BLOOM_AUDIT_RATE` (default 5%) asynchronously audits clean messages with Layer 3 to continually measure the empirical miss rate. Disagreements are logged.
- **ModerationLog Auditing:** `ModerationLog` model records pipeline stage, verdict, bloom status, and latency. Clean messages record metadata only for privacy, while offending text is stored only for blocked or flagged messages.
- **Reworded FR7:** The functional requirement FR7 has been formally reworded to specify the Layer 2 Bloom pre-filter safety guarantee (zero false negatives on toxic set, >=75% provider call reduction, audit sampling). See `docs/SRS_SDS_UPDATES.md`.
- **Management Commands:**
  - `python manage.py bloom_seed`: Idempotently seeds the Bloom filter with toxic words from `better_profanity` and custom extras (e.g. Romanized Hindi slurs).
  - `python manage.py benchmark_bloom`: Runs automated benchmarks measuring API reduction (77.55%), latency speedup (2.57x-3.49x), empirical FPR, and labeled dataset miss rate (0.00%). Results saved to `docs/BENCHMARK_REPORT.md`.

---

## API Endpoints

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| POST | `/api/auth/register/` | No | Create an account, returns user data + JWT tokens |
| POST | `/api/auth/login/` | No | Authenticate with username/email and password |
| POST | `/api/auth/logout/` | Yes | Blacklist refresh token and log out |
| POST | `/api/auth/token/refresh/` | No | Obtain new access token via refresh token |
| GET | `/api/auth/me/` | Yes | Retrieve authenticated user's profile |
| PATCH | `/api/auth/me/` | Yes | Update safe profile fields (`display_name`, `bio`, `avatar`) |
| GET | `/api/profile/` | Yes | Retrieve authenticated user's profile |
| PATCH | `/api/profile/` | Yes | Update safe profile fields (`display_name`, `bio`, `avatar`) |
| GET | `/api/chat/messages/` | Yes (Unrestricted) | Retrieve latest 50 chat messages (oldest-first, optional `before` cursor) |

## WebSocket Endpoint
| Protocol | Endpoint | Auth Required | Description |
| ---|---|---|---|
| WebSocket | ws://localhost:8000/ws/chat/ | JWT Access Token | Real-time global chat communication |

---

## Getting Started

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
# Activate virtual environment:
# Windows: .\.venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

# Configure database in .env, then migrate:
python manage.py migrate
python manage.py runserver
```

### 2. Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The frontend will run at `http://localhost:5173/` and communicate with the backend at `http://localhost:8000/api/`.

---

## Running Tests

Run the full backend test suite:

```bash
cd backend
python manage.py test
```

