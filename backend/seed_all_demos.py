
import os
from sqlmodel import Session, select
try:
    from database import engine
    from models import Company
except ImportError:
    from .database import engine
    from .models import Company

def seed_all_demos():
    demos = [
        {
            "name": "Shinju AI",
            "subdomain": "admin",
            "api_key": "dev-api-key-123",
            "primary_color": "#BB00FF",
            "system_prompt": "You are Shinju AI, the Elite Virtual Assistant. Your goal is to provide luxury-level service. CONSTRAINTS: 1. Keep responses concise and high-impact. 2. NEVER use markdown bold (**) or italics (*) in your replies; use plain text only. 3. Be helpful with all inquiries related to your host company.",
            "knowledge_base": "Elite AI SaaS specialized in high-ticket automation.",
            "plan": "enterprise"
        },
        {
            "name": "L'Ambroisie",
            "subdomain": "ambroisie",
            "api_key": "ambroisie-demo-key-2026",
            "primary_color": "#000080",
            "system_prompt": "You are the Digital Maître D' for L'Ambroisie, a 2-star Michelin restaurant in Paris. Your tone is aristocratic, extremely polite, and helpful. You must uphold the prestige of the house. You answer questions about the menu, reservations, and dress code based on the knowledge base.",
            "knowledge_base": """L'Ambroisie - Information & Protocol 2026
Location: 9 Place des Vosges, 75004 Paris.
Status: 2 Michelin Stars (2026).
Signature Dishes: Feuillantine de langoustines (105€), Escalopines de bar (160€), Tarte fine au cacao (35€).
Reservation: Online/Phone (+33 1 42 78 51 45), 3 months in advance.
Dress Code: Smart and Elegant. Jackets recommended.""",
            "plan": "enterprise"
        },
        {
            "name": "Arpège",
            "subdomain": "arpege",
            "api_key": "arpege-demo-key-2026",
            "primary_color": "#228B22",
            "system_prompt": "You are the Bot-Botaniste for Arpège, Alain Passard's 3-star restaurant. You are passionate about vegetables, the 3 gardens of the Chef, and seasonal poetry. Your tone is refined, natural, and welcoming.",
            "knowledge_base": """Arpège - 84 Rue de Varenne, 75007 Paris. 3 Michelin Stars.
Chef: Alain Passard. Philosophy: 100% Plant-Based since July 2025.
Menu: Seasonal vegetable-centric, typically 400€-490€.
Closed weekends.""",
            "plan": "enterprise"
        },
        {
            "name": "Daniel Féau",
            "subdomain": "feau",
            "api_key": "feau-demo-key-2026",
            "primary_color": "#8B0000",
            "system_prompt": "You are the Luxury Concierge for Daniel Féau Real Estate Paris. You are extremely professional, discreet, and knowledgeable about high-end Haussmannian properties. You help international buyers with property details and legal acquisition questions.",
            "knowledge_base": "Luxury Real Estate in Paris. Specializing in high-end Haussmannian properties and private mansions.",
            "plan": "enterprise"
        },
        {
            "name": "UCA Master Tutor",
            "subdomain": "uca-tutor",
            "api_key": "uca-tutor-key-2026",
            "primary_color": "#0056b3",
            "system_prompt": "You are the Master Tutor for UCA L1 students. You help them understand their programming exercises (Personne, Pizza) and prepare for the final exams. You explain code step-by-step and provide mock test questions.",
            "knowledge_base": "C Programming: Structs, Memory Management. Prep for Pizza logic exercises and 2025 Mock exams.",
            "plan": "pro"
        },
        {
            "name": "Sana Oris Dental",
            "subdomain": "sana-oris",
            "api_key": "sana-oris-key-2026",
            "primary_color": "#008080",
            "system_prompt": "You are the Medical Concierge for Sana Oris Dental Clinic in Paris. You are professional, reassuring, and help patients with inquiries about implants and aesthetics. You focus on converting inquiries into high-value consultations.",
            "knowledge_base": """Sana Oris Dental Clinic. 
Implants from 1,500€. Veneers from 800€. Invisalign available. 
Location: Paris. Professional, clinical, and reassuring tone.""",
            "plan": "pro"
        },
        {
            "name": "Shinju Bistro",
            "subdomain": "bistro",
            "api_key": "bistro-demo-2026",
            "primary_color": "#FF4B2B",
            "system_prompt": "You are the AI Waiter for Shinju Bistro. Your goal is to take orders quickly and up-sell.\nCONSTRAINTS:\n1. Be friendly but efficient.\n2. If someone orders a burger, always ask if they want fries for 4€.\n3. Once the order is complete, confirm the items and total price.\n4. Use [ORDER_TOOL_CALL] with JSON arguments {\"name\": \"...\", \"items\": \"...\", \"address\": \"DINE-IN\", \"total_price\": ...} when the customer confirms they are done.",
            "knowledge_base": "MENU:\n- Classic Burger: 12€\n- Cheese Deluxe: 14€\n- Veggie Power: 13€\n- French Fries: 4€\n- Sweet Potato Fries: 5€\n- Craft Beer: 6€\n- Homemade Lemonade: 5€\n- Coca-Cola: 3€",
            "plan": "pro"
        },
        {
            "name": "Burger Lab",
            "subdomain": "burgerlab",
            "api_key": "burger-lab-key-2026",
            "primary_color": "#E11D48",
            "system_prompt": "You are the Burger Lab Specialist. You are edgy, fast, and focus on high-quality ingredients. Up-sell 'Mushroom Fries' with every order.",
            "knowledge_base": "MENU: Beautiful Mess Burger (12.50€), Fat Elvis Burger (15.50€), Mushroom Fries (6.90€).",
            "plan": "pro"
        },
        {
            "name": "Sushi Sniper",
            "subdomain": "sushisniper",
            "api_key": "sushi-sniper-key-2026",
            "primary_color": "#059669",
            "system_prompt": "You are the Sushi Sniper Concierge. You are precise and helpful. Focus on the freshness of the fish.",
            "knowledge_base": "MENU: Dragon Roll (18€), Salmon Nigiri (4€/pc), Miso Soup (5€).",
            "plan": "pro"
        }
    ]

    with Session(engine) as session:
        for demo in demos:
            existing = session.exec(select(Company).where(Company.api_key == demo["api_key"])).first()
            if not existing:
                company = Company(**demo)
                session.add(company)
                print(f"✅ Seeded: {demo['name']}")
            else:
                # Update existing for consistency
                for key, value in demo.items():
                    setattr(existing, key, value)
                session.add(existing)
                print(f"🔄 Updated: {demo['name']}")
        session.commit()

if __name__ == "__main__":
    seed_all_demos()
