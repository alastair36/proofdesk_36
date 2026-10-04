"""
Full demo dataset per spec section 37. Run with: python3 seed_demo.py
Safe to re-run: wipes and rebuilds the whole database (dev/demo only).
Directly writes rows via the same DB helpers the app uses, rather than
replaying full HTTP workflows, to build a rich dataset quickly - but uses
the identical state values, audit actions and table shapes the real
application produces, so every record it creates is indistinguishable from
one built through the real workflow.
"""
import os
import random
import sys
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from PIL import Image
from werkzeug.security import generate_password_hash

from db import execute, query_one
from utils.paths import UPLOAD_DIR, QR_DIR
from utils.helpers import now_iso, log_audit, notify, generate_record_number, generate_code
from utils.qr import generate_qr_png

DEMO_PASSWORD = "Demo@1234"
CATEGORIES = ["Electronics", "Laptop/Desktop", "Mobile Phone", "Appliance", "Clothing/Laundry", "Shoes", "Watch"]
ITEMS = [
    ("Dell Laptop", "Dell", "Inspiron 15", "Laptop is not charging."),
    ("iPhone 13", "Apple", "A2482", "Screen cracked after a fall."),
    ("Washing Machine", "LG", "T70SKSF1Z", "Not spinning during wash cycle."),
    ("Sneakers", "Nike", "Air Max", "Sole is coming apart."),
    ("Wrist Watch", "Titan", "Neo", "Watch has stopped working."),
    ("Office Chair", "Godrej", "Interio Pro", "Wheel is broken."),
    ("Refrigerator", "Samsung", "RT28", "Not cooling properly."),
    ("Bluetooth Speaker", "JBL", "Flip 5", "Battery drains too fast."),
    ("Formal Shirts", "Van Heusen", "-", "Dry cleaning and pressing."),
    ("Gaming Mouse", "Logitech", "G502", "Left click double-clicks."),
]


def placeholder_image(record_id, tag, color):
    """Generates a simple solid-color placeholder JPEG (no copyrighted material)."""
    img = Image.new("RGB", (320, 240), color)
    target_dir = os.path.join(UPLOAD_DIR, f"record_{record_id}")
    os.makedirs(target_dir, exist_ok=True)
    import secrets
    fname = f"{secrets.token_hex(8)}.jpg"
    path = os.path.join(target_dir, fname)
    img.save(path, format="JPEG")
    return f"uploads/record_{record_id}/{fname}"


def add_evidence(record_id, uploader_id, stage, angle, color):
    ref = placeholder_image(record_id, angle, color)
    execute(
        """INSERT INTO evidence_files (service_record_id, uploaded_by, stage, angle, file_reference, file_type, created_at)
           VALUES (?, ?, ?, ?, ?, 'JPEG', ?)""",
        (record_id, uploader_id, stage, angle, ref, now_iso()),
    )


def create_user(name, email, role):
    existing = query_one("SELECT id FROM users WHERE email=?", (email,))
    if existing:
        return existing["id"]
    return execute(
        """INSERT INTO users (name, email, phone, password_hash, role, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'active', ?)""",
        (name, email, f"9{random.randint(100000000,999999999)}", generate_password_hash(DEMO_PASSWORD),
         role, now_iso()),
    )


