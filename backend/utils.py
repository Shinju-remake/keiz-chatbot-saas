from openai import OpenAI
from typing import List, Optional
from sqlmodel import Session, select
try:
    from models import ChatLog, Company, FAQRule, Reservation, ChatSession
    from rag_utils import search_kb
except ImportError:
    from .models import ChatLog, Company, FAQRule, Reservation, ChatSession
    from .rag_utils import search_kb
import os
import httpx
import re
import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import random

def process_message_v3(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> dict:
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

    # --- EMERGENCY KEYWORDS (Zero Latency) ---
    if "menu" in user_input or "carte" in user_input:
        reply = "Our curated menu features the finest seasonal selections. You can view our current offerings in the 'Menu' section of our portal, or I can describe our signature Omakase experience for you."
    elif "reservation" in user_input or "book" in user_input or "réserver" in user_input:
        reply = "I would be delighted to assist with your reservation. Please provide your **Name**, the **Date and Time** you wish to join us, and the number of **Guests** (Pax)."
    
    # 1. Database Keywords
    if not reply:
        rules = db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()
        for rule in sorted(rules, key=lambda r: len(r.keyword), reverse=True):
            if rule.keyword.lower() in user_input:
                reply = rule.response
                break
            
    # 2. AI Fallback (Elite Brain)
    if not reply:
        ai_result = get_ai_response(company, session_id, user_msg, db, language=language)
        if ai_result:
            reply = ai_result.get("reply")
            agent_id = ai_result.get("agent_identity", "Shinju AI Brain")
            source = "ai"
        else:
            # Final Fallback - Elegant & Dynamic
            fallbacks = [
                "I am here to guide your journey. Could you please specify if you are looking for our curated menu, reservation details, or perhaps our bespoke pricing?",
                "I want to ensure you find exactly what you need. Are we discussing a new reservation, or would you like to explore our latest menu selections?",
                "The Shinju experience is tailored to your needs. Shall we proceed with a booking, or do you have specific questions about our services?"
            ]
            reply = random.choice(fallbacks)
            source = "fallback"
            agent_id = "Shinju AI Navigator"

    # Log interaction
    log_entry = ChatLog(company_id=company.id, session_id=session_id, user_msg=user_msg, bot_reply=reply, source=source, timestamp=datetime.utcnow())
    db.add(log_entry); db.commit()
    
    # [RESERVATION SUCCESS PARSING]
    if reply and "[RESERVATION_SUCCESS]" in reply:
        if session_state: session_state.reengagement_status = "completed"; db.add(session_state)
        try:
            match = re.search(r"\[DATA\](.*?)\[/DATA\]", reply, re.DOTALL)
            if match:
                data = json.loads(match.group(1).strip())
                new_res = Reservation(company_id=company.id, customer_name=data.get("name", "Unknown"),
                                    date_time=data.get("date", "Unknown"), pax=int(data.get("pax", 1)), status="confirmed")
                db.add(new_res); db.commit()
                reply = re.sub(r"\[DATA\].*?\[/DATA\]", "", reply, flags=re.DOTALL).strip()
        except: pass

    return {"reply": reply, "source": source, "agent_identity": agent_id}

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> dict:
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key: return None
    
    try:
        client = OpenAI(api_key=openai_key.strip(), timeout=30.0)
        rag_context = search_kb(company.id, user_msg, api_key=openai_key)
        history = db.exec(select(ChatLog).where(ChatLog.company_id == company.id, ChatLog.session_id == session_id).order_by(ChatLog.timestamp.desc()).limit(6)).all()
        lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
        target_lang = lang_names.get(language, "English")
        
        master_prompt = (
            f"{company.system_prompt}\n"
            f"IDENTITIES: Switch between 'Sales Concierge' (for bookings) and 'Support Specialist' (for info).\n"
            f"KNOWLEDGE: {rag_context}\n"
            f"FORMAT: Start with [SALES] or [SUPPORT]. If SALES, capture Name, Date, Pax. If all info gathered, confirm with [RESERVATION_SUCCESS] and JSON block.\n"
            f"LANGUAGE: Respond ONLY in {target_lang}."
        )
        
        messages = [{"role": "system", "content": master_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        messages.append({"role": "user", "content": user_msg})
        
        # --- MODEL FALLBACK CHAIN ---
        try:
            response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=300, temperature=0.7)
        except:
            response = client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=300, temperature=0.7)
            
        full_reply = response.choices[0].message.content.strip()
        agent_id = "AI Support Specialist"
        if full_reply.startswith("[SALES]"): agent_id = "AI Sales Concierge"; full_reply = full_reply.replace("[SALES]", "").strip()
        elif full_reply.startswith("[SUPPORT]"): full_reply = full_reply.replace("[SUPPORT]", "").strip()

        return {"reply": full_reply, "agent_identity": agent_id}
    except Exception as e:
        print(f"❌ OPENAI ERROR: {e}")
        return None

async def send_whatsapp_reply(company: Company, to_number: str, text: str):
    if not (company.whatsapp_phone_id and company.whatsapp_access_token): return
    url = f"https://graph.facebook.com/v17.0/{company.whatsapp_phone_id}/messages"
    headers = { "Authorization": f"Bearer {company.whatsapp_access_token}", "Content-Type": "application/json" }
    payload = { "messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text} }
    async with httpx.AsyncClient() as client: await client.post(url, headers=headers, json=payload)

async def send_instagram_reply(company: Company, ig_sid: str, text: str):
    """
    Sends a reply via the Meta Graph API for Instagram DMs.
    """
    if not (company.instagram_page_id and company.instagram_access_token): return
    url = f"https://graph.facebook.com/v17.0/{company.instagram_page_id}/messages"
    headers = { "Authorization": f"Bearer {company.instagram_access_token}", "Content-Type": "application/json" }
    payload = { "recipient": {"id": ig_sid}, "message": {"text": text} }
    async with httpx.AsyncClient() as client: await client.post(url, headers=headers, json=payload)

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
