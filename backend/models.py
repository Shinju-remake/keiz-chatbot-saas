from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional
from datetime import datetime
import uuid

class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    # Each company gets a unique API key for the widget
    api_key: str = Field(default_factory=lambda: str(uuid.uuid4()), index=True, unique=True)
    # Company can provide their own OpenAI key, or use the SaaS global key
    openai_api_key: Optional[str] = None
    # Custom persona for the AI
    system_prompt: str = Field(default="You are a helpful, polite customer support assistant.")
    
    # WhatsApp Pro Integration (Meta Cloud API)
    whatsapp_phone_id: Optional[str] = None
    whatsapp_verify_token: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    whatsapp_access_token: Optional[str] = None

    rules: List["FAQRule"] = Relationship(back_populates="company")
    logs: List["ChatLog"] = Relationship(back_populates="company")

class FAQRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    keyword: str
    response: str
    
    company: Company = Relationship(back_populates="rules")

class ChatLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    session_id: str = Field(index=True)  # To track individual user conversations
    user_msg: str
    bot_reply: str
    source: str # 'keyword', 'ai', or 'fallback'
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    company: Company = Relationship(back_populates="logs")
