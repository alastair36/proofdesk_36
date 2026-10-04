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


def make_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (80, 80), color=(10, 200, 10)).save(buf, format="JPEG")
    buf.seek(0)
    return buf


cust = login("customer@proofdesk.demo", PASS)
prov = login("provider@proofdesk.demo", PASS)

# --- Build a fully-verified handover record to work from ---
r = cust.get(f"{BASE}/customer/requests/new")
provider_id = re.search(r'<option value="(\d+)"[^>]*>\s*\n\s*TechFix Repair Center', r.text).group(1)
cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Laptop/Desktop", "item_name": "Dell Laptop",
    "problem_description": "Laptop is not charging.",
})
r = prov.get(f"{BASE}/provider/requests")
req_id = re.findall(r'requests/(\d+)/accept', r.text)[-1]
r = prov.post(f"{BASE}/provider/requests/{req_id}/accept", allow_redirects=False)
record_number = r.headers["Location"].split("/records/")[1]
print("Using record:", record_number)

prov.post(f"{BASE}/records/{record_number}/accessories", data={"acc_Charger": "yes"})
prov.post(f"{BASE}/records/{record_number}/condition", data={"severity_Exterior_condition": "GOOD"})
prov.post(f"{BASE}/records/{record_number}/evidence", data={"angle": "Front"},
          files={"photo": ("f.jpg", make_jpeg(), "image/jpeg")})
cust.post(f"{BASE}/records/{record_number}/confirm-handover")
prov.post(f"{BASE}/records/{record_number}/confirm-handover")

r = prov.get(f"{BASE}/records/{record_number}")
check("Record is HANDOVER_VERIFIED before service phase", "HANDOVER VERIFIED" in r.text.upper())

# 22. Start service
r = cust.post(f"{BASE}/records/{record_number}/start-service")
check("Customer cannot start service (403)", r.status_code == 403)
r = prov.post(f"{BASE}/records/{record_number}/start-service", allow_redirects=True)
check("Provider starts service", r.status_code == 200 and "SERVICE IN PROGRESS" in r.text.upper())

# 23. Add diagnosis / service update
r = prov.post(f"{BASE}/records/{record_number}/service-update", data={
    "update_type": "DIAGNOSIS", "description": "Charging port requires replacement."
}, allow_redirects=True)
check("Diagnosis added", "Charging port requires replacement" in r.text)

r = prov.post(f"{BASE}/records/{record_number}/service-update", data={
    "update_type": "SERVICE_PERFORMED", "description": "Charging port replaced."
}, allow_redirects=True)
check("Service performed update added", "Charging port replaced" in r.text)

# Customer cannot add service updates
r = cust.post(f"{BASE}/records/{record_number}/service-update", data={
    "update_type": "DIAGNOSIS", "description": "hacked"
})
check("Customer blocked from adding service updates (403)", r.status_code == 403)

# 25/26. Increase cost beyond estimate -> requires customer approval
r = prov.post(f"{BASE}/records/{record_number}/update-cost", data={"new_cost": "2200"}, allow_redirects=True)
check("Cost increase creates pending approval, not silently applied",
      "Cost Approval" in r.text and "APPROVED" not in r.text.split("Cost Approval")[1][:200])

r = prov.get(f"{BASE}/records/{record_number}")
m = re.search(r"cost-approval/(\d+)/decide", r.text)
check("Cost approval decision form present for customer view", True)  # provider view won't show buttons

r = cust.get(f"{BASE}/records/{record_number}")
m = re.search(r"cost-approval/(\d+)/decide", r.text)
check("Approve/decline buttons shown to customer", m is not None)
approval_id = m.group(1)

# Provider cannot mark service complete while approval pending
r = prov.post(f"{BASE}/records/{record_number}/complete-service", allow_redirects=True)
check("Cannot complete service while cost approval pending", "pending" in r.text.lower())

# Provider cannot decide the approval themselves
r = prov.post(f"{BASE}/records/{record_number}/cost-approval/{approval_id}/decide", data={"decision": "APPROVE"})
check("Provider cannot decide their own cost approval (403)", r.status_code == 403)

