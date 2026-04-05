# Keiz Chatbot SaaS - Omni-Engine V3

A production-ready multitenant Chatbot SaaS platform with keyword-based FAQ and OpenAI fallback.

## 🚀 Features
- **Multitenancy:** Each company has its own API key and isolated conversation logs.
- **Hybrid Logic:** Keyword matching (zero-cost) with OpenAI fallback (high-intelligence).
- **Admin Dashboard:** Real-time log monitoring.
- **Embeddable Widget:** A sleek, neon-purple chat widget for any website.
- **Rate Limiting:** Built-in protection against API abuse.

## 🛠️ Tech Stack
- **Backend:** FastAPI, SQLModel (SQLite/PostgreSQL compatible).
- **AI:** OpenAI GPT-3.5 API.
- **Frontend:** Vanilla JS/CSS (No heavy frameworks for the widget).

## 📦 Getting Started

### 1. Backend Setup
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration
Edit `backend/.env` with your `OPENAI_API_KEY`.

### 3. Run the Server
```bash
uvicorn main:app --reload
```

### 4. Access the Platform
- **Landing Page:** `http://localhost:8000/`
- **Admin Dashboard:** `http://localhost:8000/admin/dashboard.html`
- **Demo Widget:** `http://localhost:8000/widget/test.html` (You may need to create this or use the embed code)

## 🧪 Testing
```bash
cd backend
venv/bin/pytest test_main.py
```

## 🔒 Security
- All requests require a valid `X-API-Key` header.
- CORS is pre-configured for global embedding.
- Rate limits are set to 5 requests per minute by default.
