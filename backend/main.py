from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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

from backend.database import create_db_and_tables, get_session, engine
from backend.models import Company, FAQRule, ChatLog
from backend.utils import process_message_v3, send_whatsapp_reply

load_dotenv()

# Initialize Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Keiz Chatbot SaaS - Omni-Engine V3 (PRO)")
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
        
        session.commit()

@app.get("/debug/network")
async def debug_network():
    """
    Test outbound connectivity to OpenAI via curl.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-v", "https://api.openai.com/v1/models"],
            capture_output=True, text=True, timeout=10
        )
        return {"stdout": result.stdout, "stderr": result.stderr}
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/httpx")
async def debug_httpx():
    """
    Test raw HTTPX connectivity to OpenAI (without the SDK).
    """
    import httpx
    import os
    key = os.getenv("OPENAI_API_KEY")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"}
            )
            return {
                "status_code": resp.status_code,
                "json": resp.json() if resp.status_code == 200 else str(resp.text),
                "headers": dict(resp.headers)
            }
    except Exception as e:
        return {"error_type": type(e).__name__, "message": str(e)}

@app.get("/debug/ai")
async def debug_ai_endpoint(db: Session = Depends(get_session)):
    """
    Diagnostic endpoint to test OpenAI connection on Render.
    """
    company = db.exec(select(Company)).first()
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"status": "error", "message": "OPENAI_API_KEY env var is MISSING on Render"}
    
    # Clean the key aggressively (remove ALL spaces/newlines from middle)
    key = key.replace(" ", "").replace("\n", "").replace("\r", "").strip()
    
    masked_key = key[:10] + "..." + key[-5:]
    import httpx
    from openai import OpenAI
    try:
        # 2026 Render Fix: Force IPv4
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        http_client = httpx.Client(transport=transport)
        
        client = OpenAI(
            api_key=key, 
            timeout=60.0,
            http_client=http_client
        )
        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": "ping"}],
            max_completion_tokens=10
        )
        return {
            "status": "success", 
            "reply": response.choices[0].message.content, 
            "key_used": masked_key,
            "version": "Diagnostic V5 (Aggressive Key Cleaning + IPv4 Force)"
        }
    except Exception as e:
        return {
            "status": "error", 
            "type": type(e).__name__, 
            "message": str(e), 
            "key_used": masked_key,
            "version": "Diagnostic V5 (Aggressive Key Cleaning + IPv4 Force)"
        }

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
            from_num = message["from"]
            text = message["text"]["body"]
            
            # Identify the company by their phone_id (or other unique metadata)
            phone_id = data["entry"][0]["id"]
            company = db.exec(select(Company).where(Company.whatsapp_phone_id == phone_id)).first()
            
            if company:
                # Use the Omni-Engine brain
                result = process_message_v3(company, f"wa_{from_num}", text, db)
                
                # Send back to WhatsApp
                await send_whatsapp_reply(company, from_num, result["reply"])
                
    except Exception as e:
        print(f"WhatsApp Webhook Error: {e}")
        
    return {"status": "success"}

# --- ADMIN ROUTES ---

@app.get("/admin/logs")
async def get_logs(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return db.exec(
        select(ChatLog)
        .where(ChatLog.company_id == company.id)
        .order_by(ChatLog.timestamp.desc())
        .limit(100)
    ).all()

@app.get("/admin/rules")
async def get_rules(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()

class FAQRuleCreate(BaseModel):
    keyword: str
    response: str

@app.post("/admin/rules")
async def create_rule(rule_in: FAQRuleCreate, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    # Check if keyword already exists
    existing = db.exec(select(FAQRule).where(FAQRule.company_id == company.id, FAQRule.keyword == rule_in.keyword.lower())).first()
    if existing:
        existing.response = rule_in.response
        db.add(existing)
    else:
        new_rule = FAQRule(company_id=company.id, keyword=rule_in.keyword.lower(), response=rule_in.response)
        db.add(new_rule)
    
    db.commit()
    return {"status": "success"}

@app.delete("/admin/rules/{rule_id}")
async def delete_rule(rule_id: int, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    rule = db.get(FAQRule, rule_id)
    if not rule or rule.company_id != company.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(rule)
    db.commit()
    return {"status": "success"}

@app.get("/admin/settings")
async def get_settings(x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return {
        "name": company.name,
        "system_prompt": company.system_prompt,
        "openai_api_key": company.openai_api_key, # Usually masked in prod, but keeping it for now for Root Admin
        "whatsapp_phone_id": company.whatsapp_phone_id,
        "whatsapp_verify_token": company.whatsapp_verify_token
    }

class SettingsUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    openai_api_key: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None

@app.post("/admin/settings")
async def update_settings(settings_in: SettingsUpdate, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    if settings_in.name: company.name = settings_in.name
    if settings_in.system_prompt: company.system_prompt = settings_in.system_prompt
    if settings_in.openai_api_key: company.openai_api_key = settings_in.openai_api_key
    if settings_in.whatsapp_phone_id: company.whatsapp_phone_id = settings_in.whatsapp_phone_id
    
    db.add(company)
    db.commit()
    return {"status": "success"}

from fastapi.responses import FileResponse

@app.get("/agency")
async def get_agency_page():
    return FileResponse(BASE_DIR / "agency.html")

# MOUNT STATIC FILES
# Use paths relative to this file's location for cloud deployment
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/widget", StaticFiles(directory=str(BASE_DIR / "widget")), name="widget")
app.mount("/admin", StaticFiles(directory=str(BASE_DIR / "admin")), name="admin")
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")
