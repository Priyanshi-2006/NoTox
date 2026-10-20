# NoTox — Real-Time Contextual & Visual Moderation Platform

**NoTox** is a real-time contextual moderation platform engineered for online chat, community discussions, and livestreaming. It features a progressive 3-stage moderation pipeline designed to eliminate toxic content while drastically reducing expensive AI moderation API overhead, alongside a real-time pre-broadcast live audio moderation and silence-censorship engine.

---

## ⚡ Key Highlights

- **Multi-Stage Moderation Pipeline:** Layer 1 Keyword Filter $\rightarrow$ Layer 2 Bloom Pre-Check $\rightarrow$ Layer 3 AI Provider.
- **77.5%+ AI Call Reduction:** Clean messages from trusted users bypass AI provider calls via high-speed Bloom pre-filtering.
- **Zero False Negatives Target:** Strict mathematical guarantees ensure no seeded toxic word or obfuscation bypasses Layer 2.
- **Live Audio Moderation & Pre-Broadcast Censorship:** Real-time offline speech recognition (Vosk) paired with an AudioWorklet 1.5-second delay buffer that silences profane words before WebRTC broadcast without beep sounds.
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
| **Live Audio & Livestreaming** | Vosk (offline Kaldi speech-to-text), Web Audio API (`AudioWorkletProcessor`), WebRTC (`RTCPeerConnection`) |
| **Frontend** | React 18, Vite, Tailwind CSS, Axios, React Router, WebSockets |

---

## 🏗 Architecture & Moderation Pipeline

### Chat Moderation Pipeline

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
         │    • Content is mostly ASCII          ┌───────────────────────────────────────────────┐
         │    • Message length within cap        │  Layer 3: AI Provider & Contextual Analysis   │
         │                                       │  • HuggingFace Inference / Mock / Null        │
         └─── [ Uncertain / Toxic Match ] ──────►│  • Bounded context window (recent messages)   │
                                                 │  • Clamped scores: toxicity, insult, threat   │
                                                 └───────────────────────────────────────────────┘
                                                                 │
                                                                 ▼
                                                 ┌───────────────────────────────────────────────┐
                                                 │  Moderation Policy Engine                     │
                                                 │  • ALLOW  : Clean / harmless sarcasm / banter │
                                                 │  • REVIEW : Ambiguous / amber zone (flagged)  │
                                                 │  • BLOCK  : Threat / high toxicity / insult   │
                                                 └───────────────────────────────────────────────┘
                                                                 │
                                                                 ▼
                                                 [ Final Verdict & ModerationLog ]
```

### Live Audio Moderation & Pre-Broadcast Censorship Pipeline

```
[ Host Microphone Input ]
           │
           ▼
┌───────────────────────────────────────────────┐
│  AudioWorklet (public/audio-processor.js)     │
│  • Resamples mic audio to 16 kHz mono         │
│  • Buffers raw audio in 1.5s circular delay   │
│  • Synchronizes Vosk timeline offset          │
│  • Streams 100ms PCM16 chunks via WebSocket   │
└───────────────────────────────────────────────┘
           │
           │ (16 kHz PCM Chunks via /ws/transcription/)
           ▼
┌───────────────────────────────────────────────┐
│  Vosk STT Engine (backend/apps/transcription) │
│  • Offline Kaldi recognizer per connection    │
│  • Word-level start / end timestamps (s)      │
└───────────────────────────────────────────────┘
           │
           │ (Transcripts & Word Timestamps)
           ▼
┌───────────────────────────────────────────────┐
│  Stream Moderation Service                    │
│  • Matches against profanity_wordlist.txt     │
│  • Evaluates flagged word timing segments     │
└───────────────────────────────────────────────┘
           │
           │ (Moderation Decisions & Censored Segments)
           ▼
┌───────────────────────────────────────────────┐
│  Delay Buffer Playout & Censorship            │
│  • Silences profane words with ±60ms padding  │
│  • Applies zero-gain attenuation (gain = 0.0) │
│  • Clean speech & background audio pass (1.0) │
└───────────────────────────────────────────────┘
           │
           ▼
[ Outgoing WebRTC Stream (Viewer Audio Track) ]
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
│   │   ├── stream_moderation/       # Live audio transcript moderation & interval tracking
│   │   ├── streams/                 # Livestreaming consumer & WebRTC signaling
│   │   └── transcription/           # Vosk speech recognition engine & WebSocket consumer
│   ├── models/                      # Vosk speech recognition model directory (gitignored)
│   ├── scripts/                     # download_vosk_model.py utility
│   ├── wordlists/                   # profanity_wordlist.txt
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   ├── public/                      # audio-processor.js (AudioWorklet delay buffer)
│   ├── src/
│   │   ├── components/              # Navbar, ProtectedRoute, LoadingSpinner
│   │   ├── context/                 # AuthContext (state & tokens)
│   │   ├── pages/                   # GlobalChat, Profile, GoLive, Watch, Login, Register
│   │   └── services/                # Axios API client, streamService, WebSocket handlers
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
- **Profile UI:** User profile page with avatar preview and trust score display.
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

