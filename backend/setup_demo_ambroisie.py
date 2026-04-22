
import sqlite3
import uuid

def add_ambroisie_demo():
    conn = sqlite3.connect('/home/keizinho/projects/chatbot_saas/backend/chatbot_v3.db')
    cursor = conn.cursor()

    # Data
    name = "L'Ambroisie"
    subdomain = "ambroisie"
    api_key = "ambroisie-demo-key-2026"
    primary_color = "#000080" # Royal Navy
    system_prompt = "You are the Digital Maître D' for L'Ambroisie, a 2-star Michelin restaurant in Paris. Your tone is aristocratic, extremely polite, and helpful. You must uphold the prestige of the house. You answer questions about the menu, reservations, and dress code based on the knowledge base."
    kb_path = "ambroisie_kb.txt"

    try:
        cursor.execute('''
            INSERT INTO company (name, subdomain, api_key, primary_color, system_prompt, knowledge_base, plan)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, subdomain, api_key, primary_color, system_prompt, kb_path, "enterprise"))
        conn.commit()
        print(f"Successfully added {name} to the database.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    add_ambroisie_demo()
