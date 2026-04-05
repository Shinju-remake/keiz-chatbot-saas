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
        if not session.exec(select(Company)).first():
            demo_company = Company(
                name="Keiz Bistro", 
                api_key="dev-api-key-123",
                system_prompt="You are a helpful assistant for Keiz Bistro. Prices range from €10 to €50.",
                whatsapp_verify_token="keiz_pro_verify" # For Pro formula
            )
            session.add(demo_company)
            session.commit()
            session.refresh(demo_company)
            
            rules = [
                FAQRule(company_id=demo_company.id, keyword="price", response="Our prices range from €10 to €50. Check our menu for details!"),
                FAQRule(company_id=demo_company.id, keyword="contact", response="You can reach us at contact@keizbistro.com or call +33 1 23 45 67 89."),
                FAQRule(company_id=demo_company.id, keyword="book", response="To book a table, please provide your name and number of guests.")
            ]
            session.add_all(rules)
            session.commit()

class ChatMessage(BaseModel):
    message: str
    session_id: str

class ChatResponse(BaseModel):
    reply: str
    source: str

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("60/minute")
async def chat_endpoint(request: Request, msg: ChatMessage, x_api_key: str = Header(...), db: Session = Depends(get_session)):
    company = db.exec(select(Company).where(Company.api_key == x_api_key)).first()
    if not company:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    
    result = process_message_v3(company, msg.session_id, msg.message, db)
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

# MOUNT STATIC FILES
# Use paths relative to this file's location for cloud deployment
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/widget", StaticFiles(directory=str(BASE_DIR / "widget")), name="widget")
app.mount("/admin", StaticFiles(directory=str(BASE_DIR / "admin")), name="admin")
app.mount("/", StaticFiles(directory=str(BASE_DIR), html=True), name="static")
