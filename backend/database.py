import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

# FORCE SQLITE for Production Stability (Bypasses PostgreSQL connection errors)
DATABASE_URL = "sqlite:///./chatbot_v3.db"

# SQLite requires check_same_thread=False
connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
