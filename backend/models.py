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

    # Instagram DM Integration (Meta Graph API)
    instagram_page_id: Optional[str] = None
    instagram_access_token: Optional[str] = None

    # Autonomous Email Integration
    email_user: Optional[str] = None
    email_password: Optional[str] = None
    email_imap_server: Optional[str] = Field(default="imap.gmail.com")
    email_smtp_server: Optional[str] = Field(default="smtp.gmail.com")
    email_automation_enabled: bool = Field(default=False)

    rules: List["FAQRule"] = Relationship(back_populates="company")
    logs: List["ChatLog"] = Relationship(back_populates="company")
    reservations: List["Reservation"] = Relationship(back_populates="company")
    sessions: List["ChatSession"] = Relationship(back_populates="company")
    insights: List["TrendInsight"] = Relationship(back_populates="company")
    orders: List["Order"] = Relationship(back_populates="company")

class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    session_id: str = Field(index=True, unique=True)
    customer_phone: Optional[str] = None
    is_human_takeover: bool = Field(default=False)
    reengagement_status: str = Field(default="none") # none, pending, completed, failed
    last_active: datetime = Field(default_factory=datetime.now)
    
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
    timestamp: datetime = Field(default_factory=datetime.now)

    company: "Company" = Relationship(back_populates="reservations")

class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    customer_name: str
    items: str 
    total_price: float = Field(default=0.0)
    delivery_address: Optional[str] = None
    status: str = Field(default="confirmed")
    timestamp: datetime = Field(default_factory=datetime.now)

    company: Company = Relationship(back_populates="orders")

class ChatLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    session_id: str = Field(index=True)  
    user_msg: str
    bot_reply: str
    source: str 
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # Feedback Loop / Human-in-the-loop
    confidence_score: float = Field(default=1.0)
    needs_review: bool = Field(default=False)
    reviewed: bool = Field(default=False)
    was_corrected: bool = Field(default=False)
    corrected_reply: Optional[str] = None

    company: Company = Relationship(back_populates="logs")

class TrendInsight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    topic: str
    frequency: int
    insight_text: str
    suggested_rule: Optional[str] = None
    status: str = Field(default="unread") # unread, dismissed, applied
    timestamp: datetime = Field(default_factory=datetime.now)

    company: Company = Relationship(back_populates="insights")