<details open>
<summary><b>Stage 4 — Live Audio Moderation & Pre-Broadcast Censorship</b></summary>
<br>

- **Speech-to-Text Transcription (Vosk):** Real-time, fully offline, privacy-preserving speech recognition running per connection using Kaldi recognizers configured with word-level start/end timestamps enabled (`SetWords(True)`).
- **Dedicated Transcription WebSocket:** Authenticated ASGI WebSocket endpoint at `/ws/transcription/` accepting binary 16 kHz 16-bit mono PCM chunks and emitting finalized/partial transcript events with timestamps.
- **Profanity Detection:** Dedicated `StreamModerationService` matching recognized words against `backend/wordlists/profanity_wordlist.txt` with timing validation and fallback partial moderation.
- **Pre-Broadcast Delay Buffer:** Host microphone audio is retained in a 1.5-second circular ring buffer in a dedicated `AudioWorkletProcessor` (`frontend/public/audio-processor.js`) running on the Web Audio rendering thread.
- **Silence-Censorship:** Detected profanity is silenced by applying zero-gain attenuation ($0.0$) with $60\text{ms}$ acoustic padding around word boundaries without interrupting video playback or introducing abrasive beep sounds. Clean speech and background audio proceed normally.
- **Timeline Synchronization:** Automatic timeline offset calibration (`voskStreamOffset`) synchronizes Vosk recognition intervals with the circular audio buffer playout index regardless of WebSocket connection latency.
</details>

<details open>
<summary><b>Stage 5 — Layer 3 Contextual Moderation & Policy Engine</b></summary>
<br>

- **Context-Aware Classification:** Bounded conversational context window (`CONTEXT_WINDOW_SIZE`, default 5 messages) passed to Layer 3 for evaluating subtle and indirect hostility without loading full history.
- **HuggingFace Inference Provider:** Native async integration via `HuggingFaceProvider` using official Inference API endpoints (default: `unitary/toxic-bert`) with bounded input length, configurable timeouts (`HF_API_TIMEOUT`), and rate-limit/outage guards.
- **Structured Output Contract:** Validated `ContextualResult` tracking clamped scores (`toxicity_score`, `harassment_score`, `threat_score`, `insult_score`, `confidence`), `intent_label`, `target_type`, and `sarcasm_detected`.
- **Defense-in-Depth Validation:** All model outputs clamped to $[0.0, 1.0]$, controlled-vocabulary validation for labels, NaN sentinel representation, and protection against prompt injection by isolating context as raw data.
- **Decoupled Moderation Policy Engine:** Evaluates scores independently of provider:
  - **ALLOW:** Clean content, harmless sarcasm, friendly banter, and ordinary disagreement.
  - **REVIEW (`flagged`):** Scores within configurable amber zone (`POLICY_REVIEW_THRESHOLD`, default 0.60).
  - **BLOCK (`blocked`):** Severe violations exceeding policy thresholds (`POLICY_THREAT_BLOCK` = 0.80, `POLICY_TOXICITY_BLOCK` = 0.85, `POLICY_HARASSMENT_BLOCK` = 0.80).
- **Sarcasm Safety Invariant:** Sarcasm alone never triggers an automatic block; harmful statements are evaluated by their explicit harm score regardless of ironic presentation.
- **Fail-Safe & Tokenless Operation:** Graceful fallback to `allow` on provider timeouts, 429 rate limits, 401 auth errors, or outages; completely operational locally with `MODERATION_PROVIDER=null` or `mock` without an API key.
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
| `POST` | `/api/stream-moderation/moderate/` | Yes | Evaluate transcript text and word timestamps for profanity |

### WebSocket Endpoints

| Protocol | Endpoint | Handshake | Purpose |
|---|---|---|---|
| `ws://` / `wss://` | `/ws/chat/` | `auth_required` $\rightarrow$ `authenticate` | Real-time chat & moderation streaming |
| `ws://` / `wss://` | `/ws/streams/<stream_id>/` | Query token authentication | WebRTC peer signaling for livestreams |
| `ws://` / `wss://` | `/ws/transcription/` | `auth_required` $\rightarrow$ `authenticate` | Live PCM audio ingestion & STT moderation streaming |

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

# Download Vosk speech recognition model (~40 MB)
python scripts/download_vosk_model.py

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

### 3. Environment Configuration

The backend supports configuration via `backend/.env`. Key settings include:

