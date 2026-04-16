from openai import OpenAI
from typing import List, Optional
from sqlmodel import Session, select
try:
    from models import ChatLog, Company, FAQRule, Reservation
except ImportError:
    from .models import ChatLog, Company, FAQRule, Reservation
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
    3. Check AI (GPT-4o Mini)
    """
    
    # [NEW] Human Takeover Check
    session_state = db.exec(
        select(ChatSession).where(ChatSession.company_id == company.id, ChatSession.session_id == session_id)
    ).first()
    
    if session_state and session_state.is_human_takeover:
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
    log_entry = ChatLog(
        company_id=company.id, 
        session_id=session_id, 
        user_msg=user_msg, 
        bot_reply=reply, 
        source=source,
        timestamp=datetime.utcnow()
    )
    db.add(log_entry)
    db.commit()
    
    # [RESERVATION SYSTEM] Parse and save if successful
    if reply and "[RESERVATION_SUCCESS]" in reply:
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

    return {"reply": reply, "source": source}

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
        history = db.exec(
            select(ChatLog)
            .where(ChatLog.company_id == company.id)
            .where(ChatLog.session_id == session_id)
            .order_by(ChatLog.timestamp.desc())
            .limit(6)
        ).all()
        
        lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
        target_lang = lang_names.get(language, "English")
        
        # RAG / Knowledge Base Injection
        kb_context = f"\nCOMPANY KNOWLEDGE BASE:\n{company.knowledge_base}\n" if company.knowledge_base else ""
        
        full_system_prompt = (
            company.system_prompt + 
            kb_context +
            f"\nIMPORTANT: You MUST respond in {target_lang}. "
            "You are an elite concierge. Your goal is to collect: Name, Date/Time, and Pax for reservations/orders. "
            "CRITICAL: If the user provides some of this information, do NOT ask for it again. "
            "Instead, acknowledge what you have and elegantly ask for only the MISSING details. "
            "When listing missing requirements, put each on its own NEW LINE using a dash. "
            "Highlight missing questions with **double asterisks**. "
            "Once ALL details are gathered, confirm the summary and say exactly: [RESERVATION_SUCCESS]. "
            "Immediately after [RESERVATION_SUCCESS], append the hidden data block: "
            "[DATA]{\"name\": \"Name\", \"date\": \"Date\", \"pax\": 4}[/DATA]"
        )
        
        messages = [{"role": "system", "content": full_system_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        messages.append({"role": "user", "content": user_msg})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini", # Modern, fast, and high-availability
            messages=messages,
            max_completion_tokens=250,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
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
    Pro Tier: Trigger Make.com Webhook for lead tracking and human escalation.
    """
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
