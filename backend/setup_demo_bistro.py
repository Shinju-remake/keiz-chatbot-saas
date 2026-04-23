
import sqlite3
import uuid
import os

def add_bistro_demo():
    # Force path to match database.py (Project Root)
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'chatbot_v3.db'))
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Data
    name = "Shinju Bistro"
    subdomain = "bistro"
    api_key = "bistro-demo-2026"
    primary_color = "#BB00FF" # Shinju Neon Purple
    system_prompt = """You are the AI Waiter for Shinju Bistro. Your goal is to take orders quickly and up-sell.
CONSTRAINTS:
1. Be friendly but efficient.
2. If someone orders a burger, always ask if they want fries for 4€.
3. Once the order is complete, confirm the items and total price.
4. Use [ORDER_TOOL_CALL] with JSON arguments {"name": "...", "items": "...", "address": "DINE-IN", "total_price": ...} when the customer confirms they are done.
"""
    menu = """
MENU:
- Classic Burger: 12€ (Beef, lettuce, tomato, house sauce)
- Cheese Deluxe: 14€ (Classic + double cheddar and caramelized onions)
- Veggie Power: 13€ (Plant-based patty, avocado, sprouts)
- French Fries: 4€
- Sweet Potato Fries: 5€
- Craft Beer: 6€
- Homemade Lemonade: 5€
- Coca-Cola: 3€
"""

    try:
        cursor.execute('''
            INSERT INTO company (name, subdomain, api_key, primary_color, system_prompt, knowledge_base, plan, email_automation_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, subdomain, api_key, primary_color, system_prompt, menu, "pro", 0))
        conn.commit()
        print(f"Successfully added {name} to the database.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    add_bistro_demo()
