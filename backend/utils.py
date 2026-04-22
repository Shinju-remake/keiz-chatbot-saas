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
from openai import OpenAI
from datetime import datetime
import random
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
cipher_suite = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

def encrypt_field(value: str) -> Optional[str]:
    if not value or not cipher_suite: return value
    return cipher_suite.encrypt(value.encode()).decode()

def decrypt_field(value: str) -> Optional[str]:
    if not value or not cipher_suite: return value
    try:
        return cipher_suite.decrypt(value.encode()).decode()
    except:
        return value # Return as-is if decryption fails (e.g. not encrypted yet)

def process_message_v3(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en", image_url: Optional[str] = None) -> dict:
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
        ai_result = get_ai_response(company, session_id, user_msg, db, language=language, image_url=image_url)
        if ai_result:
            reply = ai_result.get("reply")
            agent_id = ai_result.get("agent_identity", "Shinju AI Brain")
            source = "ai"
        else:
            # Final Fallback - Specific to Fast Food
            reply = "I'm having a brief connection issue with my central brain, but I can still take your order! Would you like to see the **menu** or provide your delivery address?"
            source = "fallback"
            agent_id = "Shinju AI Fail-Safe"

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
            
            # Post-interaction trigger
            from main import background_tasks
            # Note: This is a hack because process_message_v3 doesn't have background_tasks. 
            # In main.py we will handle this properly.
            
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

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en", image_url: Optional[str] = None) -> dict:
    openai_key = decrypt_field(company.openai_api_key) or os.getenv("OPENAI_API_KEY")
    if not openai_key: return None
    
    try:
        client = OpenAI(api_key=openai_key.strip(), timeout=30.0)
        
        # [NEW] BRAIN-DIRECT BYPASS: Always include relevant menu text if asking about menu/prices
        raw_kb = company.knowledge_base or ""
        if any(kw in user_msg.lower() for kw in ["menu", "price", "order", "what do you have", "show me", "selection"]) or image_url:
            rag_context = f"DIRECT MENU DATA: {raw_kb[:2000]}" # prioritize raw menu data
        else:
            rag_context = search_kb(company.id, user_msg, api_key=openai_key)
            if not rag_context and raw_kb: rag_context = raw_kb[:1000] # Fallback to start of KB
        
        history = db.exec(select(ChatLog).where(ChatLog.company_id == company.id, ChatLog.session_id == session_id).order_by(ChatLog.timestamp.desc()).limit(6)).all()
        lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
        target_lang = lang_names.get(language, "English")
        
        master_prompt = (
            f"{company.system_prompt}\n"
            f"IDENTITIES: Switch between 'Sales Concierge' (for bookings/orders) and 'Support Specialist' (for info).\n"
            f"KNOWLEDGE: {rag_context}\n"
            f"LANGUAGE: Respond ONLY in {target_lang}."
        )
        
        messages = [{"role": "system", "content": master_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
            
        user_content = [{"type": "text", "text": user_msg}]
        if image_url:
            user_content.append({"type": "image_url", "image_url": {"url": image_url}})
            
        messages.append({"role": "user", "content": user_content})
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "create_reservation",
                    "description": "Creates a new table reservation for the customer.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The name of the customer."},
                            "date_time": {"type": "string", "description": "The date and time of the reservation (e.g. 2024-05-20 19:00)."},
                            "pax": {"type": "integer", "description": "The number of people (pax)."}
                        },
                        "required": ["name", "date_time", "pax"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_order",
                    "description": "Creates a new delivery order for the customer.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The name of the customer."},
                            "items": {"type": "string", "description": "List of food items and options."},
                            "address": {"type": "string", "description": "Full delivery address."},
                            "total_price": {"type": "number", "description": "Calculated total price in EUR."}
                        },
                        "required": ["name", "items", "address", "total_price"]
                    }
                }
            }
        ]
        
        # --- MODEL FALLBACK CHAIN ---
        try:
            response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools, tool_choice="auto", max_tokens=300, temperature=0.7)
        except:
            response = client.chat.completions.create(model="gpt-4o", messages=messages, tools=tools, tool_choice="auto", max_tokens=300, temperature=0.7)
            
        message = response.choices[0].message
        full_reply = message.content or ""
        
        if message.tool_calls:
            tool_call = message.tool_calls[0]
            if tool_call.function.name == "create_reservation":
                args = json.loads(tool_call.function.arguments)
                full_reply += f"\n[RESERVATION_TOOL_CALL]{json.dumps(args)}"
            elif tool_call.function.name == "create_order":
                args = json.loads(tool_call.function.arguments)
                full_reply += f"\n[ORDER_TOOL_CALL]{json.dumps(args)}"

        agent_id = "AI Support Specialist"
        if "[RESERVATION_TOOL_CALL]" in full_reply or "[ORDER_TOOL_CALL]" in full_reply: agent_id = "AI Sales Concierge"
        elif full_reply.startswith("[SALES]"): agent_id = "AI Sales Concierge"; full_reply = full_reply.replace("[SALES]", "").strip()
        elif full_reply.startswith("[SUPPORT]"): full_reply = full_reply.replace("[SUPPORT]", "").strip()

        return {"reply": full_reply.strip(), "agent_identity": agent_id}
    except Exception as e:
        print(f"❌ OPENAI ERROR: {e}")
        return None

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
    """
    Luxury Follow-up: Sends a proactive confirmation message 5 seconds after a success event.
    """
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
    """
    Background worker to poll IMAP for new emails and reply via SMTP.
    """
    import imaplib, email, asyncio, time
    from database import engine

    while True:
        try:
            with Session(engine) as db:
                companies = db.exec(select(Company).where(Company.email_automation_enabled == True)).all()
                for company in companies:
                    if not (company.email_user and company.email_password): continue
                    
                    # 1. Poll IMAP
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

                        # 2. Process via AI
                        session_id = f"email_{sender}"
                        result = process_message_v3(company, session_id, f"[EMAIL_SUBJECT: {subject}] {body}", db)
                        
                        # 3. Send SMTP Reply
                        if result.get("reply"):
                            import smtplib
                            from email.mime.text import MIMEText
                            
                            reply_msg = MIMEText(result["reply"])
                            reply_msg["Subject"] = f"Re: {subject}"
                            reply_msg["From"] = company.email_user
                            reply_msg["To"] = sender
                            
                            with smtplib.SMTP_SSL(company.email_smtp_server, 465) as smtp:
                                smtp.login(company.email_user, company.email_password)
                                smtp.send_message(reply_msg)
                        
                        # Mark as read
                        mail.store(num, '+FLAGS', '\\Seen')
                    
                    mail.logout()
        except Exception as e:
            print(f"EMAIL WORKER ERROR: {e}")
            
        await asyncio.sleep(60) # Poll every minute

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
    from database import engine
    with Session(engine) as db:
        session = db.exec(select(ChatSession).where(ChatSession.company_id == company_id, ChatSession.session_id == session_id)).first()
        if session and session.reengagement_status == "none" and session.customer_phone:
            company = db.get(Company, company_id)
            if company:
                await send_whatsapp_reply(company, session.customer_phone, f"Hello! Ready to finish your booking at {company.name}?")
                session.reengagement_status = "completed"; db.add(session); db.commit()
