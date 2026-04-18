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
    1. Check Human Takeover (If active, SILENCE AI)
    2. Check Keywords
    3. Check AI (GPT-5.4 Nano)
    """
    
    # [NEW] Session Retrieval/Creation
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
        # AI is silenced. Log the user message and return a flag.
        log_entry = ChatLog(
            company_id=company.id, session_id=session_id, user_msg=user_msg, bot_reply="[HUMAN_ACTIVE]", 
            source="human_takeover", timestamp=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        return {"reply": None, "source": "human_takeover"}

    user_input = user_msg.lower()
    reply = None
    source = "keyword"
    
    # 1. Keywords
    rules = db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()
    for rule in sorted(rules, key=lambda r: len(r.keyword), reverse=True):
        if rule.keyword.lower() in user_input:
            reply = rule.response
            break
            
    # 2. AI Fallback
    if not reply:
        ai_reply = get_ai_response(company, session_id, user_msg, db, language=language)
        if ai_reply:
            reply = ai_reply
            source = "ai"
        else:
            fallback_msgs = {
                "en": "I'm not sure about that. Try asking about 'price' or 'contact'.",
                "fr": "Je ne suis pas sûr de comprendre. Essayez de demander les 'prix' ou le 'contact'.",
                "es": "No estoy seguro de eso. Intente preguntar sobre 'precio' o 'contacto'."
            }
            reply = fallback_msgs.get(language, fallback_msgs["en"])
            source = "fallback"

    # Log the interaction
    confidence = 1.0
    needs_review = False
    
    if source == "ai":
        confidence = 0.85 # High for now, can be improved with logprobs or another AI call
        needs_review = True # Pro-tier: All AI replies need 1st review in some industries
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
            # Extract JSON data from the hidden [DATA] tags
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
                
                # Clean the reply for the user (remove the technical [DATA] block)
                reply = re.sub(r"\[DATA\].*?\[/DATA\]", "", reply, flags=re.DOTALL).strip()
        except Exception as e:
            print(f"RESERVATION EXTRACTION ERROR: {e}")

    # Check for escalation triggers
    escalation_words = ["human", "escalate", "help", "aide", "humain", "urgent", "problem", "problème", "reservation", "book"]
    if any(word in user_input for word in escalation_words):
        import asyncio
        asyncio.create_task(trigger_pro_automation(company, user_msg, session_id))

    return {"reply": reply, "source": source, "agent_identity": agent_identity}

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> str:
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return None
    
    openai_key = openai_key.replace(" ", "").replace("\n", "").replace("\r", "").strip()

    try:
        client = OpenAI(
            api_key=openai_key, 
            timeout=60.0
        )
        
        # [NEW] ADVANCED RAG: Perform semantic search for relevant context
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
        # Fast intent classification to route to the correct specialized agent
        router_prompt = f"Analyze the user message and classify the core intent into EXACTLY ONE of these categories: 'SALES' (booking, reserving, pricing, buying), 'SUPPORT' (faq, location, menu, general questions). Message: '{user_msg}'"
        intent_response = client.chat.completions.create(
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": router_prompt}],
            max_completion_tokens=10,
            temperature=0.1
        )
        intent = intent_response.choices[0].message.content.strip().upper()
        
        # RAG / Knowledge Base Injection
        kb_context = f"\nRELEVANT COMPANY KNOWLEDGE:\n{rag_context}\n" if rag_context else ""
        
        # --- MULTI-AGENT ORCHESTRATION ---
        if "SALES" in intent:
            # Sales Agent: Aggressive closing, concise, focuses on capturing lead data
            agent_persona = (
                "You are an elite Sales Concierge. Your primary objective is to secure a reservation/order. "
                "Be extremely polite but highly focused on moving the user to the next step. "
                "Your goal is to collect: Name, Date/Time, and Pax. "
                "CRITICAL: If the user provides some of this information, do NOT ask for it again. "
                "Instead, acknowledge what you have and elegantly ask for only the MISSING details. "
                "When listing missing requirements, put each on its own NEW LINE using a dash. "
                "Highlight missing questions with **double asterisks**. "
                "Once ALL details are gathered, confirm the summary and say exactly: [RESERVATION_SUCCESS]. "
                "Immediately after [RESERVATION_SUCCESS], append the hidden data block: "
                "[DATA]{\"name\": \"Name\", \"date\": \"Date\", \"pax\": 4}[/DATA]"
            )
            print(f"🤖 [ROUTER] Routed session {session_id} to SALES Agent.")
        else:
            # Support Agent: Empathetic, detailed, focuses on RAG data extraction
            agent_persona = (
                "You are an empathetic Customer Support Specialist. Your primary objective is to provide detailed, "
                "highly accurate answers using ONLY the provided RELEVANT COMPANY KNOWLEDGE. "
                "If the answer is not in the knowledge base, apologize and offer to connect them with a human agent. "
                "Do not push for a sale unless the user explicitly asks to book or buy."
            )
            print(f"🤖 [ROUTER] Routed session {session_id} to SUPPORT Agent.")
            
        full_system_prompt = (
            company.system_prompt + 
            kb_context +
            f"\nIMPORTANT: You MUST respond in {target_lang}. " +
            agent_persona
        )
        
        messages = [{"role": "system", "content": full_system_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        messages.append({"role": "user", "content": user_msg})
        
        response = client.chat.completions.create(
            model="gpt-5.4-nano", # Reverting to the original Elite Brain
            messages=messages,
            max_completion_tokens=250,
            temperature=0.7
        )
        reply_text = response.choices[0].message.content.strip()
        
        return {
            "reply": reply_text,
            "agent_identity": "AI Sales Concierge" if "SALES" in intent else "AI Support Specialist"
        }
    except Exception as e:
        print(f"OPENAI CLOUD ERROR: {e}")
        # Intelligent Fallback: Return a helpful message instead of crashing
        return "I am currently fine-tuning my expertise. How else can I assist you with Shinju AI services?"

async def send_whatsapp_reply(company: Company, to_number: str, text: str):
    """
    Pro Feature: Direct reply via WhatsApp Cloud API.
    """
    if not (company.whatsapp_phone_id and company.whatsapp_access_token):
        return
        
    url = f"https://graph.facebook.com/v17.0/{company.whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {company.whatsapp_access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, headers=headers, json=payload)

async def trigger_pro_automation(company: Company, user_msg: str, session_id: str):
    """
    Pro Tier: Trigger Make.com Webhook and AI Re-engagement scheduler.
    """
    # Logic: Only schedule re-engagement for WhatsApp sessions that haven't completed.
    # Implementation for MVP: Fire re-engagement check in 2 hours (Simulated).
    if session_id.startswith("wa_"):
        import asyncio
        asyncio.create_task(schedule_reengagement(company.id, session_id))

    webhook_url = os.getenv("MAKE_WEBHOOK_URL")
    admin_email = os.getenv("ADMIN_EMAIL", "traore.m.2007@gmail.com")
    
    payload = {
        "company_name": company.name,
        "session_id": session_id,
        "message": user_msg,
        "admin_email": admin_email,
        "timestamp": datetime.utcnow().isoformat(),
        "platform": "Web Widget" if not session_id.startswith("wa_") else "WhatsApp"
    }

    print(f"DEBUG: Triggering Pro Automation for {company.name} (Session: {session_id})")
    
    if webhook_url and "placeholder" not in webhook_url:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(webhook_url, json=payload, timeout=10.0)
        except Exception as e:
            print(f"AUTOMATION ERROR: {e}")
    else:
        # Fallback to local log/email-sim if no webhook is set
        print(f"NOTICE: Webhook placeholder active. Escalation for '{user_msg}' logged to terminal.")

async def schedule_reengagement(company_id: int, session_id: str):
    """
    Wait 2 hours (or minutes for testing) and send a friendly WhatsApp follow-up if 
    the user hasn't completed their booking.
    """
    import asyncio
    # For MVP test, we wait 10 seconds. Production would be 7200 (2 hours).
    await asyncio.sleep(10) 
    
    from database import engine
    with Session(engine) as db:
        session = db.exec(
            select(ChatSession).where(ChatSession.company_id == company_id, ChatSession.session_id == session_id)
        ).first()
        
        if session and session.reengagement_status == "none" and session.customer_phone:
            company = db.get(Company, company_id)
            if company:
                # Generate a soft re-engagement message
                re_msg = f"Hello! We noticed you were interested in a reservation at {company.name}. Would you like to pick up where you left off? Our elite staff is standing by to assist."
                print(f"🚀 [RE-ENGAGEMENT] Sending follow-up to {session.customer_phone}")
                # Use current running loop to send reply
                await send_whatsapp_reply(company, session.customer_phone, re_msg)
                session.reengagement_status = "completed"
                db.add(session)
                db.commit()
GAGEMENT] Sending follow-up to {session.customer_phone}")
                # Use current running loop to send reply
                await send_whatsapp_reply(company, session.customer_phone, re_msg)
                session.reengagement_status = "completed"
                db.add(session)
                db.commit()
