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

def process_message_v3(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> dict:
    """
    The Omni-Engine Brain:
    1. Check Human Takeover
    2. Check Keywords
    3. Check AI with Self-Routing
    """
    
    # Session Retrieval/Creation
    session_state = db.exec(
        select(ChatSession).where(ChatSession.company_id == company.id, ChatSession.session_id == session_id)
    ).first()
    
    if not session_state:
        session_state = ChatSession(company_id=company.id, session_id=session_id)
        if session_id.startswith("wa_"):
            session_state.customer_phone = session_id.replace("wa_", "")
        db.add(session_state)
    
    session_state.last_active = datetime.utcnow()
    
    if session_state.is_human_takeover:
        return {"reply": None, "source": "human_takeover", "agent_identity": "Human Agent"}

    user_input = user_msg.lower()
    reply = None
    source = "keyword"
    agent_identity = "Shinju Keyword Matcher"
    
    # 1. Keywords (Zero Latency)
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
            agent_identity = ai_result.get("agent_identity", "Shinju AI Brain")
            source = "ai"
        else:
            # Final Fallback
            fallback_msgs = {
                "en": "I am here to guide your journey. Could you please specify if you are looking for our curated menu, reservation details, or perhaps our bespoke pricing?",
                "fr": "Je suis là pour guider votre expérience. Pourriez-vous préciser si vous recherchez notre menu, des détails de réservation ou nos tarifs ?",
                "es": "Estoy aquí para guiar su experiencia. ¿Podría especificar si busca nuestro menú, detalles de reserva o nuestras tarifas?"
            }
            reply = fallback_msgs.get(language, fallback_msgs["en"])
            source = "fallback"
            agent_identity = "Shinju AI Navigator"

    # Log the interaction
    log_entry = ChatLog(
        company_id=company.id, session_id=session_id, user_msg=user_msg, bot_reply=reply, 
        source=source, timestamp=datetime.utcnow()
    )
    db.add(log_entry)
    db.commit()
    
    # [RESERVATION SYSTEM]
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
        except Exception as e: print(f"RESERVATION ERROR: {e}")

    # Escalation check
    if any(word in user_input for word in ["human", "help", "aide", "urgent"]):
        import asyncio
        asyncio.create_task(trigger_pro_automation(company, user_msg, session_id))

    return {"reply": reply, "source": source, "agent_identity": agent_identity}

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> dict:
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        print("❌ CRITICAL: No OpenAI API Key found.")
        return None
    
    try:
        client = OpenAI(api_key=openai_key.strip(), timeout=60.0)
        rag_context = search_kb(company.id, user_msg, api_key=openai_key)
        
        history = db.exec(select(ChatLog).where(ChatLog.company_id == company.id, ChatLog.session_id == session_id)
                          .order_by(ChatLog.timestamp.desc()).limit(6)).all()
        
        lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
        target_lang = lang_names.get(language, "English")
        
        kb_block = f"\nKNOWLEDGE:\n{rag_context}\n" if rag_context else ""
        
        master_prompt = (
            f"{company.system_prompt}\n"
            f"IDENTITIES: You dynamically switch between 'Sales Concierge' (for bookings/pricing) and 'Support Specialist' (for info).\n"
            f"{kb_block}\n"
            f"FORMATTING: You MUST start your response with either [SALES] or [SUPPORT] based on the user's intent.\n"
            f"If intent is SALES: Focus on capturing Name, Date, Pax. Confirm with [RESERVATION_SUCCESS] and [DATA]{{\"name\":\"..\",\"date\":\"..\",\"pax\":0}}[/DATA].\n"
            f"If intent is SUPPORT: Be detailed and use only provided KNOWLEDGE.\n"
            f"RESPONSE LANGUAGE: {target_lang}."
        )
        
        messages = [{"role": "system", "content": master_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        messages.append({"role": "user", "content": user_msg})
        
        response = client.chat.completions.create(
            model="gpt-4o", # Using a highly stable model name
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )
        full_reply = response.choices[0].message.content.strip()
        
        # Parse self-routed identity
        agent_id = "AI Support Specialist"
        if full_reply.startswith("[SALES]"):
            agent_id = "AI Sales Concierge"
            full_reply = full_reply.replace("[SALES]", "").strip()
        elif full_reply.startswith("[SUPPORT]"):
            full_reply = full_reply.replace("[SUPPORT]", "").strip()

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