| Variable | Default | Description |
|---|---|---|
| `PROFANITY_WORDLIST_PATH` | `wordlists/profanity_wordlist.txt` | Path to the profanity wordlist file used for live audio filtering |
| `VOSK_MODEL_PATH` | `models/vosk-model-small-en-us-0.15` | Path to the unpacked Vosk speech recognition model directory |
| `BLOOM_BACKEND` | `local` | Chat Bloom filter backend (`local` or `redis`) |
| `BLOOM_CAPACITY` | `50000` | Expected number of items in the Bloom filter |
| `BLOOM_ERROR_RATE` | `0.001` | Desired false positive probability ($p=0.1\%$) |
| `BLOOM_MIN_TRUST` | `80` | Minimum sender trust score required for Bloom fast-path eligibility |
| `MODERATION_PROVIDER` | `null` | AI moderation provider (`null`, `mock`, `huggingface`) |
| `HF_API_TOKEN` | `""` | Hugging Face User Access Token (read-only; optional in dev) |
| `HF_MODEL_ID` | `unitary/toxic-bert` | Hugging Face model identifier for classification |
| `HF_API_TIMEOUT` | `5` | Request timeout in seconds for Hugging Face inference |
| `HF_MAX_INPUT_LENGTH` | `512` | Max character length for inputs sent to the provider |
| `CONTEXT_WINDOW_SIZE` | `5` | Bounded number of preceding messages for contextual evaluation |
| `POLICY_TOXICITY_BLOCK` | `0.85` | Toxicity score threshold for instant block |
| `POLICY_THREAT_BLOCK` | `0.80` | Threat score threshold for instant block |
| `POLICY_HARASSMENT_BLOCK`| `0.80` | Harassment score threshold for instant block |
| `POLICY_REVIEW_THRESHOLD` | `0.60` | Score threshold for flagging content into `review` status |

### 4. Layer 3 Contextual Moderation Configuration

#### Running Without an API Key (Default Dev Mode)
No external API token is required to run the development environment. When `MODERATION_PROVIDER=null` (the default), clean messages bypass to fast-path and uncertain messages pass through without hitting external APIs. In test environments, `MODERATION_PROVIDER=mock` provides deterministic simulation.

#### Configuring Hugging Face Inference
1. Create a free Hugging Face account at [huggingface.co](https://huggingface.co).
2. Generate a **Read** token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
3. Set the following in `backend/.env`:
   ```bash
   MODERATION_PROVIDER=huggingface
   HF_API_TOKEN=hf_yourTokenHere
   HF_MODEL_ID=unitary/toxic-bert
   ```
4. **Model Capabilities & Selection:**
   - Default model: `unitary/toxic-bert` (multi-label toxicity classification including `toxic`, `severe_toxic`, `obscene`, `threat`, `insult`, `identity_hate`).
   - The provider automatically handles cold starts (HTTP 503), rate limits (HTTP 429), and authorization errors (HTTP 401) with fail-safe fallback to allow, ensuring WebSocket chat responsiveness is never blocked indefinitely.

#### Context Window & Bloom Fast-Path Interaction
- Clean messages from trusted users (`trust_score >= 80`, no URLs, mostly ASCII, within length cap) continue to be fast-pathed through Layer 2 Bloom filtering in sub-milliseconds without triggering provider calls.
- Only uncertain messages or messages failing fast-path eligibility reach Layer 3.
- When Layer 3 is reached, a bounded context window (`CONTEXT_WINDOW_SIZE`, default 5 messages) is provided to disambiguate subtle hostility, banter, sarcasm, or personal attacks without loading full conversation histories.

#### Moderation Policy Engine Decisions
- **ALLOW:** No violation detected; includes friendly banter, harmless sarcasm, and ordinary disagreement.
- **REVIEW (`flagged`):** Borderline or ambiguous scores between `POLICY_REVIEW_THRESHOLD` (0.60) and block thresholds.
- **BLOCK (`blocked`):** Explicit violations exceeding policy thresholds (`threat >= 0.80`, `toxicity >= 0.85`, `harassment >= 0.80`, `insult >= 0.80`).
- **Sarcasm Safety Invariant:** Sarcasm detection alone **never** triggers an automatic block. Harmful statements are evaluated on their explicit harm score regardless of sarcastic presentation.

#### Privacy & Security
- Context and incoming messages are treated as **untrusted user content** and passed strictly as classification inputs, preventing prompt injection attacks.
- Tokens and secrets are read exclusively from backend environment variables and are never logged, stored in databases, or exposed to browser code (`VITE_API_BASE_URL` remains isolated).

### 5. Running Live Stream Audio Moderation

1. Start both the backend (Daphne/ASGI server on port `8000`) and frontend (Vite on port `5173`).
2. Log in or register an account at `http://localhost:5173/`.
3. Navigate to **Go Live** (`/streams/go-live`), enter a stream title, and click **Start stream**. Grant browser camera and microphone permissions when prompted.
4. The host client initializes the `AudioWorkletProcessor` (`audio-processor.js`), connects to `/ws/transcription/`, and streams 16 kHz mono PCM chunks while holding audio in the 1.5-second circular delay buffer.
5. In another tab or browser profile, log in and navigate to `/streams` to view the stream (`/watch/:id`).
6. When speech contains profanity present in `backend/wordlists/profanity_wordlist.txt`, the Vosk transcript timestamps identify the offending interval. The delay buffer zeroes the audio gain ($0.0$) with $\pm 60\text{ms}$ acoustic padding before playout, ensuring viewers hear complete silence during profane words while clean speech and background audio pass through seamlessly.

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

Run stream moderation and live audio transcription tests:

```bash
python manage.py test apps.stream_moderation apps.transcription
```

Run the automated Bloom performance benchmark:

```bash
python manage.py benchmark_bloom --save-report ../docs/BENCHMARK_REPORT.md
```
