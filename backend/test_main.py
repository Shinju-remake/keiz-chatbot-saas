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
    assert "€10 to €50" in data["reply"]
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
    # The limit is 5 per minute in main.py
    for i in range(5):
        client.post(
            "/chat",
            json={"message": f"Message {i}", "session_id": "limit-session"},
            headers={"x-api-key": "dev-api-key-123"}
        )
    
    response = client.post(
        "/chat",
        json={"message": "Sixth message", "session_id": "limit-session"},
        headers={"x-api-key": "dev-api-key-123"}
    )
    assert response.status_code == 429
