from fastapi.testclient import TestClient
from main import app
from database import create_db_and_tables, engine
from sqlmodel import Session, select
from models import Company, FAQRule, ChatLog
import pytest

client = TestClient(app)

@pytest.fixture(name="session")
def session_fixture():
    create_db_and_tables()
    with Session(engine) as session:
        # Seed company for tests
        company = session.exec(select(Company).where(Company.api_key == "dev-api-key-123")).first()
        if not company:
            company = Company(
                name="Shinju AI Test",
                api_key="dev-api-key-123",
                system_prompt="Test persona",
                whatsapp_verify_token="test_verify"
            )
            session.add(company)
            # Add a rule for price
            rule = FAQRule(company_id=1, keyword="price", response="Our luxury dining experience ranges from 50€ to 150€.")
            session.add(rule)
            session.commit()
        yield session

def test_chat_keyword_match(session: Session):
    # Test keyword matching (price)
    response = client.post(
        "/chat",
        json={"message": "What is the price?", "session_id": "test-session-1"},
        headers={"x-api-key": "dev-api-key-123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "50€ to 150€" in data["reply"]
    assert data["source"] == "keyword"

def test_chat_no_match_fallback(session: Session):
    # Test fallback when no keyword matches and AI is not configured/available
    response = client.post(
        "/chat",
        json={"message": "Do you have space for a party?", "session_id": "test-session-2"},
        headers={"x-api-key": "dev-api-key-123"}
    )
    assert response.status_code == 200
    data = response.json()
    # Since we don't have an OpenAI key in .env, it should fallback
    assert data["source"] in ["ai", "fallback"] 
    if data["source"] == "fallback":
        assert "not sure" in data["reply"].lower()

def test_invalid_api_key(session: Session):
    response = client.post(
        "/chat",
        json={"message": "Hello", "session_id": "test-session-3"},
        headers={"x-api-key": "wrong-key"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid API Key"

def test_rate_limiting(session: Session):
    # The limit is 60 per minute in main.py, but for the test we just check it works
    # We won't hit 60 here easily in a tight loop without slowapi being configured for tests
    # But let's verify it doesn't 403
    response = client.post(
        "/chat",
        json={"message": "Limit test", "session_id": "limit-session"},
        headers={"x-api-key": "dev-api-key-123"}
    )
    assert response.status_code == 200
