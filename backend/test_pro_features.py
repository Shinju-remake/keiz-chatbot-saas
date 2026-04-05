from fastapi.testclient import TestClient
from main import app
from sqlmodel import Session, select
from database import create_db_and_tables, engine
from models import Company, ChatLog, FAQRule
import pytest
import os

client = TestClient(app)

@pytest.fixture(name="session", scope="module")
def session_fixture():
    # Setup fresh database ONCE for the module
    if os.path.exists("chatbot_saas.db"):
        os.remove("chatbot_saas.db")
    create_db_and_tables()
    with Session(engine) as session:
        # Check if already seeded by on_startup
        if not session.exec(select(Company).where(Company.api_key == "test-api-key")).first():
            demo_company = Company(
                name="Keiz Bistro Test", 
                api_key="test-api-key",
                system_prompt="Test persona",
                whatsapp_verify_token="test_verify_token"
            )
            session.add(demo_company)
            session.commit()
        yield session

def test_whatsapp_verification_success(session: Session):
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token",
            "hub.challenge": "123456"
        }
    )
    assert response.status_code == 200
    assert response.json() == 123456

def test_whatsapp_verification_fail(session: Session):
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "123456"
        }
    )
    assert response.status_code == 403

def test_escalation_trigger(session: Session, capsys):
    response = client.post(
        "/chat",
        json={"message": "I need help from a human please!", "session_id": "pro-test-1"},
        headers={"x-api-key": "test-api-key"}
    )
    assert response.status_code == 200
    
    captured = capsys.readouterr()
    assert "DEBUG: Escalation Email sent" in captured.out
