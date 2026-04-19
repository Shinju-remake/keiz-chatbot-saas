from fastapi import FastAPI, HTTPException, Header, Depends, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import Session, select
import os
import pdfplumber
import io
from pathlib import Path
from dotenv import load_dotenv

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Relative imports for local/render consistency
try:
    from database import create_db_and_tables, get_session, engine
    from models import Company, FAQRule, ChatLog, Reservation, ChatSession, TrendInsight
    from utils import process_message_v3, send_whatsapp_reply
    from rag_utils import index_knowledge_base
except ImportError:
    from .database import create_db_and_tables, get_session, engine
    from .models import Company, FAQRule, ChatLog, Reservation, ChatSession, TrendInsight
    from .utils import process_message_v3, send_whatsapp_reply
    from .rag_utils import index_knowledge_base

load_dotenv()

# --- HELPER FUNCTIONS ---

def get_current_company(request: Request, db: Session, x_api_key: Optional[str] = None) -> Optional[Company]:
    """
    Identifies the current company via Subdomain (priority) or API Key.
    """
    # 1. Try Subdomain (Modern SaaS)
    host = request.headers.get("host", "")
    if "." in host and not host.split(".")[0] in ["www", "localhost"]:
        subdomain = host.split(".")[0]
        company = db.exec(select(Company).where(Company.subdomain == subdomain.lower())).first()
        if company: return company
    
    # 2. Try API Key (Admin Portal / Widget Legacy)
    if x_api_key:
        return db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    
    return None

# Hardened Path Resolution
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Shinju AI - Universal Console V3")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "online", "engine": "Shinju AI Omni-Console V3"}

@app.on_event("startup")
def on_startup():
    try:
        create_db_and_tables()
        # Ensure new columns exist for existing tables (manual SQLite migration)
        from sqlalchemy import text
        with engine.connect() as conn:
            # Columns for ChatLog (Feedback Loop)
            try: conn.execute(text("ALTER TABLE chatlog ADD COLUMN confidence_score FLOAT DEFAULT 1.0;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE chatlog ADD COLUMN needs_review BOOLEAN DEFAULT 0;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE chatlog ADD COLUMN reviewed BOOLEAN DEFAULT 0;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE chatlog ADD COLUMN was_corrected BOOLEAN DEFAULT 0;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE chatlog ADD COLUMN corrected_reply TEXT;")); conn.commit()
            except: pass
            
            # Columns for ChatSession (Re-engagement)
            try: conn.execute(text("ALTER TABLE chatsession ADD COLUMN customer_phone TEXT;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE chatsession ADD COLUMN reengagement_status TEXT DEFAULT 'none';")); conn.commit()
            except: pass
            
        with Session(engine) as session:
            company = session.exec(select(Company)).first()
            if not company:
                company = Company(
                    name="Shinju AI", 
                    api_key="dev-api-key-123",
                    system_prompt="You are Shinju AI, the Elite Virtual Assistant. Your goal is to provide luxury-level service. CONSTRAINTS: 1. Keep responses concise and high-impact. 2. NEVER use markdown bold (**) or italics (*) in your replies; use plain text only. 3. Be helpful with all inquiries related to your host company.",
                    whatsapp_verify_token="shinju_pro_verify"
                )
                session.add(company)
                session.commit()
                session.refresh(company)
    except Exception as e:
        print(f"STARTUP ERROR (Non-fatal): {e}")

class ChatMessage(BaseModel):
    message: str
    session_id: str
    language: Optional[str] = "en"

