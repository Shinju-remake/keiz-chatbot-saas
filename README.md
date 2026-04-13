# Shinju AI - Omni-Engine V3

A production-ready multitenant Chatbot SaaS platform with keyword-based FAQ and OpenAI **GPT-5.4 Nano** intelligence.

## 🚀 Features
- **Shinju AI Universal Console:** Unified command center for multi-portal management.
- **Hybrid Logic:** Keyword matching (zero-cost) with OpenAI fallback (high-intelligence).
- **Multitenancy:** Each company has its own API key and isolated conversation logs.
- **Clean URLs:** Access `/dashboard`, `/agency`, `/demo`, and `/test` with professional routing.
- **Embeddable Widget:** A sleek, neon-purple chat widget with **EN/FR/ES** language support.
- **Pro-Tier Automation:** Make.com Webhook bridge for lead tracking and human escalation.
- **Mobile/iOS Ready:** Fully optimized for all modern mobile and desktop browsers.

## 🛠️ Tech Stack
- **Backend:** FastAPI, SQLModel (SQLite/PostgreSQL compatible).
- **AI:** OpenAI GPT-5.4 Nano (Cost-optimized 2026 pricing).
- **Frontend:** Vanilla JS / CSS3 (No framework for the widget).
- **Deployment:** Render (Live at keiz-chatbot-saas-1.onrender.com).

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
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Access the Platform
- **Landing Page:** `http://localhost:8000/`
- **Agency Page:** `http://localhost:8000/agency`
- **Admin Dashboard:** `http://localhost:8000/dashboard`
- **Demo Widget:** `http://localhost:8000/demo`

## 🧪 Testing
```bash
cd backend
venv/bin/pytest test_main.py
```

## 🔒 Security
- All requests require a valid `X-API-Key` header.
- CORS is pre-configured for global embedding.
- Rate limits are set to 5 requests per minute by default.
- WhatsApp Webhook secured with `c2f05b5f` verify token.
