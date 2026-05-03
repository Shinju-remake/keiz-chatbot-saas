import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Load existing .env
load_dotenv()

def test_email_dispatch():
    admin_email = os.getenv("ADMIN_EMAIL", "traore.m.2007@gmail.com")
    smtp_user = os.getenv("SMTP_USER", admin_email)
    smtp_pass = os.getenv("SMTP_PASSWORD")
    
    print(f"Testing SMTP for user: {smtp_user}")
    print(f"Target recipient: {admin_email}")
    
    if not smtp_pass:
        print("❌ Error: SMTP_PASSWORD is not set in .env")
        return

    subject = "🧪 ChatBoost SMTP Test"
    body = "This is a test email from the ChatBoost integration to verify the new App Password."
    
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = admin_email

    try:
        print("Connecting to smtp.gmail.com:465...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print("✅ SUCCESS: Test email sent successfully!")
    except Exception as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    test_email_dispatch()
