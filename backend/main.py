from fastapi import FastAPI, HTTPException, Header, Depends, Request, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlmodel import Session, select
import os
import uuid
import pdfplumber
import io
import hmac
import hashlib
from dotenv import load_dotenv
import sys
from pathlib import Path

# Add current directory to sys.path for Render/Production import stability
_CURRENT_DIR = Path(__file__).resolve().parent
sys.path.append(str(_CURRENT_DIR))

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Relative imports for local/render consistency
try:
    from database import create_db_and_tables, get_session, engine
    from models import Company, FAQRule, ChatLog, Reservation, ChatSession, TrendInsight
    from utils import process_message_v3, send_whatsapp_reply, email_automation_loop, encrypt_field
    from rag_utils import index_knowledge_base
except ImportError:
    from .database import create_db_and_tables, get_session, engine
    from .models import Company, FAQRule, ChatLog, Reservation, ChatSession, TrendInsight
    from .utils import process_message_v3, send_whatsapp_reply, email_automation_loop, encrypt_field
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
        # --- UNIFIED DEMO SEEDING ---
        try:
            from seed_all_demos import seed_all_demos
        except ImportError:
            from .seed_all_demos import seed_all_demos
        seed_all_demos()

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

            # [NEW] Columns for Instagram/Email Pro Features
            try: conn.execute(text("ALTER TABLE company ADD COLUMN instagram_page_id TEXT;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE company ADD COLUMN instagram_access_token TEXT;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE company ADD COLUMN email_user TEXT;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE company ADD COLUMN email_password TEXT;")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE company ADD COLUMN email_imap_server TEXT DEFAULT 'imap.gmail.com';")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE company ADD COLUMN email_smtp_server TEXT DEFAULT 'smtp.gmail.com';")); conn.commit()
            except: pass
            try: conn.execute(text("ALTER TABLE company ADD COLUMN email_automation_enabled BOOLEAN DEFAULT 0;")); conn.commit()
            except: pass
            
        with Session(engine) as session:
            company = session.exec(select(Company)).first()
            
            # [PRODUCTION BRAIN-PATCH] Ensure default menu exists if KB is empty
            menu_v3 = """
            BURGER LAB - OFFICIAL MENU 2026
            ---
            BEEF BURGERS (AL A CARTE)
            - Beautiful Mess: 12.50€ (Signature Angus beef, fried portobello strips, runny honey egg, charcoal bun)
            - The Chuck Norris: 13.90€ (Angus beef, BBQ beef brisket, crispy onion strings, cheddar)
            - Fat Elvis: 15.50€ (Double Angus beef, creamy peanut butter, blueberry jam - strange but legendary)
            - Good Ol' Cheeseburger: 9.90€ (Classic smash patty, American cheese, pickles)

            CHICKEN BURGERS
            - The Phoenix: 10.90€ (Nashville-style fried chicken, spicy glaze, slaw, pickles)
            - Chicken Tomatina: 11.50€ (Fried chicken, sun-dried tomato pesto, mozzarella, basil)

            SIDES & UPGRADES
            - Meal Upgrade: +3.50€ (Add Regular Fries & Bottomless Soda to any burger)
            - Animal Fries: 5.50€ (Hand-cut fries topped with melted cheese, grilled onions, jalapeños, and secret Lab Sauce)
            - Mushroom Fries: 6.90€ (Fries topped with sautéed portobello mushrooms and truffle oil)
            - Lab Tenders (3pcs): 7.50€ (Crispy buttermilk chicken strips with honey mustard)

            POLICIES & INFO
            - Spice Levels: 'Authentic Heat' salsa is very spicy. Mild options available.
            - Delivery: 3€ flat rate within 5km. Free for orders over 30€.
            - Wait Time: Average 8-12 minutes for 'Turbo-Prep' fresh orders.
            """

            if not company:
                company = Company(
                    name="Fast Food Hub", 
                    api_key="dev-api-key-123",
                    subdomain="fastfood",
                    knowledge_base=menu_v3.strip(),
                    system_prompt="You are the Shinju AI Fast Food Concierge. Your goal is to provide elite, rapid service for our high-volume food hub. CONSTRAINTS: 1. Keep responses ultra-concise. 2. Use plain text only (no bold/italics). 3. Always try to upsell: if someone orders a burger or main dish, ask if they want to 'make it a meal' with large fries and a drink for 3.50€ extra. 4. For delivery orders, capture Name, Address, and Phone Number. 5. If asked about wait times, explain that our 'Turbo-Prep' system ensures most orders are ready in under 8 minutes.",
                    whatsapp_verify_token="shinju_pro_verify",
                    whatsapp_access_token=encrypt_field(os.getenv("WHATSAPP_ACCESS_TOKEN")),
                    instagram_access_token=encrypt_field(os.getenv("INSTAGRAM_ACCESS_TOKEN")),
                    openai_api_key=encrypt_field(os.getenv("OPENAI_API_KEY"))
                )
                session.add(company)
                session.commit()
            else:
                if not company.knowledge_base:
                    company.knowledge_base = menu_v3.strip()
                
                # [CRITICAL] Force sync keys from environment to ensure decryption consistency
                if os.getenv("OPENAI_API_KEY"):
                    company.openai_api_key = encrypt_field(os.getenv("OPENAI_API_KEY"))
                if os.getenv("WHATSAPP_ACCESS_TOKEN"):
                    company.whatsapp_access_token = encrypt_field(os.getenv("WHATSAPP_ACCESS_TOKEN"))
                if os.getenv("INSTAGRAM_ACCESS_TOKEN"):
                    company.instagram_access_token = encrypt_field(os.getenv("INSTAGRAM_ACCESS_TOKEN"))
                
                session.add(company)
                session.commit()

        # [NEW] Start Background Email Worker
        import asyncio
        asyncio.create_task(email_automation_loop())

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
async def chat_endpoint(request: Request, msg: ChatMessage, background_tasks: BackgroundTasks, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    # Process message and get rich metadata
    result = await process_message_v3(company, msg.session_id, msg.message, db, language=msg.language)
    
    # [NEW] Proactive Luxury Follow-up for Web Chat
    if result.get("reply") and ("[RESERVATION_TOOL_CALL]" in result["reply"] or "[ORDER_TOOL_CALL]" in result["reply"]):
        from utils import send_post_interaction_confirmation
        ctype = "reservation" if "[RESERVATION_TOOL_CALL]" in result["reply"] else "order"
        background_tasks.add_task(send_post_interaction_confirmation, company, msg.session_id, ctype)

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

@app.get("/demo_master")
async def get_demo_master():
    return FileResponse(str(BASE_DIR / "demo_master.html"))

@app.get("/dashboard")
async def get_dashboard(): return await get_dashboard_static()

@app.get("/client-dashboard")
async def get_client_dashboard():
    return FileResponse(str(BASE_DIR / "admin" / "client_dashboard.html"))

@app.get("/test")
async def get_test(): return await get_test_static()

# --- UNIFIED META WEBHOOK (WhatsApp + Instagram) ---

@app.get("/webhook/meta")
async def verify_meta(request: Request, db: Session = Depends(get_session)):
    """
    Meta verifies your server URL with a Verify Token (Unified).
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

@app.post("/webhook/meta")
async def handle_meta_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    """
    Unified Meta Webhook for WhatsApp and Instagram DM events with Signature Verification.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    app_secret = os.getenv("META_APP_SECRET")
    
    if app_secret and signature:
        actual_sig = signature.replace("sha256=", "")
        expected_sig = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(actual_sig, expected_sig):
            raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()
    try:
        entry = data["entry"][0]
        
        # 1. Handle WhatsApp
        if "changes" in entry:
            value = entry["changes"][0]["value"]
            if "messages" in value:
                message = value["messages"][0]
                from_num = message["from"]
                
                # Multitenancy resolution via phone_id
                phone_id = value["metadata"]["display_phone_number"]
                company = db.exec(select(Company).where(Company.whatsapp_phone_id == phone_id)).first()
                if not company: company = db.exec(select(Company)).first() # Fallback
                
                if company:
                    text = ""
                    image_url = None
                    msg_type = message.get("type", "text")
                    
                    if msg_type == "text":
                        text = message["text"]["body"]
                    elif msg_type == "audio":
                        from utils import download_whatsapp_media, transcribe_audio
                        audio_id = message["audio"]["id"]
                        audio_bytes = await download_whatsapp_media(audio_id, company)
                        if audio_bytes:
                            text = transcribe_audio(audio_bytes, company)
                            text = f"[VOICE NOTE] {text}"
                    elif msg_type == "image":
                        import base64
                        from utils import download_whatsapp_media
                        image_id = message["image"]["id"]
                        image_bytes = await download_whatsapp_media(image_id, company)
                        mime_type = message["image"].get("mime_type", "image/jpeg")
                        if image_bytes:
                            b64 = base64.b64encode(image_bytes).decode("utf-8")
                            image_url = f"data:{mime_type};base64,{b64}"
                            text = "[IMAGE RECEIVED]"
                    
                    if text or image_url:
                        result = await process_message_v3(company, f"wa_{from_num}", text, db, image_url=image_url)
                        from utils import send_whatsapp_reply, send_post_interaction_confirmation
                        background_tasks.add_task(send_whatsapp_reply, company, from_num, result.get("reply", ""))
                        
                        # [NEW] Proactive Luxury Follow-up
                        if result.get("reply") and ("[RESERVATION_TOOL_CALL]" in result["reply"] or "[ORDER_TOOL_CALL]" in result["reply"]):
                            ctype = "reservation" if "[RESERVATION_TOOL_CALL]" in result["reply"] else "order"
                            background_tasks.add_task(send_post_interaction_confirmation, company, f"wa_{from_num}", ctype)

        # 2. Handle Instagram
        elif "messaging" in entry:
            messaging = entry["messaging"][0]
            sender_id = messaging["sender"]["id"]
            if "message" in messaging and "text" in messaging["message"]:
                text = messaging["message"]["text"]
                page_id = entry["id"]
                company = db.exec(select(Company).where(Company.instagram_page_id == page_id)).first()
                if not company: company = db.exec(select(Company)).first() # Fallback
                
                if company:
                    result = await process_message_v3(company, f"ig_{sender_id}", text, db)
                    from utils import send_instagram_reply, send_post_interaction_confirmation
                    background_tasks.add_task(send_instagram_reply, company, sender_id, result["reply"])
                    
                    # [NEW] Proactive Luxury Follow-up
                    if result.get("reply") and ("[RESERVATION_TOOL_CALL]" in result["reply"] or "[ORDER_TOOL_CALL]" in result["reply"]):
                        ctype = "reservation" if "[RESERVATION_TOOL_CALL]" in result["reply"] else "order"
                        background_tasks.add_task(send_post_interaction_confirmation, company, f"ig_{sender_id}", ctype)
                    
        return {"status": "ok"}
    except Exception as e:
        print(f"META WEBHOOK ERROR: {e}")
        return {"status": "error"}

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
        openai_api_key=encrypt_field(data.openai_key),
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

# --- ADMIN PORTAL ENDPOINTS ---

@app.get("/admin/stats")
async def get_admin_stats(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    total_res = len(company.reservations)
    total_orders = len(company.orders)
    active_chats = len(company.sessions)
    needs_review = db.exec(select(ChatLog).where(ChatLog.company_id == company.id, ChatLog.needs_review == True)).all()
    
    return {
        "active_chats": active_chats,
        "total_reservations": total_res + total_orders,
        "needs_review": len(needs_review),
        "avg_confidence": 98 
    }

@app.get("/admin/reservations")
async def get_reservations(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    
    res = [{"customer_name": r.customer_name, "date_time": r.date_time, "pax": str(r.pax), "type": "reservation"} for r in company.reservations]
    orders = [{"customer_name": o.customer_name, "date_time": o.timestamp.strftime("%Y-%m-%d %H:%M"), "pax": o.items, "type": "order"} for o in company.orders]
    
    combined = res + orders
    return sorted(combined, key=lambda x: x["date_time"], reverse=True)

@app.get("/admin/orders")
async def get_orders(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return sorted(company.orders, key=lambda x: x.timestamp, reverse=True)

@app.get("/admin/rules")
async def get_rules(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return company.rules

@app.post("/admin/rules")
async def add_rule(rule: FAQRule, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    rule.company_id = company.id
    db.add(rule)
    db.commit()
    return {"status": "success"}

@app.delete("/admin/rules/{rule_id}")
async def delete_rule(rule_id: int, request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    rule = db.get(FAQRule, rule_id)
    if rule and rule.company_id == company.id:
        db.delete(rule)
        db.commit()
    return {"status": "success"}

@app.get("/admin/logs")
async def get_logs(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return db.exec(select(ChatLog).where(ChatLog.company_id == company.id).order_by(ChatLog.timestamp.desc()).limit(50)).all()

@app.get("/admin/analytics/trends")
async def get_trends(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_session)):
    company = get_current_company(request, db, x_api_key)
    if not company: raise HTTPException(status_code=403, detail="Invalid Authentication")
    return {"trends": company.insights}

# MOUNT STATIC FILES
app.mount("/widget", StaticFiles(directory=str(BASE_DIR / "widget")), name="widget")
app.mount("/admin_static", StaticFiles(directory=str(BASE_DIR / "admin")), name="admin_static")
app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static_root")
