import sys, re, io
import requests
from PIL import Image

BASE = "http://127.0.0.1:5050"
PASS = "Demo@1234"
failures = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


def login(email, password):
    s = requests.Session()
    s.post(f"{BASE}/login", data={"email": email, "password": password})
    return s


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (60, 60), (5, 5, 200)).save(buf, format="JPEG")
    buf.seek(0)
    return buf


cust = login("customer@proofdesk.demo", PASS)
prov = login("provider@proofdesk.demo", PASS)
admin = login("admin@proofdesk.demo", PASS)


def build_completed_record():
    r = cust.get(f"{BASE}/customer/requests/new")
    provider_id = re.search(r'<option value="(\d+)"[^>]*>\s*\n\s*TechFix Repair Center', r.text).group(1)
    cust.post(f"{BASE}/customer/requests/new", data={
        "provider_id": provider_id, "category": "Laptop/Desktop", "item_name": "Dell Laptop",
        "problem_description": "Not charging.",
    })
    r = prov.get(f"{BASE}/provider/requests")
    req_id = re.findall(r'requests/(\d+)/accept', r.text)[-1]
    r = prov.post(f"{BASE}/provider/requests/{req_id}/accept", allow_redirects=False)
    rn = r.headers["Location"].split("/records/")[1]

    prov.post(f"{BASE}/records/{rn}/accessories", data={"acc_Charger": "yes"})
    prov.post(f"{BASE}/records/{rn}/condition", data={"severity_Exterior_condition": "GOOD"})
    prov.post(f"{BASE}/records/{rn}/evidence", data={"angle": "Front"}, files={"photo": ("f.jpg", jpeg(), "image/jpeg")})
    cust.post(f"{BASE}/records/{rn}/confirm-handover")
    prov.post(f"{BASE}/records/{rn}/confirm-handover")
    prov.post(f"{BASE}/records/{rn}/start-service")
    prov.post(f"{BASE}/records/{rn}/complete-service")
    prov.post(f"{BASE}/records/{rn}/record-payment", data={"amount": "1500", "method": "Cash"})
    prov.post(f"{BASE}/records/{rn}/ready-for-return")
    r = prov.post(f"{BASE}/records/{rn}/generate-return-code", allow_redirects=True)
    code = re.search(r'<p style="font-size:1.4rem;font-weight:700">([A-Z0-9]+)</p>', r.text).group(1)
    cust.post(f"{BASE}/records/{rn}/confirm-return-code", data={"code": code})
    prov.post(f"{BASE}/records/{rn}/return-condition", data={"severity_Exterior_condition": "GOOD"})
    r = prov.get(f"{BASE}/records/{rn}/return")
    acc_id = re.search(r'name="ret_(\d+)"', r.text).group(1)
    prov.post(f"{BASE}/records/{rn}/return-accessories", data={f"ret_{acc_id}": "yes"})
    prov.post(f"{BASE}/records/{rn}/return-evidence", data={"angle": "Front"}, files={"photo": ("r.jpg", jpeg(), "image/jpeg")})
    r = prov.post(f"{BASE}/records/{rn}/verify-return", data={"condition_summary": "ok"}, allow_redirects=True)
    return rn, r


record_number, r = build_completed_record()
check("Record auto-transitions to COMPLETED after return verified", "COMPLETED" in r.text.upper())

r = prov.get(f"{BASE}/records/{record_number}")
check("Record shows locked banner", "Record locked" in r.text)

# 31/32/33. Locking enforcement
r = prov.post(f"{BASE}/records/{record_number}/accessories", data={"acc_Charger": "no"})
check("Cannot edit accessories on locked record (403)", r.status_code == 403)

r = prov.post(f"{BASE}/records/{record_number}/service-update", data={"update_type": "DIAGNOSIS", "description": "x"})
check("Cannot add service update to locked record (403)", r.status_code == 403)

r = prov.post(f"{BASE}/records/{record_number}/record-payment", data={"amount": "1", "method": "Cash"})
check("Cannot record payment on locked record (403)", r.status_code == 403)

# 34. Audit history remains available after lock
r = prov.get(f"{BASE}/records/{record_number}")
check("Audit history still visible after lock", "RECORD COMPLETED" in r.text.upper() or "Record Completed" in r.text)

# Before/after comparison page
r = cust.get(f"{BASE}/records/{record_number}/compare")
check("Before/after comparison page accessible", r.status_code == 200)
check("Comparison shows AT HANDOVER and AT RETURN", "AT HANDOVER" in r.text and "AT RETURN" in r.text)

# --- Dispute lifecycle on a second, separate record ---
record2, _ = build_completed_record()

r = prov.get(f"{BASE}/records/{record2}/dispute/new")
check("Provider blocked from opening a dispute (403)", r.status_code == 403)

r = cust.post(f"{BASE}/records/{record2}/dispute/new", data={
    "category": "CONDITION_DISAGREEMENT", "description": "Item came back with a new scratch."
}, allow_redirects=True)
check("Customer opens dispute successfully", r.status_code == 200)
check("Record status becomes DISPUTED", "DISPUTED" in r.text.upper())

# Duplicate open dispute blocked
r = cust.post(f"{BASE}/records/{record2}/dispute/new", data={
    "category": "OTHER", "description": "second"
}, allow_redirects=True)
check("Second dispute while one is open is blocked", "already an open dispute" in r.text)

# Admin reviews and resolves
r = admin.get(f"{BASE}/admin/disputes")
m = re.search(rf"dispute_id=|disputes/(\d+)\b", r.text)
disp_id_match = re.search(r"disputes/(\d+)", r.text)
check("Dispute appears in admin dispute list", record2 in r.text)
disp_id = disp_id_match.group(1)

r = cust.get(f"{BASE}/admin/disputes/{disp_id}")
check("Customer blocked from admin dispute review (403)", r.status_code == 403)

r = admin.get(f"{BASE}/admin/disputes/{disp_id}")
check("Admin can view dispute detail with evidence", r.status_code == 200 and "Photographic Evidence" in r.text)

r = admin.post(f"{BASE}/admin/disputes/{disp_id}/resolve", data={"resolution": "Verified no new damage; closing."}, allow_redirects=True)
check("Admin resolves dispute", r.status_code == 200 and ("resolved and closed" in r.text.lower() or "CLOSED" in r.text))

r = cust.get(f"{BASE}/records/{record2}")
check("Record restored to COMPLETED after dispute resolved", "COMPLETED" in r.text.upper())
check("Original record still shows as locked after dispute resolution", "Record locked" in r.text)

print("\n--- Summary ---")
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("All Phase 5 tests passed.")
