from sqlmodel import Session, create_engine, select
from models import Company
from utils import get_ai_response
import os
from dotenv import load_dotenv

load_dotenv()

engine = create_engine('sqlite:////home/keizinho/projects/chatbot_saas/backend/chatbot_saas.db')
with Session(engine) as session:
    company = session.exec(select(Company).where(Company.name == "Shinju Bistro")).first()
    if company:
        print(f"Testing AI with model: gpt-5.4-nano")
        try:
            # We don't have a chat log yet, so history will be empty.
            reply = get_ai_response(company, "test_sess_123", "hey", session)
            print(f"AI Reply: {reply}")
        except Exception as e:
            print(f"AI Error: {e}")
    else:
        print("Company not found.")