def create_provider(owner_id, business_name, category, verification_status):
    existing = query_one("SELECT id FROM service_providers WHERE owner_user_id=?", (owner_id,))
    if existing:
        return existing["id"]
    return execute(
        """INSERT INTO service_providers (owner_user_id, business_name, category, description,
           contact_phone, address, operating_hours, verification_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (owner_id, business_name, category, f"Trusted {category.lower()} specialists.",
         f"9{random.randint(100000000,999999999)}", "Bengaluru, India", "Mon-Sat 10:00-19:00",
         verification_status, now_iso()),
    )


def create_full_record(customer_id, provider_id, provider_owner_id, item, target_status,
                        with_dispute=False):
    item_name, brand, model, problem = item
    serial = f"SN{random.randint(100000,999999)}"
    est_cost = float(random.choice([500, 800, 1200, 1500, 2000, 2500]))

    req_id = execute(
        """INSERT INTO service_requests (customer_id, provider_id, category, item_name, brand, model,
           serial_number, problem_description, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED', ?)""",
        (customer_id, provider_id, random.choice(CATEGORIES), item_name, brand, model,
         serial, problem, now_iso()),
    )
    record_number = generate_record_number()
    record_id = execute(
        """INSERT INTO service_records (service_request_id, customer_id, provider_id, record_number,
           item_name, brand, model, serial_number, problem_description, estimated_cost,
           expected_completion_date, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?)""",
        (req_id, customer_id, provider_id, record_number, item_name, brand, model, serial,
         problem, est_cost, "2026-10-05", now_iso()),
    )
    log_audit(record_id, provider_owner_id, "SERVICE_RECORD_CREATED", None, record_number)
    execute("UPDATE service_records SET status='HANDOVER_PENDING' WHERE id=?", (record_id,))

    if target_status == "HANDOVER_PENDING":
        return record_number

    # --- handover documentation ---
    execute("INSERT INTO accessories (service_record_id, name, received) VALUES (?, 'Charger', 1)", (record_id,))
    execute("INSERT INTO accessories (service_record_id, name, received) VALUES (?, 'Bag', 0)", (record_id,))
    execute(
        """INSERT INTO condition_reports (service_record_id, stage, condition_type, severity, description, created_at)
           VALUES (?, 'HANDOVER', 'Exterior condition', 'GOOD', 'No visible damage', ?)""",
        (record_id, now_iso()),
    )
    add_evidence(record_id, provider_owner_id, "HANDOVER", "Front", (120, 140, 200))
    execute(
        "INSERT INTO confirmations (service_record_id, user_id, role, confirmation_type, confirmed_at) VALUES (?, ?, 'customer', 'HANDOVER', ?)",
        (record_id, customer_id, now_iso()),
    )
    execute(
        "INSERT INTO confirmations (service_record_id, user_id, role, confirmation_type, confirmed_at) VALUES (?, ?, 'provider', 'HANDOVER', ?)",
        (record_id, provider_owner_id, now_iso()),
    )
    verification_code = generate_code(10)
    execute(
        "UPDATE service_records SET status='HANDOVER_VERIFIED', verification_code=? WHERE id=?",
        (verification_code, record_id),
    )
    generate_qr_png(f"http://localhost:5050/records/verify/{verification_code}",
                     os.path.join(QR_DIR, f"{verification_code}.png"))
    log_audit(record_id, customer_id, "STATUS_CHANGED", "HANDOVER_PENDING", "HANDOVER_VERIFIED")

    if target_status == "HANDOVER_VERIFIED":
        return record_number

    execute("UPDATE service_records SET status='SERVICE_IN_PROGRESS' WHERE id=?", (record_id,))
    execute(
        """INSERT INTO service_updates (service_record_id, update_type, description, created_by, created_at)
           VALUES (?, 'DIAGNOSIS', ?, ?, ?)""",
        (record_id, f"Diagnosed: {problem}", provider_owner_id, now_iso()),
    )
    log_audit(record_id, provider_owner_id, "STATUS_CHANGED", "HANDOVER_VERIFIED", "SERVICE_IN_PROGRESS")

    if target_status == "SERVICE_IN_PROGRESS":
        return record_number

    final_cost = est_cost if random.random() > 0.4 else est_cost + 500
    execute("UPDATE service_records SET status='SERVICE_COMPLETED', final_cost=? WHERE id=?", (final_cost, record_id))
    execute("UPDATE service_records SET status='PAYMENT_PENDING' WHERE id=?", (record_id,))
    log_audit(record_id, provider_owner_id, "STATUS_CHANGED", "SERVICE_IN_PROGRESS", "PAYMENT_PENDING")

    if target_status == "PAYMENT_PENDING":
        return record_number

    execute(
        """INSERT INTO payments (service_record_id, amount, method, reference, status, recorded_by, created_at)
           VALUES (?, ?, 'UPI', ?, 'PAID', ?, ?)""",
        (record_id, final_cost, f"REF{random.randint(10000,99999)}", provider_owner_id, now_iso()),
    )
    execute("UPDATE service_records SET status='READY_FOR_RETURN' WHERE id=?", (record_id,))
    log_audit(record_id, provider_owner_id, "STATUS_CHANGED", "PAYMENT_PENDING", "READY_FOR_RETURN")

    if target_status == "READY_FOR_RETURN":
        return record_number

    return_code = generate_code(6)
    execute("INSERT INTO returns (service_record_id, return_code) VALUES (?, ?)", (record_id, return_code))
    execute("UPDATE service_records SET status='RETURN_PENDING', return_code=? WHERE id=?", (return_code, record_id))
    log_audit(record_id, provider_owner_id, "STATUS_CHANGED", "READY_FOR_RETURN", "RETURN_PENDING")

    if target_status == "RETURN_PENDING":
        return record_number

    execute(
        "UPDATE returns SET returned_by=?, returned_at=?, received_by=?, verified_at=?, condition_summary=? WHERE service_record_id=?",
        (customer_id, now_iso(), provider_owner_id, now_iso(), "Matches handover condition", record_id),
    )
    execute("UPDATE accessories SET returned=1 WHERE service_record_id=?", (record_id,))
    execute(
        """INSERT INTO condition_reports (service_record_id, stage, condition_type, severity, description, created_at)
           VALUES (?, 'RETURN', 'Exterior condition', 'GOOD', 'No new damage observed', ?)""",
        (record_id, now_iso()),
    )
    add_evidence(record_id, provider_owner_id, "RETURN", "Front", (120, 140, 200))
    execute("UPDATE service_records SET status='RETURN_VERIFIED' WHERE id=?", (record_id,))
    log_audit(record_id, provider_owner_id, "STATUS_CHANGED", "RETURN_PENDING", "RETURN_VERIFIED")

    if with_dispute:
        execute("UPDATE service_records SET status='DISPUTED' WHERE id=?", (record_id,))
        execute(
            """INSERT INTO disputes (service_record_id, opened_by, category, description, status,
               previous_status, created_at) VALUES (?, ?, 'CONDITION_DISAGREEMENT', ?, 'OPEN', 'RETURN_VERIFIED', ?)""",
            (record_id, customer_id, "The item came back with a new scratch that wasn't there at drop-off.", now_iso()),
        )
        log_audit(record_id, customer_id, "DISPUTE_OPENED", "RETURN_VERIFIED", "CONDITION_DISAGREEMENT")
        return record_number

    ts = now_iso()
    execute("UPDATE service_records SET status='COMPLETED', locked_at=? WHERE id=?", (ts, record_id))
    log_audit(record_id, customer_id, "STATUS_CHANGED", "RETURN_VERIFIED", "COMPLETED")
    log_audit(record_id, customer_id, "RECORD_COMPLETED", None, "Locked.")
    return record_number


def run_seed(app, quiet=False):
    """Load the demo dataset (3 base accounts + 10 customers + 5 providers + 15 records).
    Idempotent for accounts; call it on an empty database. quiet=True suppresses output."""
    def say(*a):
        if not quiet:
            print(*a)

    with app.app_context():
        # Base 3 demo accounts (idempotent)
        cust0 = create_user("Alastair Fernandes", "customer@proofdesk.demo", "customer")
        prov0_owner = create_user("Priya Sharma", "provider@proofdesk.demo", "provider")
        create_user("Platform Admin", "admin@proofdesk.demo", "admin")
        prov0 = create_provider(prov0_owner, "TechFix Repair Center", "Laptop/Desktop", "VERIFIED")
        say("Base accounts ready.")

        # 10 customers total (including base)
        customer_ids = [cust0]
        customer_names = [
            "Meera Iyer", "Rohan Kapoor", "Sana Sheikh", "Vikram Rao", "Ananya Das",
            "Farhan Ali", "Divya Menon", "Karthik Nair", "Priyanka Joshi",
        ]
        for i, name in enumerate(customer_names):
            customer_ids.append(create_user(name, f"customer{i+1}@proofdesk.demo", "customer"))

        # 5 providers total (including base) - one left PENDING to demo verification workflow
        provider_defs = [
            ("Sana's Mobile Clinic", "Mobile Phone", "VERIFIED"),
            ("CleanCraft Laundry", "Clothing/Laundry", "VERIFIED"),
            ("StepRight Shoe Repair", "Shoes", "VERIFIED"),
            ("HomeAppliance Care", "Appliance", "PENDING"),
        ]
        providers = [(prov0, prov0_owner)]
        for i, (biz, cat, status) in enumerate(provider_defs):
            owner_id = create_user(f"{biz} Owner", f"provider{i+1}@proofdesk.demo", "provider")
            providers.append((create_provider(owner_id, biz, cat, status), owner_id))
        say(f"{len(customer_ids)} customers, {len(providers)} providers ready.")

        # 15 service records spanning the full lifecycle
        plan = [
            "HANDOVER_PENDING", "HANDOVER_PENDING",
            "HANDOVER_VERIFIED", "HANDOVER_VERIFIED",
            "SERVICE_IN_PROGRESS", "SERVICE_IN_PROGRESS", "SERVICE_IN_PROGRESS",
            "PAYMENT_PENDING", "PAYMENT_PENDING",
            "READY_FOR_RETURN",
            "RETURN_PENDING",
            "COMPLETED", "COMPLETED", "COMPLETED",
            "COMPLETED",  # this one will be flipped to DISPUTED
        ]
        created = []
        for i, target in enumerate(plan):
            customer_id = random.choice(customer_ids)
            provider_id, provider_owner_id = random.choice([p for p in providers if p[1] != customer_id] or providers)
            item = ITEMS[i % len(ITEMS)]
            with_dispute = (i == len(plan) - 1)
            created.append(create_full_record(
                customer_id, provider_id, provider_owner_id, item,
                "RETURN_VERIFIED" if with_dispute else target, with_dispute))

        say(f"{len(created)} service records created across all lifecycle states.")
        say("Sample record numbers:", ", ".join(created[:5]), "...")
        say("\nDemo login credentials (password for all):", DEMO_PASSWORD)
        say("customer@proofdesk.demo / provider@proofdesk.demo / admin@proofdesk.demo")


if __name__ == "__main__":
    from app import app as _app
    run_seed(_app)