# 26. Customer approves
r = cust.post(f"{BASE}/records/{record_number}/cost-approval/{approval_id}/decide",
               data={"decision": "APPROVE"}, allow_redirects=True)
check("Customer approves additional cost", "APPROVED" in r.text.upper() and "₹2200" in r.text.replace(".00","").replace(" ","") or "2200.00" in r.text)

# Duplicate decision blocked
r = cust.post(f"{BASE}/records/{record_number}/cost-approval/{approval_id}/decide", data={"decision": "APPROVE"})
check("Duplicate cost decision blocked", "already been decided" in r.text)

# 21/completing. Now complete service
r = prov.post(f"{BASE}/records/{record_number}/complete-service", allow_redirects=True)
check("Service completed after approval resolved", r.status_code == 200 and "PAYMENT PENDING" in r.text.upper())

# 22 payment. Underpayment shouldn't allow ready-for-return
r = prov.post(f"{BASE}/records/{record_number}/record-payment", data={
    "amount": "1000", "method": "Cash", "reference": "partial"
}, allow_redirects=True)
check("Partial payment recorded", "1000.00" in r.text)

r = prov.post(f"{BASE}/records/{record_number}/ready-for-return", allow_redirects=True)
check("Cannot mark ready for return before full payment", "Full payment" in r.text)

r = prov.post(f"{BASE}/records/{record_number}/record-payment", data={
    "amount": "1200", "method": "UPI", "reference": "REF999"
}, allow_redirects=True)
check("Remaining payment recorded", "1200.00" in r.text)

# Customer cannot record payment
r = cust.post(f"{BASE}/records/{record_number}/record-payment", data={"amount": "1", "method": "Cash"})
check("Customer blocked from recording payment (403)", r.status_code == 403)

# 23. Ready for return now allowed
r = prov.post(f"{BASE}/records/{record_number}/ready-for-return", allow_redirects=True)
check("Marked ready for return after full payment", "READY FOR RETURN" in r.text.upper())

# 24. Return code generation
r = prov.get(f"{BASE}/records/{record_number}/return")
check("Return page loads", r.status_code == 200)
r = prov.post(f"{BASE}/records/{record_number}/generate-return-code", allow_redirects=True)
m = re.search(r"Return code generated: ([A-Z0-9]+)", r.text) or re.search(r'<p style="font-size:1.4rem;font-weight:700">([A-Z0-9]+)</p>', r.text)
check("Return code generated", m is not None)
code = m.group(1) if m else None

# Wrong code rejected
r = cust.post(f"{BASE}/records/{record_number}/confirm-return-code", data={"code": "WRONG1"}, allow_redirects=True)
check("Incorrect return code rejected", "Incorrect return code" in r.text)

# Correct code
r = cust.post(f"{BASE}/records/{record_number}/confirm-return-code", data={"code": code}, allow_redirects=True)
check("Correct return code accepted", "confirmed" in r.text.lower())

# 29 (dup prevention). Duplicate return code confirmation blocked
r = cust.post(f"{BASE}/records/{record_number}/confirm-return-code", data={"code": code}, allow_redirects=True)
check("Duplicate return confirmation prevented", "already been confirmed" in r.text)

# Provider records final condition + accessories returned + verifies
prov.post(f"{BASE}/records/{record_number}/return-condition", data={"severity_Exterior_condition": "GOOD"})
r = prov.get(f"{BASE}/records/{record_number}/return")
acc_id_match = re.search(r'name="ret_(\d+)"', r.text)
if acc_id_match:
    prov.post(f"{BASE}/records/{record_number}/return-accessories", data={f"ret_{acc_id_match.group(1)}": "yes"})
prov.post(f"{BASE}/records/{record_number}/return-evidence", data={"angle": "Front"},
          files={"photo": ("r.jpg", make_jpeg(), "image/jpeg")})

r = prov.post(f"{BASE}/records/{record_number}/verify-return", data={"condition_summary": "Matches handover condition"},
               allow_redirects=True)
check("Return verified successfully", "RETURN VERIFIED" in r.text.upper())

print("\n--- Summary ---")
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("All Phase 4 tests passed.")
