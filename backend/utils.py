from openai import OpenAI
from typing import List, Optional
from sqlmodel import Session, select
from backend.models import ChatLog, Company, FAQRule
import os
import httpx
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def process_message_v3(company: Company, session_id: str, user_msg: str, db: Session) -> dict:
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
    rules = db.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()
    for rule in sorted(rules, key=lambda r: len(r.keyword), reverse=True):
        if rule.keyword.lower() in user_input:
            reply = rule.response
            break
            
    # 2. AI Fallback
    if not reply:
        ai_reply = get_ai_response(company, session_id, user_msg, db)
        if ai_reply:
            reply = ai_reply
            source = "ai"
        else:
            reply = "I'm not sure about that. Try asking about 'price' or 'contact'."
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
    if "human" in user_input or "escalate" in user_input or "help" in user_input:
        send_escalation_email(company, user_msg, session_id)

    return {"reply": reply, "source": source}

def get_ai_response(company: Company, session_id: str, user_msg: str, db: Session) -> str:
    openai_key = company.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return None
    
    # Clean the key (remove newlines/spaces from Render env vars)
    openai_key = openai_key.strip()

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
        
        messages = [{"role": "system", "content": company.system_prompt}]
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

def send_escalation_email(company: Company, user_msg: str, session_id: str):
    """
    Pro Feature: Alert the business owner of a high-priority query.
    """
    owner_email = os.getenv("ADMIN_EMAIL", "traore.m.2007@gmail.com")
    msg = MIMEText(f"User is asking for human help!\n\nSession: {session_id}\nMessage: {user_msg}")
    msg["Subject"] = f"🚨 AI Escalation: {company.name}"
    msg["From"] = "keiz-ai@saas.com"
    msg["To"] = owner_email
    
    # In production, use a real SMTP service (SendGrid, Mailgun)
    # For now, we log the intent.
    print(f"DEBUG: Escalation Email sent to {owner_email} for {company.name}")
