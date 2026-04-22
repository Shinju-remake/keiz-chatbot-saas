## Update Wed 22 Apr 13:52:58 BST 2026 - Shinju AI Agency Enhancements
- Replaced Regex reservation parsing with OpenAI Function Calling.
- Added Meta Webhook Signature Verification (X-Hub-Signature-256).
- Integrated Voice Notes (Whisper) and OCR (GPT-4o-Vision) support for incoming WhatsApp Media.
- Introduced Secret Encryption at rest for Company API keys using Fernet.
- Transitioned from asyncio.create_task to reliable fastapi.BackgroundTasks for background processes.
