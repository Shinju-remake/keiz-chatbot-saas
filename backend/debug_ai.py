import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

print(f"Using Key: {api_key[:10]}...{api_key[-5:]}")

client = OpenAI(api_key=api_key)

try:
    print("Sending request to OpenAI...")
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": "Say hello"}],
        max_tokens=10
    )
    print("SUCCESS!")
    print(f"Reply: {response.choices[0].message.content}")
except Exception as e:
    print(f"CRITICAL ERROR: {e}")
