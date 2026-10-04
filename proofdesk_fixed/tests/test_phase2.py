import sys
import requests

BASE = "http://127.0.0.1:5050"
PASS = "Demo@1234"
failures = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/login", data={"email": email, "password": password})
    return s


cust = login("customer@proofdesk.demo", PASS)
prov = login("provider@proofdesk.demo", PASS)
admin = login("admin@proofdesk.demo", PASS)

# Find provider id from the new-request form
r = cust.get(f"{BASE}/customer/requests/new")
check("New request form loads", r.status_code == 200 and "TechFix Repair Center" in r.text)

import re
m = re.search(r'<option value="(\d+)"[^>]*>\s*\n\s*TechFix Repair Center', r.text)
provider_id = m.group(1) if m else None
check("Provider option present in dropdown", provider_id is not None)

# 11/12. Create valid request
r = cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Laptop/Desktop", "item_name": "Dell Laptop",
    "brand": "Dell", "model": "Inspiron 15", "serial_number": "ABC123XYZ",
    "problem_description": "Laptop is not charging.", "preferred_service": "Diagnose and repair",
    "expected_completion_date": "2026-09-27", "additional_notes": "Handle with care",
}, allow_redirects=False)
check("Valid request creation redirects", r.status_code == 302)

# 12. Reject missing required fields
r = cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Laptop/Desktop", "item_name": "",
    "problem_description": "",
}, allow_redirects=False)
check("Missing required fields rejected", r.status_code == 200 and "required" in r.text.lower())

# Verify request shows up for customer
r = cust.get(f"{BASE}/customer/requests")
check("Request appears in customer's request list", "Dell Laptop" in r.text)

# Verify it shows up for provider
r = prov.get(f"{BASE}/provider/requests")
check("Request appears in provider's incoming requests", "Dell Laptop" in r.text)

m2 = re.search(r'requests/(\d+)/accept', r.text)
check("Accept form present for provider", m2 is not None)
req_id = m2.group(1)

# Authorization: customer cannot hit provider's accept endpoint directly
r = cust.post(f"{BASE}/provider/requests/{req_id}/accept")
check("Customer cannot accept a request as provider (403)", r.status_code == 403)

# 13. Provider accepts request -> creates service record
r = prov.post(f"{BASE}/provider/requests/{req_id}/accept", allow_redirects=False)
check("Accept redirects to new service record", r.status_code == 302 and "/records/SR-" in r.headers.get("Location", ""))
record_number = r.headers["Location"].split("/records/")[1]
check("Record number format SR-YYYY-XXXXX", re.match(r"^SR-\d{4}-\d{5}$", record_number) is not None)

# Record view page for provider works and shows core sections
r = prov.get(f"{BASE}/records/{record_number}")
check("Provider can view the new record", r.status_code == 200 and "HANDOVER PENDING" in r.text.upper())
check("Item info shown on record page", "Dell Laptop" in r.text and "ABC123XYZ" in r.text)

# Record view page for customer works
r = cust.get(f"{BASE}/records/{record_number}")
check("Customer (owner) can view the record", r.status_code == 200)

# Admin can view any record
r = admin.get(f"{BASE}/records/{record_number}")
check("Admin can view any record", r.status_code == 200)

# 7. Authorization: customer cannot access another customer's record
other_cust = requests.Session()
import random
other_email = f"othercust{random.randint(1000,9999)}@test.com"
other_cust.post(f"{BASE}/register", data={
    "name": "Other Customer", "email": other_email, "password": "Password1", "role": "customer"
})
other_cust.post(f"{BASE}/login", data={"email": other_email, "password": "Password1"})
r = other_cust.get(f"{BASE}/records/{record_number}")
check("Unrelated customer blocked from another customer's record (403)", r.status_code == 403)

# 14. Provider reject flow
r = cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Mobile Phone", "item_name": "iPhone",
    "problem_description": "Screen cracked",
}, allow_redirects=False)
r = prov.get(f"{BASE}/provider/requests")
m3 = re.findall(r'requests/(\d+)/reject', r.text)
check("Reject form present", len(m3) > 0)
reject_id = m3[-1]
r = prov.post(f"{BASE}/provider/requests/{reject_id}/reject", allow_redirects=False)
check("Provider can reject a request", r.status_code == 302)
r = cust.get(f"{BASE}/customer/requests")
check("Rejected status visible to customer", "REJECTED" in r.text)

# Non-existent record number -> 404, not a 500 or data leak
r = cust.get(f"{BASE}/records/SR-2026-99999")
check("Nonexistent record returns 404", r.status_code == 404)

print("\n--- Summary ---")
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("All Phase 2 tests passed.")