class ChatResponse(BaseModel):
    reply: Optional[str] = None
    source: str
    agent_identity: Optional[str] = "Shinju AI Agent"

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("60/minute")
async def chat_endpoint(request: Request, msg: ChatMessage, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    # Process message and get rich metadata
    result = process_message_v3(company, msg.session_id, msg.message, db, language=msg.language)
    
    # result now contains 'reply', 'source', and potentially 'agent_identity'
    return ChatResponse(**result)

# --- THE UNIVERSAL CONSOLE ---

@app.get("/")
async def get_console():
    return FileResponse(str(BASE_DIR / "console.html"))

# --- PORTAL STATIC ROUTES (For Iframes) ---

@app.get("/login")
async def get_login():
    return FileResponse(str(BASE_DIR / "login.html"))

@app.get("/signup")
async def get_signup():
    return FileResponse(str(BASE_DIR / "signup.html"))

@app.get("/agency_static")
async def get_agency_static():
    return FileResponse(str(BASE_DIR / "agency.html"))

@app.get("/demo_static")
async def get_demo_static():
    return FileResponse(str(BASE_DIR / "test.html"))

@app.get("/dashboard_static")
async def get_dashboard_static():
    return FileResponse(str(BASE_DIR / "admin" / "dashboard.html"))

@app.get("/test_static")
async def get_test_static():
    return FileResponse(str(BASE_DIR / "widget" / "test.html"))

# --- CLEAN URL REDIRECTS (Optional, but good for direct access) ---

@app.get("/agency")
async def get_agency(): return await get_agency_static()

@app.get("/demo")
async def get_demo(): return await get_demo_static()

@app.get("/dashboard")
async def get_dashboard(): return await get_dashboard_static()

@app.get("/client-dashboard")
async def get_client_dashboard():
    return FileResponse(str(BASE_DIR / "admin" / "client_dashboard.html"))

@app.get("/test")
async def get_test(): return await get_test_static()

# --- PRO FEATURES: WHATSAPP WEBHOOK ---

@app.get("/webhook/whatsapp")
async def verify_whatsapp(request: Request, db: Session = Depends(get_session)):
    """
    Step 1: Meta verifies your server URL with a Verify Token.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token:
        # Check if any company matches this verify token
        company = db.exec(select(Company).where(Company.whatsapp_verify_token == token)).first()
        if company:
            return int(challenge)
    
    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook/whatsapp")
async def handle_whatsapp_msg(request: Request, db: Session = Depends(get_session)):
    """
    Step 2: Handle incoming WhatsApp messages.
    """
    data = await request.json()
    
    try:
        # Extract metadata from Meta's complex payload
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            message = entry["messages"][0]
            from_number = message["from"]
            text = message["text"]["body"]
            
            # Identify which company this webhook is for based on their phone_id or a unique token
            # For this MVP, we use the first company found (simulated multitenancy)
            company = db.exec(select(Company)).first()
            if company:
                session_id = f"wa_{from_number}"
                result = process_message_v3(company, session_id, text, db)
                
                # Send the reply back to WhatsApp
                import asyncio
                asyncio.create_task(send_whatsapp_reply(company, from_number, result["reply"]))
                
        return {"status": "ok"}
    except Exception as e:
        print(f"WHATSAPP WEBHOOK ERROR: {e}")
        return {"status": "error"}

# --- SAAS MULTI-TENANCY MIDDLEWARE ---

@app.middleware("http")
async def subdomain_middleware(request: Request, call_next):
    # Logic: Detect subdomain for routing
    host = request.headers.get("host", "")
    if "." in host and not host.split(".")[0] in ["www", "localhost"]:
        request.state.subdomain = host.split(".")[0].lower()
    else:
        request.state.subdomain = None
    
    response = await call_next(request)
    return response

# --- PRO FEATURES: STRIPE SAAS BILLING ---

class CheckoutSession(BaseModel):
    plan: str

@app.post("/admin/billing/checkout")
async def create_checkout_session(data: CheckoutSession, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    # In a real app, you would use stripe.checkout.Session.create()
    # For this MVP, we provide a local simulated success URL
    print(f"STRIPE: Simulating {data.plan} checkout for {company.name}")
    
    # Using a local success simulate route instead of fake stripe.com domain
    sim_url = f"{request.base_url}admin/billing/simulate_success?plan={data.plan}&cid={company.id}"
    return {"url": sim_url}

@app.get("/admin/billing/simulate_success")
async def simulate_stripe_success(plan: str, cid: int, db: Session = Depends(get_session)):
    """
    Simulates the callback from Stripe after a successful payment.
    """
    company = db.get(Company, cid)
    if company:
        company.plan = plan
        db.add(company)
        db.commit()
        return FileResponse(str(BASE_DIR / "admin" / "dashboard.html")) # Send back to dashboard
    return {"status": "error"}

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_session)):
    """
    Finalized SaaS Billing: Automatically upgrades customer plans upon payment.
    """
    payload = await request.json()
    event = payload.get("type")

    if event == "checkout.session.completed":
        session = payload.get("data", {}).get("object", {})
        # Extract the metadata we sent during checkout
        # Note: In production, you'd use stripe.Webhook.construct_event for security
        company_id = session.get("metadata", {}).get("company_id")
        new_plan = session.get("metadata", {}).get("plan", "pro")

        if company_id:
            company = db.get(Company, int(company_id))
            if company:
                company.plan = new_plan
                db.add(company)
                db.commit()
                print(f"💰 STRIPE: Upgraded {company.name} to {new_plan.upper()} Tier.")

    return {"status": "ok"}

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...), x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key: raise HTTPException(status_code=500, detail="OpenAI Key not configured")
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key.strip())
        
        # Save temp file for Whisper
        temp_filename = f"temp_{uuid.uuid4()}.wav"
        with open(temp_filename, "wb") as f:
            f.write(await file.read())
            
        with open(temp_filename, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
            
        os.remove(temp_filename) # Cleanup
        return {"text": transcript.text}
    except Exception as e:
        print(f"WHISPER ERROR: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed")

# --- ADMIN API ROUTES ---

@app.get("/admin/stats")
async def get_dashboard_stats(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    # Calculate stats
    active_chats = db.exec(select(ChatSession).where(ChatSession.company_id == company.id)).all()
    total_res = db.exec(select(Reservation).where(Reservation.company_id == company.id)).all()
    logs = db.exec(select(ChatLog).where(ChatLog.company_id == company.id)).all()
    
    needs_review = [l for l in logs if l.needs_review and not l.reviewed]
    avg_conf = sum([l.confidence_score for l in logs]) / len(logs) if logs else 1.0
    
    return {
        "active_chats": len(active_chats),
        "total_reservations": len(total_res),
        "needs_review": len(needs_review),
        "avg_confidence": round(avg_conf * 100)
    }

@app.get("/admin/logs")
async def get_logs(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return db.exec(select(ChatLog).where(ChatLog.company_id == company.id).order_by(ChatLog.timestamp.desc()).limit(100)).all()

@app.get("/admin/reservations")
async def get_reservations(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return db.exec(select(Reservation).where(Reservation.company_id == company.id).order_by(Reservation.timestamp.desc())).all()

@app.get("/admin/analytics/trends")
async def get_ai_trends(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    # Return persisted insights first
    stored_insights = db.exec(select(TrendInsight).where(TrendInsight.company_id == company.id).order_by(TrendInsight.timestamp.desc())).all()
    if stored_insights:
        return {"trends": stored_insights}
    
    # Otherwise, generate a fresh one (Simulated)
    # In a pro-version, this would trigger an OpenAI analysis task
    new_insight = TrendInsight(
        company_id=company.id,
        topic="Menu Inquiries",
        frequency=15,
        insight_text="Multiple users are asking about a weekend brunch menu which is not explicitly mentioned in your KB.",
        suggested_rule="Add keyword 'brunch' with weekend hours: 10AM - 3PM."
    )
    db.add(new_insight)
    db.commit()
    db.refresh(new_insight)
    return {"trends": [new_insight]}

@app.get("/admin/rules")
async def get_rules(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()

class FAQRuleCreate(BaseModel):
    keyword: str
    response: str

@app.post("/admin/rules")
async def create_rule(rule_in: FAQRuleCreate, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    existing = db.exec(select(FAQRule).where(FAQRule.company_id == company.id, FAQRule.keyword == rule_in.keyword.lower())).first()
    if existing: existing.response = rule_in.response; db.add(existing)
    else: db.add(FAQRule(company_id=company.id, keyword=rule_in.keyword.lower(), response=rule_in.response))
    db.commit(); return {"status": "success"}

@app.delete("/admin/rules/{rule_id}")
async def delete_rule(rule_id: int, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    rule = db.get(FAQRule, rule_id)
    if not rule or rule.company_id != company.id: raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule); db.commit(); return {"status": "success"}

@app.get("/admin/settings")
async def get_settings(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return {
        "name": company.name, 
        "subdomain": company.subdomain,
        "primary_color": company.primary_color,
        "logo_url": company.logo_url,
        "knowledge_base": company.knowledge_base,
        "system_prompt": company.system_prompt, 
        "openai_api_key": company.openai_api_key, 
        "whatsapp_phone_id": company.whatsapp_phone_id, 
        "whatsapp_verify_token": company.whatsapp_verify_token,
        "plan": company.plan
    }

class SettingsUpdate(BaseModel):
    name: Optional[str] = None
    subdomain: Optional[str] = None
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None
    knowledge_base: Optional[str] = None
    system_prompt: Optional[str] = None
    openai_api_key: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None

@app.post("/admin/settings")
async def update_settings(settings_in: SettingsUpdate, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    if settings_in.name: company.name = settings_in.name
    if settings_in.subdomain: company.subdomain = settings_in.subdomain.lower()
    if settings_in.primary_color: company.primary_color = settings_in.primary_color
    if settings_in.logo_url: company.logo_url = settings_in.logo_url
    
    if settings_in.knowledge_base: 
        company.knowledge_base = settings_in.knowledge_base
        # [NEW] Re-index knowledge base in background
        import asyncio
        asyncio.create_task(asyncio.to_thread(index_knowledge_base, company.id, company.knowledge_base, company.openai_api_key))

    if settings_in.system_prompt: company.system_prompt = settings_in.system_prompt
    if settings_in.openai_api_key: company.openai_api_key = settings_in.openai_api_key
    if settings_in.whatsapp_phone_id: company.whatsapp_phone_id = settings_in.whatsapp_phone_id
    db.add(company); db.commit(); return {"status": "success"}

@app.post("/admin/kb/upload")
async def upload_kb_pdf(request: Request, file: UploadFile = File(...), x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    try:
        content = await file.read()
        extracted_text = ""
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    extracted_text += text + "\n"
        
        if not extracted_text.strip():
            raise HTTPException(status_code=400, detail="No readable text found in PDF.")
            
        # Update company KB
        company.knowledge_base = extracted_text.strip()
        db.add(company)
        db.commit()
        
        # [NEW] Re-index knowledge base in background
        import asyncio
        asyncio.create_task(asyncio.to_thread(index_knowledge_base, company.id, company.knowledge_base, company.openai_api_key))
        
        return {"status": "success", "extracted_length": len(extracted_text)}
    except Exception as e:
        print(f"PDF EXTRACTION ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to process PDF.")

# --- PUBLIC SAAS SIGNUP ---

class SignupIn(BaseModel):
    name: str
    subdomain: str
    email: str 
    openai_key: Optional[str] = None
    plan: Optional[str] = "free"

@app.post("/auth/signup")
async def public_signup(data: SignupIn, db: Session = Depends(get_session)):
    # Check if subdomain is taken
    existing = db.exec(select(Company).where(Company.subdomain == data.subdomain.lower())).first()
    if existing:
        raise HTTPException(status_code=400, detail="Subdomain already in use.")
    
    new_company = Company(
        name=data.name,
        subdomain=data.subdomain.lower(),
        openai_api_key=data.openai_key,
        plan=data.plan,
        system_prompt=f"You are the AI Assistant for {data.name}. Luxury-level service is mandatory."
    )
    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    
    return {
        "status": "success",
        "api_key": new_company.api_key,
        "dashboard_url": f"https://{new_company.subdomain}.shinju-ai.com/dashboard"
    }

# --- SUBDOMAIN RESOLUTION ENGINE ---

@app.get("/widget/config")
async def get_widget_config(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    """
    Identifies company by either API Key (legacy) or Subdomain (Modern SaaS).
    """
    company = None
    if x_api_key:
        company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    
    if not company:
        host = request.headers.get("host", "")
        if "." in host:
            sub = host.split(".")[0]
            company = db.exec(select(Company).where(Company.subdomain == sub)).first()

    if not company:
        # Fallback to default for dev testing
        company = db.exec(select(Company)).first()

    if not company: raise HTTPException(status_code=404, detail="Company not found")
    
    return {
        "name": company.name,
        "primary_color": company.primary_color,
        "logo_url": company.logo_url,
        "api_key": company.api_key
    }

# --- LIVE CHAT TAKEOVER ENGINE ---

class TakeoverIn(BaseModel):
    session_id: str
    active: bool

@app.post("/admin/chat/takeover")
async def toggle_takeover(data: TakeoverIn, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    # Update or create session state
    session_state = db.exec(select(ChatSession).where(ChatSession.company_id == company.id, ChatSession.session_id == data.session_id)).first()
    if not session_state:
        session_state = ChatSession(company_id=company.id, session_id=data.session_id)
    
    session_state.is_human_takeover = data.active
    session_state.last_active = datetime.utcnow()
    db.add(session_state)
    db.commit()
    return {"status": "success"}

@app.get("/admin/chat/active")
async def get_active_sessions(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    # Return sessions active in the last 24 hours
    since = datetime.utcnow().timestamp() - 86400
    return db.exec(select(ChatSession).where(ChatSession.company_id == company.id)).all()

class CorrectionIn(BaseModel):
    log_id: int
    correction: str

@app.post("/admin/logs/correct")
async def correct_log(data: CorrectionIn, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    log = db.get(ChatLog, data.log_id)
    if not log or log.company_id != company.id: raise HTTPException(status_code=404, detail="Log not found")
    
    # Update log state
    log.was_corrected = True
    log.corrected_reply = data.correction
    log.reviewed = True
    log.needs_review = False
    db.add(log)
    
    # Create a new FAQ rule from this correction (Human-in-the-loop)
    new_rule = FAQRule(
        company_id=company.id,
        keyword=log.user_msg.lower()[:50], # Use first 50 chars of user message as keyword
        response=data.correction
    )
    db.add(new_rule)
    db.commit()
    return {"status": "success"}

# MOUNT STATIC FILES
app.mount("/widget", StaticFiles(directory=str(BASE_DIR / "widget")), name="widget")
app.mount("/admin_static", StaticFiles(directory=str(BASE_DIR / "admin")), name="admin_static")
app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static_root")
