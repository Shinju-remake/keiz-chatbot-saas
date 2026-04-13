import os
from sqlmodel import SQLModel, Session, create_engine, select
from models import Company, FAQRule, ChatLog
from dotenv import load_dotenv

load_dotenv()

# SQLite Source
SQLITE_URL = "sqlite:///./chatbot_saas.db"
sqlite_engine = create_engine(SQLITE_URL)

# PostgreSQL Destination
POSTGRES_URL = "postgresql://keiz:shinju2026@localhost/chatbot_db"
postgres_engine = create_engine(POSTGRES_URL)

def migrate():
    print("🚀 Starting migration from SQLite to PostgreSQL...")
    
    # Create tables in PostgreSQL
    print("📦 Creating tables in PostgreSQL...")
    SQLModel.metadata.create_all(postgres_engine)
    
    with Session(sqlite_engine) as sqlite_session:
        with Session(postgres_engine) as postgres_session:
            # 1. Migrate Companies
            print("🏢 Migrating Companies...")
            companies = sqlite_session.exec(select(Company)).all()
            for company in companies:
                sqlite_session.expunge(company) # Detach from SQLite session
                postgres_session.add(company)
            postgres_session.commit()
            
            # 2. Migrate FAQ Rules
            print("📜 Migrating FAQ Rules...")
            rules = sqlite_session.exec(select(FAQRule)).all()
            for rule in rules:
                sqlite_session.expunge(rule)
                postgres_session.add(rule)
            postgres_session.commit()
            
            # 3. Migrate Chat Logs
            print("💬 Migrating Chat Logs...")
            logs = sqlite_session.exec(select(ChatLog)).all()
            for log in logs:
                sqlite_session.expunge(log)
                postgres_session.add(log)
            postgres_session.commit()
            
    print("✅ Migration complete! Shinju AI is now powered by PostgreSQL.")

if __name__ == "__main__":
    migrate()
