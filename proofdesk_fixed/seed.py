"""
Phase 1 seed: creates the three baseline demo accounts.
Run with: python3 seed.py
Safe to re-run - skips users that already exist.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from db import get_db, query_one, execute
from werkzeug.security import generate_password_hash
from utils.helpers import now_iso

DEMO_PASSWORD = "Demo@1234"

app = create_app()

with app.app_context():
    users = [
        ("Alastair Fernandes", "customer@proofdesk.demo", "9876543210", "customer"),
        ("Priya Sharma", "provider@proofdesk.demo", "9876500000", "provider"),
        ("Platform Admin", "admin@proofdesk.demo", "9876511111", "admin"),
    ]
    for name, email, phone, role in users:
        existing = query_one("SELECT id FROM users WHERE email = ?", (email,))
        if existing:
            print(f"Skip (exists): {email}")
            continue
        uid = execute(
            """INSERT INTO users (name, email, phone, password_hash, role, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (name, email, phone, generate_password_hash(DEMO_PASSWORD), role, now_iso()),
        )
        print(f"Created {role}: {email} (id={uid})")
        if role == "provider":
            pid = execute(
                """INSERT INTO service_providers
                   (owner_user_id, business_name, category, description, contact_phone,
                    address, operating_hours, verification_status, created_at)
                   VALUES (?, 'TechFix Repair Center', 'Laptop/Desktop',
                           'Authorized laptop and desktop repair with certified technicians.',
                           ?, '221B Residency Road, Bengaluru', 'Mon-Sat 10:00-19:00', 'VERIFIED', ?)""",
                (uid, phone, now_iso()),
            )
            print(f"  -> provider profile id={pid} (VERIFIED)")

    print("\nDemo login credentials (password for all):", DEMO_PASSWORD)
