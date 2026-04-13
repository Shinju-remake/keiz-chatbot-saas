from openai import OpenAI
from typing import List, Optional
from sqlmodel import Session, select
try:
    from models import ChatLog, Company, FAQRule
except ImportError:
    from .models import ChatLog, Company, FAQRule
import os
import httpx
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def process_message_v3(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> dict:
    """
    The Omni-Engine Brain:
    1. Check Keywords (Zero-cost)
    2. Check AI (GPT-5.4 Nano)
    3. Final Fallback
    """
    user_input = user_msg.lower()
    reply = None
    source = "keyword"
    
    # 1. Keywords
    # Note: For now, keywords are language-agnostic. 
    # In a full Pro version, we'd have FAQRule.language.
    rules = db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()
    for rule in sorted(rules, key=lambda r: len(r.keyword), reverse=True):
        if rule.keyword.lower() in user_input:
            reply = rule.response
            break
            
    # 2. AI Fallback (Handles translation if needed)
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
    
    # Check for escalation triggers (Pro feature)
    escalation_words = ["human", "escalate", "help", "aide", "humain", "urgent", "problem", "problème", "reservation", "book"]
    if any(word in user_input for word in escalation_words):
        import asyncio
        # Run automation in background to avoid slowing down the chat reply
        asyncio.create_task(trigger_pro_automation(company, user_msg, session_id))

    return {"reply": reply, "source": source}

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session, language: str = "en") -> str:
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return None
    
    # Clean the key aggressively (remove ALL spaces and newlines from the middle)
    openai_key = openai_key.replace(" ", "").replace("\n", "").replace("\r", "").strip()

    try:
        # 2026 Render Fix: Force IPv4 to avoid handshake timeouts with OpenAI
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        http_client = httpx.Client(transport=transport)
        
        client = OpenAI(
            api_key=openai_key, 
            timeout=60.0,
            http_client=http_client
        )
        history = db.exec(
            select(ChatLog)
            .where(ChatLog.company_id == company.id)
            .where(ChatLog.session_id == session_id)
            .order_by(ChatLog.timestamp.desc())
            .limit(6)
        ).all()
        
        # Add language instruction to system prompt
        lang_names = {"en": "English", "fr": "French", "es": "Spanish"}
        target_lang = lang_names.get(language, "English")
        
        full_system_prompt = company.system_prompt + f" IMPORTANT: You MUST respond in {target_lang}."
        
        messages = [{"role": "system", "content": full_system_prompt}]
        for h in reversed(history):
            messages.append({"role": "user", "content": h.user_msg})
            messages.append({"role": "assistant", "content": h.bot_reply})
        messages.append({"role": "user", "content": user_msg})
        
        response = client.chat.completions.create(
            model="gpt-5.4-nano", # Modern efficiency
            messages=messages,
            max_completion_tokens=150,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OPENAI CLOUD ERROR: {e}")
        return None

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
