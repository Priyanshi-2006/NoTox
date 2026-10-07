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

### Stage 3 — Real-Time Global Chat
Global Chat Backend: Added a dedicated chat Django application for real-time communication using Django Channels and Daphne.
WebSocket Configuration: Configured ASGI-based WebSocket routing with the global chat endpoint:
ws://localhost:8000/ws/chat/
JWT WebSocket Authentication: WebSocket clients authenticate using the existing JWT access token. Only authenticated and active users can join the global chat.
User Restrictions: Restricted users are prevented from connecting to the global chat.
Real-Time Message Broadcasting: Implemented GlobalChatConsumer to receive and broadcast messages to all currently connected authenticated users.
Message Validation: Added message length validation with a maximum message size of 2000 characters.
Frontend Global Chat: Added a dedicated GlobalChat React page with WebSocket communication and connection/authentication status handling.
Chat Message UI: Messages sent by the current user are displayed on the right, while messages received from other users are displayed on the left.
Sender Information: Chat messages include the sender's username and display name.
Current Limitation: Chat messages are currently real-time only and are not persisted in the database.
Development Channel Layer: The current implementation uses Django Channels' InMemoryChannelLayer, which is suitable for local development and single-process use. Production-ready channel infrastructure will be implemented in a later stage.

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

## WebSocket Endpoint
| Protocol | Endpoint | Auth Required | Description |
| ---|---|---|---|
| WebSocket | ws://localhost:8000/ws/chat/ | JWT Access Token |Real-time global chat communication |

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

# Configure PostgreSQL connection in .env, then migrate:
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
python manage.py test apps.accounts
```

