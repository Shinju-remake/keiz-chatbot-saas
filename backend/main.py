from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import Session, select
import os
from pathlib import Path
from dotenv import load_dotenv

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Relative imports for local/render consistency
try:
    from database import create_db_and_tables, get_session, engine
    from models import Company, FAQRule, ChatLog, Reservation
    from utils import process_message_v3, send_whatsapp_reply
except ImportError:
    from .database import create_db_and_tables, get_session, engine
    from .models import Company, FAQRule, ChatLog, Reservation
    from .utils import process_message_v3, send_whatsapp_reply

load_dotenv()

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

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
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
            
        # Ensure all rules exist
        target_rules = {
            "price": "Our luxury dining experience ranges from 50€ to 150€. Quality is our priority.",
            "contact": "Contact Shinju at contact@shinju-ai.com or visit our dashboard.",
            "book": "To book a table at Shinju Bistro, please provide your name and number of guests.",
            "reserve": "I can assist with reservations at Shinju Bistro! Please provide the date, time, and party size.",
            "reservation": "For reservations, tell me the date, time, and how many guests will be joining us.",
            "menu": "Explore our menu at shinju-bistro.com/menu",
            "vibe": "The atmosphere at Shinju is one of refined elegance, perfect for discerning guests.",
            "hello": "Hello! I am Shinju AI. How can I serve you today?",
            "hi": "Greetings. I am Shinju AI, your dedicated assistant. How may I help?",
            "recommend": "I highly recommend our signature Omakase experience.",
            "hey": "Welcome back. I am Shinju AI. What can I do for you?"
        }
        
        existing_keywords = session.exec(select(FAQRule.keyword).where(FAQRule.company_id == company.id)).all()
        for kw, resp in target_rules.items():
            if kw not in existing_keywords:
                session.add(FAQRule(company_id=company.id, keyword=kw, response=resp))
        
        # Sample Reservation for Demo
        existing_res = session.exec(select(Reservation).where(Reservation.company_id == company.id)).first()
        if not existing_res:
            session.add(Reservation(
                company_id=company.id,
                customer_name="Keizinho Test",
                date_time="Tonight at 8:30 PM",
                pax=2,
                status="confirmed"
            ))

        session.commit()

class ChatMessage(BaseModel):
    message: str
    session_id: str
    language: Optional[str] = "en"

class ChatResponse(BaseModel):
    reply: str
    source: str

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("60/minute")
async def chat_endpoint(request: Request, msg: ChatMessage, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    result = process_message_v3(company, msg.session_id, msg.message, db, language=msg.language)
    return ChatResponse(**result)

# --- THE UNIVERSAL CONSOLE ---

@app.get("/")
async def get_console():
    return FileResponse(str(BASE_DIR / "console.html"))

# --- PORTAL STATIC ROUTES (For Iframes) ---

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
    # Logic: If host is 'bistro.shinju-ai.com', set company context
    host = request.headers.get("host", "")
    if "." in host and not host.startswith("www"):
        subdomain = host.split(".")[0]
        # We can store this in request.state for use in endpoints
        request.state.subdomain = subdomain
    else:
        request.state.subdomain = None
    
    response = await call_next(request)
    return response

# --- PRO FEATURES: STRIPE SAAS BILLING ---

class CheckoutSession(BaseModel):
    plan: str

@app.post("/admin/billing/checkout")
async def create_checkout_session(data: CheckoutSession, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    
    # In a real app, you would use stripe.checkout.Session.create()
    # For this MVP, we simulate the redirection URL
    print(f"STRIPE: Creating {data.plan} session for {company.name}")
    
    # Placeholder for the actual Stripe URL
    stripe_url = f"https://checkout.stripe.com/pay/c_test_shinju_{data.plan}_{company.id}"
    return {"url": stripe_url}

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_session)):
    """
    Handle successful payments to upgrade company plans.
    """
    # Verify Stripe signature and update company.plan
    return {"status": "ok"}

# --- ADMIN API ROUTES ---

@app.get("/admin/logs")
async def get_logs(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    return db.exec(select(ChatLog).where(ChatLog.company_id == company.id).order_by(ChatLog.timestamp.desc()).limit(100)).all()

@app.get("/admin/reservations")
async def get_reservations(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    return db.exec(select(Reservation).where(Reservation.company_id == company.id).order_by(Reservation.timestamp.desc())).all()

@app.get("/admin/stats")
async def get_stats(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    
    total_chats = db.exec(select(ChatLog).where(ChatLog.company_id == company.id)).all()
    reservations = db.exec(select(Reservation).where(Reservation.company_id == company.id)).all()
    
    ai_count = len([l for l in total_chats if l.source == 'ai'])
    kw_count = len([l for l in total_chats if l.source == 'keyword'])
    
    return {
        "total_messages": len(total_chats),
        "reservations_count": len(reservations),
        "ai_usage": ai_count,
        "keyword_usage": kw_count,
        "success_rate": "99.9%" # Strategic marketing placeholder
    }

@app.get("/admin/rules")
async def get_rules(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    return db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()

class FAQRuleCreate(BaseModel):
    keyword: str
    response: str

@app.post("/admin/rules")
async def create_rule(rule_in: FAQRuleCreate, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    existing = db.exec(select(FAQRule).where(FAQRule.company_id == company.id, FAQRule.keyword == rule_in.keyword.lower())).first()
    if existing: existing.response = rule_in.response; db.add(existing)
    else: db.add(FAQRule(company_id=company.id, keyword=rule_in.keyword.lower(), response=rule_in.response))
    db.commit(); return {"status": "success"}

@app.delete("/admin/rules/{rule_id}")
async def delete_rule(rule_id: int, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    rule = db.get(FAQRule, rule_id)
    if not rule or rule.company_id != company.id: raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule); db.commit(); return {"status": "success"}

@app.get("/admin/settings")
async def get_settings(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
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
async def update_settings(settings_in: SettingsUpdate, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    if settings_in.name: company.name = settings_in.name
    if settings_in.subdomain: company.subdomain = settings_in.subdomain.lower()
    if settings_in.primary_color: company.primary_color = settings_in.primary_color
    if settings_in.logo_url: company.logo_url = settings_in.logo_url
    if settings_in.knowledge_base: company.knowledge_base = settings_in.knowledge_base
    if settings_in.system_prompt: company.system_prompt = settings_in.system_prompt
    if settings_in.openai_api_key: company.openai_api_key = settings_in.openai_api_key
    if settings_in.whatsapp_phone_id: company.whatsapp_phone_id = settings_in.whatsapp_phone_id
    db.add(company); db.commit(); return {"status": "success"}

# --- PUBLIC SAAS SIGNUP ---

class SignupIn(BaseModel):
    name: str
    subdomain: str
    email: str # For admin context
    openai_key: Optional[str] = None

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
async def toggle_takeover(data: TakeoverIn, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    
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
async def get_active_sessions(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    
    # Return sessions active in the last 24 hours
    since = datetime.utcnow().timestamp() - 86400
    return db.exec(select(ChatSession).where(ChatSession.company_id == company.id)).all()

class CorrectionIn(BaseModel):
    log_id: int
    correction: str

@app.post("/admin/logs/correct")
async def correct_log(data: CorrectionIn, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company: raise HTTPException(status_code=403, detail="Invalid API Key")
    log = db.get(ChatLog, data.log_id)
    if not log or log.company_id != company.id: raise HTTPException(status_code=404, detail="Log not found")
    
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
