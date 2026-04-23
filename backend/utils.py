import os
import httpx
import re
import json
import smtplib
import io
import base64
from email.mime.text import MIMEText
from typing import List, Optional
from sqlmodel import Session, select
try:
    from models import ChatLog, Company, FAQRule, Reservation, ChatSession, Order
    from rag_utils import search_kb
except ImportError:
    from .models import ChatLog, Company, FAQRule, Reservation, ChatSession, Order
    from .rag_utils import search_kb
from openai import AsyncOpenAI
from datetime import datetime
import random
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
try:
    cipher_suite = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None
except Exception as e:
    print(f"⚠️ ENCRYPTION ENGINE ERROR: {e}. Secrets will remain unencrypted.")
    cipher_suite = None

def encrypt_field(value: str) -> Optional[str]:
    if not value or not cipher_suite: return value
    try:
        return cipher_suite.encrypt(value.encode()).decode()
    except Exception as e:
        print(f"❌ ENCRYPTION ERROR: {e}")
        return value

def decrypt_field(value: str) -> Optional[str]:
    if not value or not cipher_suite: return value
    try:
        return cipher_suite.decrypt(value.encode()).decode()
    except Exception as e:
        return value 

async def process_message_v3(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en", image_url: Optional[str] = None) -> dict:
    session_state = db.exec(select(ChatSession).where(ChatSession.company_id == company.id, ChatSession.session_id == session_id)).first()
    if not session_state:
        session_state = ChatSession(company_id=company.id, session_id=session_id)
        if session_id.startswith("wa_"): session_state.customer_phone = session_id.replace("wa_", "")
        db.add(session_state)
    
    session_state.last_active = datetime.utcnow()
    if session_state.is_human_takeover: return {"reply": None, "source": "human_takeover", "agent_identity": "Human Agent"}

    user_input = user_msg.lower()
    reply = None
    source = "keyword"
    agent_id = "Shinju Keyword Matcher"

    # --- SYSTEM FAIL-SAFE: DIRECT MENU HANDLER ---
    if any(kw in user_input for kw in ["menu", "serve", "selection", "food", "what do you have", "carte"]):
        if company.knowledge_base:
            reply = f"[MENU_DATA]{company.knowledge_base}"
            source = "system_menu"
            agent_id = "Shinju Menu Specialist"

    # 1. Database Keywords (Custom Business Rules)
    if not reply:
        rules = db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()
        for rule in sorted(rules, key=lambda r: len(r.keyword), reverse=True):
            if rule.keyword.lower() in user_input:
                reply = rule.response
                break
            
    # 2. AI Fallback (Elite Brain / RAG)
    if not reply:
        try:
            ai_result = await get_ai_response(company, session_id, user_msg, db, language=language, image_url=image_url)
            if ai_result:
                reply = ai_result.get("reply")
                agent_id = ai_result.get("agent_identity", "Shinju AI Brain")
                source = "ai"
            else:
                trace_id = f"REF-{datetime.utcnow().strftime('%H%M%S')}"
                openai_check = "Key_Present" if (decrypt_field(company.openai_api_key) or os.getenv("OPENAI_API_KEY")) else "Key_MISSING"
                reply = f"I'm having a brief connection issue with my central brain [{trace_id}]. (TRACE: get_ai_response was None | {openai_check})"
                source = "fallback"
                agent_id = "Shinju AI Fail-Safe"
        except Exception as e:
            trace_id = f"EXC-{datetime.utcnow().strftime('%H%M%S')}"
            print(f"❌ PIPELINE CRASH [{trace_id}]: {type(e).__name__}: {str(e)}")
            reply = f"I encountered an internal error [{trace_id}]: {type(e).__name__}: {str(e)}"
            source = "fallback"
            agent_id = "Shinju AI Error-Guard"

    # Log interaction
    log_entry = ChatLog(company_id=company.id, session_id=session_id, user_msg=user_msg, bot_reply=reply, source=source, timestamp=datetime.utcnow())
    db.add(log_entry); db.commit()
    
    # [RESERVATION TOOL CALL PARSING]
    if reply and "[RESERVATION_TOOL_CALL]" in reply:
        if session_state: session_state.reengagement_status = "completed"; db.add(session_state)
        try:
            parts = reply.split("[RESERVATION_TOOL_CALL]")
            reply_text = parts[0].strip()
            data_str = parts[1].strip()
            data = json.loads(data_str)
            
            new_res = Reservation(
                company_id=company.id, 
                customer_name=data.get("name", "Unknown"),
                date_time=data.get("date_time", data.get("date", "Unknown")), 
                pax=int(data.get("pax", 1)), 
                status="confirmed"
            )
            db.add(new_res); db.commit()
            
            if not reply_text:
                reply = f"Great! I've confirmed your reservation for {new_res.customer_name} on {new_res.date_time} for {new_res.pax} people."
            else:
                reply = reply_text
        except Exception as e:
            print(f"RESERVATION ERROR: {e}")
            pass

    # [ORDER TOOL CALL PARSING]
    if reply and "[ORDER_TOOL_CALL]" in reply:
        try:
            parts = reply.split("[ORDER_TOOL_CALL]")
            reply_text = parts[0].strip()
            data_str = parts[1].strip()
            data = json.loads(data_str)
            
            new_order = Order(
                company_id=company.id,
                customer_name=data.get("name", "Unknown"),
                items=data.get("items", ""),
                total_price=float(data.get("total_price", 0.0)),
                delivery_address=data.get("address", ""),
                status="confirmed"
            )
            db.add(new_order); db.commit()
            
            if not reply_text:
                reply = f"Thank you for your order, {new_order.customer_name}! It's being prepared and will be delivered to {new_order.delivery_address} shortly."
            else:
                reply = reply_text
        except Exception as e:
            print(f"ORDER ERROR: {e}")
            pass

    return {"reply": reply, "source": source, "agent_identity": agent_id}

async def call_openai_raw(key: str, model: str, messages: list, tools: list = None):
    """
    Hyper-Stable Direct REST Bridge to OpenAI (Bypasses library issues).
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json",
        "Connection": "close"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.7
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=45.0, http2=False) as client:
        res = await client.post(url, headers=headers, json=payload)
        if res.status_code != 200:
            raise Exception(f"OpenAI Direct API Error {res.status_code}: {res.text}")
        return res.json()

async def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en", image_url: Optional[str] = None) -> dict:
    db_key = company.openai_api_key
    openai_key = decrypt_field(db_key) if db_key else None
    
    if not openai_key or not str(openai_key).startswith("sk-"):
        openai_key = os.getenv("OPENAI_API_KEY")
        
    if not openai_key:
        print(f"⚠️ AI ERROR: No valid OpenAI Key found for {company.name}")
        return None
    
    # Context Assembly
    raw_kb = company.knowledge_base or ""
    user_input_lower = user_msg.lower()
    if any(kw in user_input_lower for kw in ["menu", "price", "order", "what do you have", "show me", "selection"]) or image_url:
        rag_context = f"DIRECT MENU DATA: {raw_kb[:2000]}"
    else:
        try:
            rag_context = search_kb(company.id, user_msg, api_key=openai_key)
        except Exception as e:
            print(f"⚠️ RAG Search Error: {e}")
            rag_context = ""
        if not rag_context and raw_kb: rag_context = raw_kb[:1000]
    
    history = db.exec(select(ChatLog).where(ChatLog.company_id == company.id, ChatLog.session_id == session_id).order_by(ChatLog.timestamp.desc()).limit(6)).all()
    lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
    target_lang = lang_names.get(language, "English")
    
    master_prompt = (
        f"{company.system_prompt}\n"
        f"KNOWLEDGE: {rag_context}\n"
        f"LANGUAGE: Respond ONLY in {target_lang}."
    )
    
    messages = [{"role": "system", "content": master_prompt}]
    for h in reversed(history):
        if h.user_msg and h.bot_reply:
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        
    user_content = [{"type": "text", "text": user_msg}]
    if image_url:
        user_content.append({"type": "image_url", "image_url": {"url": image_url}})
    messages.append({"role": "user", "content": user_content})
    
    tools = [
        {"type": "function", "function": {"name": "create_reservation", "description": "Book a table", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "date_time": {"type": "string"}, "pax": {"type": "integer"}}, "required": ["name", "date_time", "pax"]}}},
        {"type": "function", "function": {"name": "create_order", "description": "Place food order", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "items": {"type": "string"}, "address": {"type": "string"}, "total_price": {"type": "number"}}, "required": ["name", "items", "address", "total_price"]}}}
    ]
    
    # --- HYBRID COMPLETION STRATEGY ---
    try:
        # Try primary via direct REST bridge (more stable on Render)
        data = await call_openai_raw(openai_key, "gpt-4o-mini", messages, tools)
        choice = data["choices"][0]
        full_reply = choice["message"].get("content") or ""
        
        if choice["message"].get("tool_calls"):
            tc = choice["message"]["tool_calls"][0]
            if tc["function"]["name"] == "create_reservation":
                full_reply += f"\n[RESERVATION_TOOL_CALL]{tc['function']['arguments']}"
            elif tc["function"]["name"] == "create_order":
                full_reply += f"\n[ORDER_TOOL_CALL]{tc['function']['arguments']}"

        agent_id = "AI Concierge"
        if "[RESERVATION_TOOL_CALL]" in full_reply or "[ORDER_TOOL_CALL]" in full_reply: agent_id = "AI Sales Specialist"
        return {"reply": full_reply.strip(), "agent_identity": agent_id}
        
    except Exception as e:
        # Final fallback to standard library if direct bridge fails
        print(f"⚠️ Direct Bridge Failed: {e}. Falling back to library.")
        try:
            client = AsyncOpenAI(api_key=openai_key.strip())
            response = await client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools, tool_choice="auto")
            message = response.choices[0].message
            full_reply = message.content or ""
            if message.tool_calls:
                tc = message.tool_calls[0]
                full_reply += f"\n[{tc.function.name.upper()}_TOOL_CALL]{tc.function.arguments}"
            return {"reply": full_reply.strip(), "agent_identity": "AI Support Specialist (Safe-Mode)"}
        except Exception as e2:
            raise Exception(f"Total Brain Blackout: [Bridge: {str(e)}] [Lib: {str(e2)}]")

async def send_whatsapp_reply(company: Company, to_number: str, text: str):
    access_token = decrypt_field(company.whatsapp_access_token)
    if not (company.whatsapp_phone_id and access_token): return
    url = f"https://graph.facebook.com/v17.0/{company.whatsapp_phone_id}/messages"
    headers = { "Authorization": f"Bearer {access_token}", "Content-Type": "application/json" }
    payload = { "messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text} }
    async with httpx.AsyncClient() as client: await client.post(url, headers=headers, json=payload)

async def send_instagram_reply(company: Company, ig_sid: str, text: str):
    access_token = decrypt_field(company.instagram_access_token)
    if not (company.instagram_page_id and access_token): return
    url = f"https://graph.facebook.com/v17.0/{company.instagram_page_id}/messages"
    headers = { "Authorization": f"Bearer {access_token}", "Content-Type": "application/json" }
    payload = { "recipient": {"id": ig_sid}, "message": {"text": text} }
    async with httpx.AsyncClient() as client: await client.post(url, headers=headers, json=payload)

async def send_post_interaction_confirmation(company: Company, session_id: str, type: str = "order"):
    import asyncio
    await asyncio.sleep(5)
    
    if type == "order":
        msg = f"✨ Shinju Concierge: We've received your order! Our chef is preparing your meal with the finest ingredients. You will be notified once it's out for delivery."
    else:
        msg = f"✨ Shinju Concierge: Your table is ready for your arrival. We look forward to providing you with an exceptional dining experience."

    if session_id.startswith("wa_"):
        await send_whatsapp_reply(company, session_id.replace("wa_", ""), msg)
    elif session_id.startswith("ig_"):
        await send_instagram_reply(company, session_id.replace("ig_", ""), msg)

async def download_whatsapp_media(media_id: str, company: Company) -> Optional[bytes]:
    access_token = decrypt_field(company.whatsapp_access_token)
    if not access_token: return None
    
    url = f"https://graph.facebook.com/v17.0/{media_id}/"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            media_url = res.json().get("url")
            if media_url:
                media_res = await client.get(media_url, headers=headers)
                if media_res.status_code == 200:
                    return media_res.content
    return None

def transcribe_audio(audio_content: bytes, company: Company) -> str:
    openai_key = decrypt_field(company.openai_api_key) or os.getenv("OPENAI_API_KEY")
    if not openai_key: return ""
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key.strip())
        audio_file = io.BytesIO(audio_content)
        audio_file.name = "audio.ogg"
        
        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file
        )
        return transcript.text
    except Exception as e:
        print(f"WHISPER ERROR: {e}")
        return ""

async def email_automation_loop():
    import imaplib, email, asyncio, time
    try:
        from database import engine
    except ImportError:
        from .database import engine

    while True:
        try:
            with Session(engine) as db:
                companies = db.exec(select(Company).where(Company.email_automation_enabled == True)).all()
                for company in companies:
                    if not (company.email_user and company.email_password): continue
                    
                    mail = imaplib.IMAP4_SSL(company.email_imap_server)
                    mail.login(company.email_user, company.email_password)
                    mail.select("inbox")
                    status, messages = mail.search(None, '(UNSEEN)')
                    
                    for num in messages[0].split():
                        status, data = mail.fetch(num, "(RFC822)")
                        raw_email = data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        
                        sender = msg.get("From")
                        subject = msg.get("Subject")
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_payload(decode=True).decode()
                                    break
                        else:
                            body = msg.get_payload(decode=True).decode()

                        session_id = f"email_{sender}"
                        result = await process_message_v3(company, session_id, f"[EMAIL_SUBJECT: {subject}] {body}", db)
                        
                        if result.get("reply"):
                            reply_msg = MIMEText(result["reply"])
                            reply_msg["Subject"] = f"Re: {subject}"
                            reply_msg["From"] = company.email_user
                            reply_msg["To"] = sender
                            
                            with smtplib.SMTP_SSL(company.email_smtp_server, 465) as smtp:
                                smtp.login(company.email_user, company.email_password)
                                smtp.send_message(reply_msg)
                        
                        mail.store(num, '+FLAGS', '\\Seen')
                    
                    mail.logout()
        except Exception as e:
            print(f"EMAIL WORKER ERROR: {e}")
            
        await asyncio.sleep(60)

async def trigger_pro_automation(company: Company, user_msg: str, session_id: str):
    if session_id.startswith("wa_"):
        import asyncio
        asyncio.create_task(schedule_reengagement(company.id, session_id))
    webhook_url = os.getenv("MAKE_WEBHOOK_URL")
    if webhook_url and "placeholder" not in webhook_url:
        payload = { "company": company.name, "msg": user_msg, "sid": session_id }
        async with httpx.AsyncClient() as client: await client.post(webhook_url, json=payload)

async def schedule_reengagement(company_id: int, session_id: str):
    import asyncio
    await asyncio.sleep(10)
    try:
        from database import engine
    except ImportError:
        from .database import engine
    with Session(engine) as db:
        session = db.exec(select(ChatSession).where(ChatSession.company_id == company_id, ChatSession.session_id == session_id)).first()
        if session and session.reengagement_status == "none" and session.customer_phone:
            company = db.get(Company, company_id)
            if company:
                await send_whatsapp_reply(company, session.customer_phone, f"Hello! Ready to finish your booking at {company.name}?")
                session.reengagement_status = "completed"; db.add(session); db.commit()
