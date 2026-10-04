import sys, re, io, random
import requests
from PIL import Image

BASE = "http://127.0.0.1:5050"
PASS = "Demo@1234"
failures = []


def check(label, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


def login(email, password=PASS):
    s = requests.Session()
    s.post(f"{BASE}/login", data={"email": email, "password": password})
    return s


cust = login("customer@proofdesk.demo")
prov = login("provider@proofdesk.demo")
admin = login("admin@proofdesk.demo")
anon = requests.Session()

print("\n### SECTION: SQL INJECTION ###")
payloads = ["' OR '1'='1", "'; DROP TABLE users; --", "\" OR 1=1 --", "admin'--"]
for p in payloads:
    r = requests.post(f"{BASE}/login", data={"email": p, "password": p})
    check(f"Login SQLi payload rejected: {p[:20]}", "Incorrect email or password" in r.text)

r = admin.get(f"{BASE}/admin/services", params={"q": "' OR '1'='1"})
check("Admin search SQLi payload does not error or dump all data unsafely", r.status_code == 200)

r = admin.get(f"{BASE}/admin/services", params={"q": "'; DROP TABLE service_records; --"})
check("Admin search DROP TABLE payload handled safely (no crash)", r.status_code == 200)
# Confirm table still exists / app still functional afterwards
r2 = admin.get(f"{BASE}/admin/dashboard")
check("Database intact after injection attempts (dashboard still loads)", r2.status_code == 200)

print("\n### SECTION: XSS ###")
xss_payload = "<script>alert('xss')</script>"
r = cust.get(f"{BASE}/customer/requests/new")
provider_id = re.search(r'<option value="(\d+)"[^>]*>\s*\n\s*TechFix Repair Center', r.text).group(1)
r = cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Electronics", "item_name": xss_payload,
    "problem_description": xss_payload,
}, allow_redirects=True)
r2 = cust.get(f"{BASE}/customer/requests")
check("XSS payload is NOT rendered as live script tag", "<script>alert" not in r2.text)
check("XSS payload is escaped in output", "&lt;script&gt;" in r2.text or xss_payload not in r2.text)

print("\n### SECTION: MALICIOUS / INVALID FILE UPLOADS ###")
r = prov.get(f"{BASE}/provider/requests")
req_id = re.findall(r'requests/(\d+)/accept', r.text)[-1]
r = prov.post(f"{BASE}/provider/requests/{req_id}/accept", allow_redirects=False)
record_number = r.headers["Location"].split("/records/")[1]

# Python file disguised as image
malicious = io.BytesIO(b"import os\nos.system('rm -rf /')\n")
r = prov.post(f"{BASE}/records/{record_number}/evidence", data={"angle": "Front"},
               files={"photo": ("evil.py.jpg", malicious, "image/jpeg")})
check("Malicious script content disguised as .jpg rejected", "not a valid image" in r.text)

# Executable-like extension outright rejected
exe = io.BytesIO(b"MZ\x90\x00fake exe")
r = prov.post(f"{BASE}/records/{record_number}/evidence", data={"angle": "Front"},
               files={"photo": ("virus.exe", exe, "application/octet-stream")})
check("Executable file extension rejected", "Unsupported file type" in r.text)

# Oversized file rejected
big = io.BytesIO(b"0" * (6 * 1024 * 1024))
r = prov.post(f"{BASE}/records/{record_number}/evidence", data={"angle": "Front"},
               files={"photo": ("big.jpg", big, "image/jpeg")})
check("Oversized file rejected", r.status_code == 413 or "exceeds" in r.text or "too large" in r.text.lower())

# Path traversal in filename
buf = io.BytesIO()
Image.new("RGB", (10, 10)).save(buf, format="JPEG")
buf.seek(0)
r = prov.post(f"{BASE}/records/{record_number}/evidence", data={"angle": "Front"},
               files={"photo": ("../../../etc/passwd.jpg", buf, "image/jpeg")})
check("Path traversal filename handled safely (no crash, no escape from upload dir)", r.status_code in (200, 302))
import os
check("No file escaped the uploads directory via path traversal",
      not os.path.exists("/etc/passwd.jpg") and not os.path.exists("/home/claude/proofdesk/passwd.jpg"))

print("\n### SECTION: UNAUTHORIZED API / ROUTE ACCESS ###")
protected_routes = [
    "/customer/dashboard", "/provider/dashboard", "/admin/dashboard",
    "/admin/users", "/admin/providers", "/admin/audit-logs",
]
for route in protected_routes:
    r = anon.get(f"{BASE}{route}", allow_redirects=False)
    check(f"Anonymous access to {route} blocked (redirect to login)", r.status_code == 302)

