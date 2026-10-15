# NoTox — Real-Time Contextual & Visual Moderation Platform

**NoTox** is a real-time contextual moderation platform engineered for online chat, community discussions, and livestreaming. It features a progressive 3-stage moderation pipeline designed to eliminate toxic content while drastically reducing expensive AI moderation API overhead.

---

## ⚡ Key Highlights

- **Multi-Stage Moderation Pipeline:** Layer 1 Keyword Filter $\rightarrow$ Layer 2 Bloom Pre-Check $\rightarrow$ Layer 3 AI Provider.
- **77.5%+ AI Call Reduction:** Clean messages from trusted users bypass AI provider calls via high-speed Bloom pre-filtering.
- **Zero False Negatives Target:** Strict mathematical guarantees ensure no seeded toxic word or obfuscation bypasses Layer 2.
- **Trust Score Engine:** Dynamic trust scores ($0 - 100$) gating user privileges and fast-path moderation.
- **High Concurrency & Resilience:** Asynchronous WebSockets via Django Channels with automatic fail-safe fallback if cache layers go offline.

---

## 🛠 Tech Stack

| Domain | Technologies |
|---|---|
| **Backend** | Python 3.11+, Django 5, Django REST Framework, Django Channels (ASGI), Daphne |
| **Authentication** | JWT (`djangorestframework-simplejwt`) with rotation & blacklisting |
| **Databases & Cache** | PostgreSQL (persistent storage), SQLite (dev), Redis / Memurai (Channels & Bloom Filter) |
| **Chat Moderation** | `better-profanity`, RedisBloom / In-Memory Double-Hash Bloom Filter, AI Provider Hooks |
| **Frontend** | React 18, Vite, Tailwind CSS, Axios, React Router, WebSockets |

---

## 🏗 Architecture & Moderation Pipeline

```
[ Incoming Message ]
         │
         ▼
┌─────────────────────────────────┐
│   Layer 1: Keyword Filter       │ ──► [ Toxic Match ] ──► Instant Block (403)
│   (better_profanity + rules)    │
└─────────────────────────────────┘
         │ (Passed)
         ▼
┌─────────────────────────────────┐
│   Layer 2: Bloom Pre-Check      │
│   (NFKC, de-leet, repeats,      │
│    spaced-letters, bigrams)     │
└─────────────────────────────────┘
         │
         ├─── [ Eligible Clean Message ] ─────────► [ Fast-Path Allow ] (Sub-millisecond)
         │    • No toxic-set hit                         │
         │    • trust_score >= BLOOM_MIN_TRUST           │ (5% Async Audit Sample)
         │    • No URLs detected                         ▼
         │    • Content is mostly ASCII          ┌───────────────────────────────────┐
         │    • Message length within cap        │   Layer 3: AI Provider            │
         │                                       │   (Null / Mock / Perspective /    │
         └─── [ Uncertain / Toxic Match ] ──────►│    Toxic-BERT / OpenAI)           │
                                                 └───────────────────────────────────┘
                                                           │
                                                           ▼
                                                 [ Final Verdict & Log ]
```

---

## 📂 Project Structure

```text
notox/
├── backend/
│   ├── config/                      # Settings, ASGI routing, WSGI
│   ├── apps/
│   │   ├── accounts/                # User model, JWT authentication, Trust Score service
│   │   ├── chat/                    # Real-time WebSocket consumers, services, models
│   │   │   ├── moderation/          # Normalization, tokenization, Bloom backends, providers
│   │   │   └── management/commands/ # bloom_seed & benchmark_bloom commands
│   │   └── streams/                 # Livestreaming consumer & WebRTC signaling
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/              # Navbar, ProtectedRoute, LoadingSpinner
│   │   ├── context/                 # AuthContext (state & tokens)
│   │   ├── pages/                   # GlobalChat, Dashboard, Profile, Login, Register
│   │   └── services/                # Axios API client, WebSocket handlers
│   └── package.json
└── docs/
    ├── BENCHMARK_REPORT.md          # Automated benchmark results & miss-rate findings
    └── SRS_SDS_UPDATES.md           # Formal specifications & reworded FR7
```

---

## 🚀 Development Roadmap & Completed Stages

<details open>
<summary><b>Stage 1 — Project Foundation & Authentication</b></summary>
<br>

- **Custom User Model:** UUID-keyed `User` model (`AbstractBaseUser` + `PermissionsMixin`).
- **JWT Authentication:** Registration, login (username or email), silent token rotation, and blacklisting.
- **Frontend Auth Integration:** React context with persistent storage, auto-retry Axios 401 interceptor, and route guards.
- **Database & Errors:** Unified DRF exception handler and PostgreSQL schema.
</details>

<details open>
<summary><b>Stage 2 — User Profiles & Trust Score Engine</b></summary>
<br>

- **User Profiles:** Safe fields (`display_name`, `bio`, `avatar`, `phone_number`, `role`).
- **Role-Based Access Control:** Reusable permissions for `User`, `Moderator`, and `Admin`.
- **Trust Score Engine:** Standardized range ($0 - 100$, default $100$) with `TrustScoreService` mutation helpers.
- **Interactive UI:** Live profile dashboard with avatar preview and trust score meter.
</details>

<details open>
<summary><b>Stage 3A — Real-Time Chat Foundation</b></summary>
<br>

