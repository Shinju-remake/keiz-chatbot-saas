import os
from sqlmodel import Session, select
from database import engine
from models import Company, FAQRule

def add_new_rules():
    with Session(engine) as session:
        # Get the demo company
        company = session.exec(select(Company).where(Company.name == "Keiz Bistro")).first()
        
        if company:
            # Check existing keywords to avoid duplicates
            existing_keywords = [rule.keyword for rule in session.exec(select(FAQRule).where(FAQRule.company_id == company.id)).all()]
            
            new_rules = []
            if "vibe" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="vibe", response="The vibe at Keiz Bistro is chic and cozy, with soft jazz and warm lighting. Perfect for dates!"))
            if "atmosphere" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="atmosphere", response="We offer a sophisticated yet relaxed atmosphere, ideal for both business lunches and romantic dinners."))
            if "recommend" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="recommend", response="I highly recommend our signature Coq au Vin or the Crème Brûlée—they are our most loved dishes!"))
            if "dessert" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="dessert", response="Our dessert menu features French classics like Tarte Tatin, Profiteroles, and our famous Chocolate Fondant."))
            if "menu" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="menu", response="You can view our full menu on our website at keizbistro.com/menu."))
            if "hello" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="hello", response="Hello! Welcome to Keiz Bistro. How can I help you today?"))
            if "hey" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="hey", response="Hey there! Welcome to Keiz Bistro. How can I help you?"))
            if "hi" not in existing_keywords:
                new_rules.append(FAQRule(company_id=company.id, keyword="hi", response="Hi! Welcome to Keiz Bistro. How can I assist you?"))
                
            if new_rules:
                session.add_all(new_rules)
                session.commit()
                print(f"Added {len(new_rules)} new rules.")
            else:
                print("Rules already exist.")

if __name__ == "__main__":
    add_new_rules()