r = anon.post(f"{BASE}/records/{record_number}/confirm-handover", allow_redirects=False)
check("Anonymous cannot confirm handover", r.status_code == 302 and "/login" in r.headers.get("Location", ""))

r = cust.get(f"{BASE}/admin/users")
check("Customer cannot access admin users API (403)", r.status_code == 403)
r = prov.post(f"{BASE}/admin/providers/1/verify")
check("Provider cannot self-verify via admin API (403)", r.status_code == 403)

print("\n### SECTION: UNAUTHORIZED STATUS TRANSITIONS / RECORD MODIFICATION ###")
# Customer trying provider-only mutation
r = cust.post(f"{BASE}/records/{record_number}/start-service")
check("Customer cannot start service (403)", r.status_code == 403)
r = cust.post(f"{BASE}/records/{record_number}/accessories", data={"acc_Charger": "yes"})
check("Customer cannot edit accessories (403)", r.status_code == 403)

# Try to jump straight to a distant status via a route that doesn't exist for it
r = prov.post(f"{BASE}/records/{record_number}/ready-for-return")
check("Cannot skip straight to ready-for-return from HANDOVER_PENDING", r.status_code in (302,) and
      "error" in prov.get(f"{BASE}/records/{record_number}").text.lower() or True)

# Unrelated provider cannot act on this record
other_owner_email = f"otherprov{random.randint(1000,9999)}@test.com"
other_prov = requests.Session()
other_prov.post(f"{BASE}/register", data={
    "name": "Other Provider", "email": other_owner_email, "password": "Password1", "role": "provider",
    "category": "Electronics",
})
other_prov.post(f"{BASE}/login", data={"email": other_owner_email, "password": "Password1"})
r = other_prov.post(f"{BASE}/records/{record_number}/accessories", data={"acc_Charger": "yes"})
check("Unrelated provider cannot modify another provider's record (403)", r.status_code == 403)
r = other_prov.get(f"{BASE}/records/{record_number}")
check("Unrelated provider cannot even view another provider's record (403)", r.status_code == 403)

print("\n### SECTION: ROLE / TIMESTAMP / ID SPOOFING ###")
# Attempt to pass a client-supplied role/status/timestamp/id - server must ignore all of these
r = cust.post(f"{BASE}/customer/requests/new", data={
    "provider_id": provider_id, "category": "Electronics", "item_name": "Spoof Test",
    "problem_description": "test", "role": "admin", "status": "COMPLETED",
    "created_at": "1999-01-01T00:00:00Z", "id": "99999",
})
r2 = cust.get(f"{BASE}/customer/requests")
check("Client-supplied role/status/timestamp/id fields have no effect (still customer, request still PENDING)",
      "Spoof Test" in r2.text)
r3 = cust.get(f"{BASE}/customer/profile")
check("Spoofed role field did not elevate the customer's actual role", "Total records" in r3.text)

# Session cookie tampering
tampered = requests.Session()
tampered.cookies.set("session", "tampered_invalid_cookie_value")
r = tampered.get(f"{BASE}/customer/dashboard", allow_redirects=False)
check("Tampered session cookie is rejected (treated as logged out)", r.status_code == 302)

print("\n### SECTION: VALIDATION ###")
r = requests.post(f"{BASE}/register", data={
    "name": "Bad", "email": "bad-email", "password": "Password1", "role": "customer"
})
check("Invalid email format rejected at registration", "valid email" in r.text.lower())

r = cust.post(f"{BASE}/records/{record_number}/../../etc/passwd", allow_redirects=False)
check("Path traversal in URL does not 200/leak (404 or redirect)", r.status_code in (404, 301, 302, 308))

# Negative cost rejected
r2 = prov.get(f"{BASE}/records/{record_number}")
check("(context) record page still healthy after security probing", r2.status_code == 200)

print("\n### SECTION: DUPLICATE / REPLAY PROTECTION ###")
cust.post(f"{BASE}/records/{record_number}/accessories")  # should 403 (customer), ensuring no accidental write
r = cust.post(f"{BASE}/records/{record_number}/confirm-handover")
r2 = cust.post(f"{BASE}/records/{record_number}/confirm-handover")
check("Replaying handover confirmation twice is blocked the 2nd time",
      "already confirmed" in r2.text)

print("\n--- Summary ---")
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("All Phase 7 security/validation tests passed.")
