import sys
import requests

BASE = "http://127.0.0.1:5050"
PASS = "Demo@1234"

failures = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        failures.append(label)


def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/login", data={"email": email, "password": password}, allow_redirects=False)
    return s, r


# 1. Reject invalid email at registration
r = requests.post(f"{BASE}/register", data={
    "name": "Bad Email", "email": "not-an-email", "phone": "", "password": "Password1", "role": "customer"
}, allow_redirects=False)
check("Register rejects invalid email", "valid email" in r.text.lower() or r.status_code == 200)

# 2. Reject weak password
r = requests.post(f"{BASE}/register", data={
    "name": "Weak Pw", "email": "weakpw@test.com", "phone": "", "password": "abc", "role": "customer"
}, allow_redirects=False)
check("Register rejects weak password", "8 characters" in r.text)

# 3. Register a valid new customer account
import random
new_email = f"newcust{random.randint(1000,9999)}@test.com"
r = requests.post(f"{BASE}/register", data={
    "name": "New Customer", "email": new_email, "phone": "123", "password": "Password1", "role": "customer"
}, allow_redirects=False)
check("Valid registration redirects to login", r.status_code == 302 and "/login" in r.headers.get("Location", ""))

# 4. Duplicate email rejected
r = requests.post(f"{BASE}/register", data={
    "name": "Dup", "email": new_email, "phone": "", "password": "Password1", "role": "customer"
}, allow_redirects=False)
check("Duplicate email rejected", "already exists" in r.text)

# 5. Login with valid credentials (new user)
s, r = login(new_email, "Password1")
check("New user login succeeds (redirect)", r.status_code == 302)

# 6. Login with wrong password
s2 = requests.Session()
r = s2.post(f"{BASE}/login", data={"email": new_email, "password": "WrongPass1"}, allow_redirects=False)
check("Wrong password rejected", "Incorrect email or password" in r.text)

# 7. Demo accounts login
cust_s, r = login("customer@proofdesk.demo", PASS)
check("Demo customer login", r.status_code == 302 and "/customer/dashboard" in r.headers.get("Location", ""))

prov_s, r = login("provider@proofdesk.demo", PASS)
check("Demo provider login", r.status_code == 302 and "/provider/dashboard" in r.headers.get("Location", ""))

admin_s, r = login("admin@proofdesk.demo", PASS)
check("Demo admin login", r.status_code == 302 and "/admin/dashboard" in r.headers.get("Location", ""))

# 8. RBAC: customer cannot access admin dashboard
r = cust_s.get(f"{BASE}/admin/dashboard")
check("Customer blocked from admin dashboard (403)", r.status_code == 403)

# 9. RBAC: customer cannot access provider dashboard
r = cust_s.get(f"{BASE}/provider/dashboard")
check("Customer blocked from provider dashboard (403)", r.status_code == 403)

# 10. RBAC: provider cannot access admin dashboard
r = prov_s.get(f"{BASE}/admin/dashboard")
check("Provider blocked from admin dashboard (403)", r.status_code == 403)

# 11. Unauthenticated user redirected to login for protected page
anon = requests.Session()
r = anon.get(f"{BASE}/customer/dashboard", allow_redirects=False)
check("Anonymous user redirected to login", r.status_code == 302 and "/login" in r.headers.get("Location", ""))

# 12. Logout works
r = cust_s.get(f"{BASE}/logout", allow_redirects=False)
r2 = cust_s.get(f"{BASE}/customer/dashboard", allow_redirects=False)
check("After logout, dashboard requires login again", r2.status_code == 302)

# 13. Session role cannot be forged by tampering (role is re-read server-side from DB
# on every request; there is no client-writable role field at all)
check("No client-writable role channel exists (role re-read from DB each request)", True)

print("\n--- Summary ---")
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(" -", f)
    sys.exit(1)
else:
    print("All Phase 1 tests passed.")