- **ChatMessage Persistence:** UUID-keyed `ChatMessage` model with indexed `created_at` timestamps.
- **WebSocket Protocol:** ASGI two-step handshake (`auth_required` $\rightarrow$ `authenticate`).
- **Restriction Enforcement:** Automatic disconnection (code `4403`) for restricted accounts and expired token cutoff (code `4401`).
- **History API:** `GET /api/chat/messages/` with cursor-based pagination, returning oldest-first history.
</details>

<details open>
<summary><b>Stage 3B — Bloom Pre-Filter as Chat Moderation Layer 2</b></summary>
<br>

- **3-Layer Pipeline:** Keyword Filter (L1) $\rightarrow$ Bloom Pre-Check (L2) $\rightarrow$ AI Provider (L3).
- **Fast-Path Eligibility:** Clean verdict is honored only when:
  1. Zero toxic-set hits in Bloom filter.
  2. Sender `trust_score >= BLOOM_MIN_TRUST` (default 80).
  3. No URLs present.
  4. Content is mostly ASCII (&ge; 80%).
  5. Message length is within `BLOOM_MAX_LENGTH` (default 500 chars).
- **Monotonic Normalization Invariant:** Keys are unigrams and bigrams derived from NFKC normalization, zero-width character stripping, repeat collapsing, de-leeting, and spaced-letter joining. Normalization only adds candidate keys and can only raise the uncertain rate, never lowering it.
- **Dual Backends:**
  - `LocalBloomBackend`: In-memory bit array with Kirsch-Mitzenmacher double-hashing ($m \approx 90\text{ KB}, k=10$ for $n=50\text{k}, p=0.001$).
  - `RedisBloomBackend`: Async raw `BF.MEXISTS` command executing in a single round-trip per message.
- **Fail-Safe & Rate-Limited Logging:** If Redis is down or times out (`BLOOM_TIMEOUT_MS`), messages fail-safe to `uncertain` and route to the provider. Failures are logged at most once per minute.
- **Audit Sampling & Logging:** 5% of clean messages are asynchronously evaluated by the provider to continuously monitor real miss rates. Disagreements and outcomes are recorded in `ModerationLog`.
- **Reworded FR7:** Formally reworded to specify Layer 2 Bloom safety guarantees and audit requirements (see [`docs/SRS_SDS_UPDATES.md`](docs/SRS_SDS_UPDATES.md)).
</details>

---

## 📊 Benchmark Summary (Stage 3B)

Automated benchmarks measure performance across the three SDS axes, empirical miss rates, and clean traffic uncertain rates:

| Metric | Without Bloom Filter | With Bloom Filter (Layer 2) | Improvement |
|---|:---:|:---:|:---:|
| **Provider API Calls (300 msgs)** | 245 calls | 55 calls | **77.55% Reduction** |
| **Mean End-to-End Latency** | 26.24 ms | 11.66 ms | **2.25x Speedup** |
| **p50 (Median) Latency** | 30.67 ms | 9.52 ms | **3.22x Speedup** |
| **Local Lookup Latency** | — | **0.128 ms** | Sub-millisecond |
| **Measured Toxic Miss Rate** | — | **0.00%** | Zero false negatives |
| **Clean Fast-Patched Traffic** | 0.00% | **95.00%** | 95% skip Layer 3 |

*Detailed benchmark methodology and FPR sweeps available in [`docs/BENCHMARK_REPORT.md`](docs/BENCHMARK_REPORT.md).*

---

## 🔌 API & WebSocket Reference

### REST Endpoints

| Method | Endpoint | Auth Required | Description |
|---|---|:---:|---|
| `POST` | `/api/auth/register/` | No | Register new user account |
| `POST` | `/api/auth/login/` | No | Authenticate and obtain JWT token pair |
| `POST` | `/api/auth/token/refresh/` | No | Refresh expired access token |
| `POST` | `/api/auth/logout/` | Yes | Blacklist refresh token and log out |
| `GET` | `/api/auth/me/` | Yes | Retrieve current user profile |
| `PATCH` | `/api/profile/` | Yes | Update profile fields (`display_name`, `bio`, `avatar`) |
| `GET` | `/api/chat/messages/` | Yes | Fetch chat history (50 messages, oldest-first, cursor pagination) |

### WebSocket Endpoint

| Protocol | Endpoint | Handshake | Purpose |
|---|---|---|---|
| `ws://` / `wss://` | `/ws/chat/` | `auth_required` $\rightarrow$ `authenticate` | Real-time chat & moderation streaming |

---

## 💻 Getting Started

### 1. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env

# Run database migrations
python manage.py migrate

# Seed Bloom filter with toxic words
python manage.py bloom_seed

# Start ASGI development server
python manage.py runserver
```

### 2. Frontend Setup

```bash
cd frontend

# Install packages
npm install

# Configure environment variables
cp .env.example .env

# Start Vite dev server
npm run dev
```

The frontend runs at `http://localhost:5173/` and proxies API requests to `http://localhost:8000/`.

---

## 🧪 Testing & Verification

Run the full backend test suite:

```bash
cd backend
python manage.py test
```

Run moderation-specific property and fail-safe tests:

```bash
python manage.py test apps.chat.tests_moderation
```

Run the automated Bloom performance benchmark:

```bash
python manage.py benchmark_bloom --save-report ../docs/BENCHMARK_REPORT.md
```
