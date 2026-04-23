
import sqlite3
import os
from datetime import datetime, timedelta

def seed_orders():
    # Force path to match database.py (Project Root)
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'chatbot_v3.db'))
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get company ID for bistro
    cursor.execute("SELECT id FROM company WHERE subdomain='bistro'")
    res = cursor.fetchone()
    if not res:
        print("Company 'bistro' not found. Run setup_demo_bistro.py first.")
        return
    company_id = res[0]

    orders = [
        ("Jean Dupont", "2x Classic Burger, 1x Homemade Lemonade", 29.0, "TABLE 4"),
        ("Marie Curie", "1x Cheese Deluxe, 1x Sweet Potato Fries", 19.0, "TABLE 2"),
        ("Pierre Gasly", "3x Veggie Power, 3x Coca-Cola", 48.0, "DELIVERY: 12 Rue de Rivoli")
    ]

    for name, items, price, addr in orders:
        # Vary timestamps
        ts = (datetime.utcnow() - timedelta(minutes=15 * orders.index((name, items, price, addr)))).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO "order" (company_id, customer_name, items, total_price, delivery_address, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (company_id, name, items, price, addr, "confirmed", ts))

    conn.commit()
    print(f"Seeded {len(orders)} orders for Shinju Bistro.")
    conn.close()

if __name__ == "__main__":
    seed_orders()
