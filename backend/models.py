from sqlmodel import SQLModel, Field, Relationship
from typing import List, Optional
from datetime import datetime
import uuid

class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    subdomain: Optional[str] = Field(default=None, index=True, unique=True)
    
    # Each company gets a unique API key for the widget
    api_key: str = Field(default_factory=lambda: str(uuid.uuid4()), index=True, unique=True)
    
    # Custom Branding
    primary_color: str = Field(default="#BB00FF")
    logo_url: Optional[str] = None
    
    # RAG / Knowledge Base
    knowledge_base: Optional[str] = Field(default=None) 
    
    # AI Persona
    openai_api_key: Optional[str] = None
    system_prompt: str = Field(default="You are a helpful, polite customer support assistant.")
    
    # SaaS Billing (Stripe)
    plan: str = Field(default="free") 
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None

    # WhatsApp Pro Integration (Meta Cloud API)
    whatsapp_phone_id: Optional[str] = None
    whatsapp_verify_token: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    whatsapp_access_token: Optional[str] = None

    rules: List["FAQRule"] = Relationship(back_populates="company")
    logs: List["ChatLog"] = Relationship(back_populates="company")
    reservations: List["Reservation"] = Relationship(back_populates="company")
    sessions: List["ChatSession"] = Relationship(back_populates="company")

class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    session_id: str = Field(index=True, unique=True)
    is_human_takeover: bool = Field(default=False)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    
    company: Company = Relationship(back_populates="sessions")

class FAQRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    keyword: str
    response: str
    
    company: Company = Relationship(back_populates="rules")

class Reservation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    customer_name: str
    date_time: str 
    pax: int
    status: str = Field(default="pending") 
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    company: "Company" = Relationship(back_populates="reservations")

class ChatLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    session_id: str = Field(index=True)  
    user_msg: str
    bot_reply: str
    source: str 
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    company: Company = Relationship(back_populates="logs")
