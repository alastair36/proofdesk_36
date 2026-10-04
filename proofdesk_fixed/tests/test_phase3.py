import sys
import re
import io
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
    s.post(f"{BASE}/login", data={"email": email, "password": password})
    return s


cust = login("customer@proofdesk.demo", PASS)
prov = login("provider@proofdesk.demo", PASS)

# --- Set up a fresh request -> accepted record for this test run ---
r = cust.get(f"{BASE}/customer/requests/new")
m = re.search(r'<option value="(\d+)"[^>]*>\s*\n\s*TechFix Repair Center', r.text)
provider_id = m.group(1)

r = cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Laptop/Desktop", "item_name": "Dell Laptop",
    "brand": "Dell", "model": "Inspiron 15", "serial_number": "ABC123XYZ",
    "problem_description": "Laptop is not charging.", "expected_completion_date": "2026-09-27",
}, allow_redirects=False)

r = prov.get(f"{BASE}/provider/requests")
req_id = re.findall(r'requests/(\d+)/accept', r.text)[-1]
r = prov.post(f"{BASE}/provider/requests/{req_id}/accept", allow_redirects=False)
record_number = r.headers["Location"].split("/records/")[1]
print("Using record:", record_number)

handover_url = f"{BASE}/records/{record_number}/handover"

# 15/16. Add accessories & condition
r = prov.get(handover_url)
check("Handover page loads for provider", r.status_code == 200)
check("Shows INCOMPLETE VERIFICATION before docs added", "INCOMPLETE VERIFICATION" in r.text)

r = prov.post(f"{BASE}/records/{record_number}/accessories", data={
    "acc_Charger": "yes", "acc_Mouse": "no", "custom_accessories": "",
})
check("Accessories saved", r.status_code in (200, 302))

r = prov.post(f"{BASE}/records/{record_number}/condition", data={
    "severity_Exterior_condition": "GOOD", "notes_Exterior_condition": "No visible damage",
    "severity_Scratches": "MINOR_ISSUE", "notes_Scratches": "Minor scratch on left side",
    "severity_Keyboard": "", "severity_Functional_condition": "GOOD",
})
check("Condition saved", r.status_code in (200, 302))

# 17/18. Photo upload - valid and invalid
from PIL import Image
buf = io.BytesIO()
Image.new("RGB", (100, 100), color=(120, 120, 200)).save(buf, format="JPEG")
buf.seek(0)
r = prov.post(f"{BASE}/records/{record_number}/evidence",
               data={"angle": "Front"}, files={"photo": ("front.jpg", buf, "image/jpeg")})
check("Valid image upload accepted", r.status_code in (200, 302))

r = prov.get(handover_url)
check("Uploaded photo appears on handover page", "front.jpg" not in r.text and "Front" in r.text)

# 18. Reject invalid file (fake image - text content with .jpg extension)
r_before = prov.get(handover_url)
before_count = len(re.findall(r'<figcaption>', r_before.text))

fake = io.BytesIO(b"this is not an image, just text pretending to be one")
r = prov.post(f"{BASE}/records/{record_number}/evidence",
               data={"angle": "Back"}, files={"photo": ("fake.jpg", fake, "image/jpeg")})
check("Fake-image upload flagged as error", "not a valid image" in r.text)
r2 = prov.get(handover_url)
after_count = len(re.findall(r'<figcaption>', r2.text))
check("Fake image did not get stored as evidence", after_count == before_count)

# Reject disallowed extension outright
fake2 = io.BytesIO(b"GIF89a not allowed")
r = prov.post(f"{BASE}/records/{record_number}/evidence",
               data={"angle": "Back"}, files={"photo": ("image.gif", fake2, "image/gif")})
check("Disallowed extension flagged as error", "Unsupported file type" in r.text)
r2 = prov.get(handover_url)
after_count2 = len(re.findall(r'<figcaption>', r2.text))
check("Disallowed extension (.gif) rejected", after_count2 == before_count)

# Authorization: customer cannot upload evidence (provider-only action)
buf2 = io.BytesIO()
Image.new("RGB", (50, 50)).save(buf2, format="PNG")
buf2.seek(0)
r = cust.post(f"{BASE}/records/{record_number}/evidence",
              data={"angle": "Front"}, files={"photo": ("x.png", buf2, "image/png")})
check("Customer blocked from uploading evidence (403)", r.status_code == 403)

# Still incomplete: no confirmations yet
r = prov.get(handover_url)
check("Still shows INCOMPLETE before confirmations", "INCOMPLETE VERIFICATION" in r.text)
check("Missing customer confirmation listed", "Customer confirmation" in r.text)

# 19. Customer confirms
r = cust.post(f"{BASE}/records/{record_number}/confirm-handover", allow_redirects=True)
check("Customer confirmation succeeds", r.status_code == 200)

# Duplicate confirmation prevented
r = cust.post(f"{BASE}/records/{record_number}/confirm-handover", allow_redirects=True)
check("Duplicate customer confirmation prevented", "already confirmed" in r.text)

# A user cannot confirm on behalf of the other role: provider account trying is fine
# (that's their own role) but let's confirm customer cannot impersonate provider role
# by checking there is no client-supplied role field being trusted at all (already true by design)

# 20. Provider confirms -> should trigger full verification
r = prov.post(f"{BASE}/records/{record_number}/confirm-handover", allow_redirects=True)
check("Provider confirmation succeeds", r.status_code == 200)
check("Handover now fully verified", "VERIFIED HANDOVER" in r.text)
check("Verification code shown", "Verification code:" in r.text)

m = re.search(r'qr/([A-Z0-9]+)\.png', r.text)
check("QR code image referenced", m is not None)
if m:
    qr_code = m.group(1)
    r_qr = prov.get(f"{BASE}/static/qr/{qr_code}.png")
    check("QR code PNG file is actually servable", r_qr.status_code == 200 and r_qr.headers['Content-Type'] == 'image/png')

    # Public verification page (no login) shows only safe info
    anon = requests.Session()
    r_pub = anon.get(f"{BASE}/records/verify/{qr_code}")
    check("Public verify page accessible without login", r_pub.status_code == 200)
    check("Public verify page shows record number", record_number in r_pub.text)
    check("Public verify page does NOT show customer email", "customer@proofdesk.demo" not in r_pub.text)

# Record status transitioned
r = prov.get(f"{BASE}/records/{record_number}")
check("Record status is HANDOVER_VERIFIED", "HANDOVER VERIFIED" in r.text.upper())

# Editing locked after verification
r = prov.post(f"{BASE}/records/{record_number}/accessories", data={"acc_Charger": "no"})
check("Cannot edit accessories after handover verified (403)", r.status_code == 403)

r = prov.get(f"{BASE}/records/{record_number}/handover")
check("Handover page still viewable (read-only) after verification", r.status_code == 200)

print("\n--- Summary ---")
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("All Phase 3 tests passed.")
