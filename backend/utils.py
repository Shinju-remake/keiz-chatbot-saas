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
    3. Check AI with Intent Routing
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
        log_entry = ChatLog(
            company_id=company.id, session_id=session_id, user_msg=user_msg, bot_reply="[HUMAN_ACTIVE]", 
            source="human_takeover", timestamp=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        return {"reply": None, "source": "human_takeover", "agent_identity": "Human Agent"}

    user_input = user_msg.lower()
    reply = None
    source = "keyword"
    agent_identity = "Shinju Keyword Matcher"
    
    # 1. Keywords
    rules = db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()
    for rule in sorted(rules, key=lambda r: len(r.keyword), reverse=True):
        if rule.keyword.lower() in user_input:
            reply = rule.response
            break
            
    # 2. AI Fallback with Intent Routing
    if not reply:
        ai_result = get_ai_response(company, session_id, user_msg, db, language=language)
        if ai_result:
            if isinstance(ai_result, dict):
                reply = ai_result.get("reply")
                agent_identity = ai_result.get("agent_identity", "Shinju AI Brain")
            else:
                reply = ai_result
                agent_identity = "Shinju AI Brain"
            source = "ai"
        else:
            fallback_msgs = {
                "en": "I'm not sure about that. Try asking about 'price' or 'contact'.",
                "fr": "Je ne suis pas sûr de comprendre. Essayez de demander les 'prix' ou le 'contact'.",
                "es": "No estoy seguro de eso. Intente preguntar sobre 'precio' o 'contacto'."
            }
            reply = fallback_msgs.get(language, fallback_msgs["en"])
            source = "fallback"
            agent_identity = "Shinju Fallback Agent"

    # Log the interaction
    confidence = 1.0
    needs_review = False
    
    if source == "ai":
        confidence = 0.85
        needs_review = True 
    elif source == "fallback":
        confidence = 0.3
        needs_review = True
        
    log_entry = ChatLog(
        company_id=company.id, 
        session_id=session_id, 
        user_msg=user_msg, 
        bot_reply=reply, 
        source=source,
        confidence_score=confidence,
        needs_review=needs_review,
        timestamp=datetime.utcnow()
    )
    db.add(log_entry)
    db.commit()
    
    # [RESERVATION SYSTEM] Parse and save if successful
    if reply and "[RESERVATION_SUCCESS]" in reply:
        if session_state:
            session_state.reengagement_status = "completed"
            db.add(session_state)
            
        try:
            match = re.search(r"\[DATA\](.*?)\[/DATA\]", reply, re.DOTALL)
            if match:
                data_str = match.group(1).strip()
                data = json.loads(data_str)
                
                new_res = Reservation(
                    company_id=company.id,
                    customer_name=data.get("name", "Unknown"),
                    date_time=data.get("date", "Unknown"),
                    pax=int(data.get("pax", 1)),
                    status="confirmed"
                )
                db.add(new_res)
                db.commit()
                print(f"✅ AUTO-RESERVATION: Captured booking for {new_res.customer_name}")
                reply = re.sub(r"\[DATA\].*?\[/DATA\]", "", reply, flags=re.DOTALL).strip()
        except Exception as e:
            print(f"RESERVATION EXTRACTION ERROR: {e}")

    # Check for escalation triggers
    escalation_words = ["human", "escalate", "help", "aide", "humain", "urgent", "problem", "problème", "reservation", "book"]
    if any(word in user_input for word in escalation_words):
        import asyncio
        asyncio.create_task(trigger_pro_automation(company, user_msg, session_id))

    return {"reply": reply, "source": source, "agent_identity": agent_identity}

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> dict:
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return None
    
    openai_key = openai_key.replace(" ", "").replace("\n", "").replace("\r", "").strip()

    try:
        client = OpenAI(api_key=openai_key, timeout=60.0)
        
        # ADVANCED RAG
        rag_context = search_kb(company.id, user_msg, api_key=openai_key)
        
        history = db.exec(
            select(ChatLog)
            .where(ChatLog.company_id == company.id)
            .where(ChatLog.session_id == session_id)
            .order_by(ChatLog.timestamp.desc())
            .limit(6)
        ).all()
        
        lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
        target_lang = lang_names.get(language, "English")
        
        # --- PHASE 5: INTENT ROUTER ---
        router_prompt = f"Analyze the user message and classify the core intent into EXACTLY ONE of these categories: 'SALES' (booking, reserving, pricing, buying), 'SUPPORT' (faq, location, menu, general questions). Message: '{user_msg}'"
        intent_response = client.chat.completions.create(
            model="gpt-4o-mini", # Using a faster model for routing
            messages=[{"role": "user", "content": router_prompt}],
            max_tokens=10,
            temperature=0.1
        )
        intent = intent_response.choices[0].message.content.strip().upper()
        
        kb_context = f"\nRELEVANT COMPANY KNOWLEDGE:\n{rag_context}\n" if rag_context else ""
        
        if "SALES" in intent:
            agent_persona = (
                "You are an elite Sales Concierge. Your primary objective is to secure a reservation/order. "
                "Collect: Name, Date/Time, and Pax. If some info is provided, don't ask again. "
                "Once ALL details are gathered, confirm and say exactly: [RESERVATION_SUCCESS]. "
                "Append hidden data block: [DATA]{\"name\": \"Name\", \"date\": \"Date\", \"pax\": 4}[/DATA]"
            )
            agent_id = "AI Sales Concierge"
        else:
            agent_persona = (
                "You are an empathetic Customer Support Specialist. Provide accurate answers using provided knowledge. "
                "Do not push for a sale unless asked."
            )
            agent_id = "AI Support Specialist"
            
        full_system_prompt = (company.system_prompt + kb_context + f"\nIMPORTANT: You MUST respond in {target_lang}. " + agent_persona)
        
        messages = [{"role": "system", "content": full_system_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        messages.append({"role": "user", "content": user_msg})
        
        response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=messages,
            max_tokens=250,
            temperature=0.7
        )
        reply_text = response.choices[0].message.content.strip()
        
        return {
            "reply": reply_text,
            "agent_identity": agent_id
        }
    except Exception as e:
        print(f"OPENAI CLOUD ERROR: {e}")
        return None

async def send_whatsapp_reply(company: Company, to_number: str, text: str):
    if not (company.whatsapp_phone_id and company.whatsapp_access_token):
        return
    url = f"https://graph.facebook.com/v17.0/{company.whatsapp_phone_id}/messages"
    headers = { "Authorization": f"Bearer {company.whatsapp_access_token}", "Content-Type": "application/json" }
    payload = { "messaging_product": "whatsapp", "to": to_number, "type": "text", "text": {"body": text} }
    async with httpx.AsyncClient() as client:
        await client.post(url, headers=headers, json=payload)

async def trigger_pro_automation(company: Company, user_msg: str, session_id: str):
    if session_id.startswith("wa_"):
        import asyncio
        asyncio.create_task(schedule_reengagement(company.id, session_id))
    webhook_url = os.getenv("MAKE_WEBHOOK_URL")
    payload = { "company_name": company.name, "session_id": session_id, "message": user_msg, "timestamp": datetime.utcnow().isoformat() }
    if webhook_url and "placeholder" not in webhook_url:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(webhook_url, json=payload, timeout=10.0)
        except Exception as e:
            print(f"AUTOMATION ERROR: {e}")

async def schedule_reengagement(company_id: int, session_id: str):
    import asyncio
    await asyncio.sleep(10) 
    from database import engine
    with Session(engine) as db:
        session = db.exec(select(ChatSession).where(ChatSession.company_id == company_id, ChatSession.session_id == session_id)).first()
        if session and session.reengagement_status == "none" and session.customer_phone:
            company = db.get(Company, company_id)
            if company:
                re_msg = f"Hello! We noticed you were interested in a reservation at {company.name}. Would you like to pick up where you left off?"
                await send_whatsapp_reply(company, session.customer_phone, re_msg)
                session.reengagement_status = "completed"
                db.add(session)
                db.commit()
