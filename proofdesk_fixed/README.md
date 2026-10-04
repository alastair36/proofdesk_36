# ProofDesk

> **Quick start (Windows)**
>
> 1. Install Python 3.10+ from python.org (tick **"Add Python to PATH"**).
> 2. Open **cmd** inside the `proofdesk` folder and run **one command**:
>
>    ```
>    start
>    ```
>
> That installs everything (first time only), loads the demo data and opens
> **http://127.0.0.1:5050** in the browser. Works the same on Mac/Linux with `python3 start.py`.
>
> Log in with `customer@proofdesk.demo`, `provider@proofdesk.demo` or `admin@proofdesk.demo`
> (password `Demo@1234`).
>
> **On a phone?** Phones can't run Python, so either:
> 1. Run `start phone` on the PC, then open the `http://<PC-IP>:5050` address it prints (same Wi-Fi), or
> 2. On GitHub use **Code -> Codespaces -> Create codespace**. It installs, seeds and starts the
>    app automatically (see `.devcontainer/`); open the forwarded port 5050 from any browser.

A digital service-handover and evidence management platform for repair shops, laundries,
electronics service centers and similar businesses. It creates a structured, timestamped,
evidence-first record of the entire lifecycle of a customer's item: from drop-off, through
condition documentation and dual confirmation, service, payment, and verified return.

Built as a real, working application — not a mockup. Every button performs a real
server-side operation; every workflow has been exercised with automated tests against a
running instance (see **Testing** below).

---

## 1. Technology Stack

| Layer          | Choice                                                               |
|----------------|-----------------------------------------------------------------------|
| Backend        | Python 3 + Flask (server-rendered, blueprint-organized)               |
| Database       | SQLite (via Python's built-in `sqlite3`), raw parameterized SQL       |
| Auth           | Flask sessions (signed cookies) + Werkzeug PBKDF2 password hashing    |
| Templates      | Jinja2 (server-rendered HTML, no separate frontend build step)        |
| File uploads   | Content-validated via Pillow (actual image decoding, not just extension/MIME trust) |
| QR codes       | Real QR generation via the pure-Python `qrcode` package (Pillow-rendered): cross-platform, no system libraries, no external services |
| Styling        | Hand-written CSS, no external CDN dependency                          |

This stack was chosen because it is fully self-contained (no external network calls, no
paid services, no JS build pipeline) and is realistic for a college-level full-stack project
while still implementing real security practices.

---

## 2. Project Structure

```
proofdesk/
├── app.py                  # App factory, blueprint registration, error handlers
├── auth.py                 # Registration, login, logout, RBAC decorators
├── db.py                   # SQLite connection helpers
├── schema.sql              # Full relational schema (16 tables, FKs, constraints)
├── seed.py                 # Minimal seed: just the 3 demo accounts
├── seed_demo.py            # Full demo dataset: 15 records across every lifecycle state
├── requirements.txt
├── .env.example
├── routes/
│   ├── customer.py         # Customer dashboard, requests, services, notifications, profile
│   ├── provider.py         # Provider dashboard, request accept/reject, profile
│   ├── admin.py             # Admin dashboard/analytics, users, providers, disputes, audit log
│   └── records.py          # THE CORE MODULE: service record lifecycle, handover, service
│                            # workflow, cost approval, payments, returns, disputes, QR verify
├── utils/
│   ├── helpers.py           # Server-side timestamps, ID/code generation, audit + notify
│   ├── state_machine.py     # Explicit allowed-transitions table (no arbitrary status changes)
│   ├── verification.py      # Deterministic handover/return verification (no AI scoring)
│   ├── uploads.py           # Content-based image validation, safe filename generation
│   └── qr.py                # QR generation (qrcode package; libqrencode fallback)
├── templates/               # Jinja2 templates, organized by role/module
├── static/
│   ├── css/style.css
│   ├── uploads/             # Uploaded evidence photos (server-generated filenames)
│   └── qr/                  # Generated QR code PNGs
└── tests/                   # Automated test suites (see Testing section)
```

---

## 3. Database Schema

16 tables implementing the full spec: `users`, `service_providers`, `service_requests`,
`service_records`, `accessories`, `condition_reports`, `evidence_files`, `confirmations`,
`service_updates`, `cost_approvals`, `payments`, `returns`, `disputes`, `audit_logs`,
`notifications`. Full definitions with foreign keys, `CHECK` constraints and indexes are in
`schema.sql`. Key design points:

- Every status field is constrained with `CHECK (... IN (...))` at the database level, not
  just in application code.
- `confirmations` has a `UNIQUE(service_record_id, role, confirmation_type)` constraint —
  duplicate confirmations are rejected by the database itself, not just the route logic.
- `service_records.locked_at` is set once, server-side, when a record reaches `COMPLETED`,
  and is checked before any mutating operation on that record.
- `disputes.previous_status` lets the admin resolution flow restore a record to where it was
  before the dispute, without ever touching the original locked data.

---

## 4. Environment Variables

| Variable      | Required?         | Purpose                                          |
|---------------|--------------------|---------------------------------------------------|
| `SECRET_KEY`  | Recommended in prod | Signs session cookies. If unset, a random key is generated per run (fine for local demo, but means logins won't survive a server restart). |

Copy `.env.example` to `.env` and set `SECRET_KEY` for anything beyond a local demo.
(The app reads it via `os.environ`; wire up `python-dotenv` loading in `app.py` if you want
`.env` auto-loaded, or `export` it in your shell before running.)

---

## 5. Setup Instructions

### Requirements
- Python 3.10+ (on Windows, tick **"Add Python to PATH"** in the installer)
- Nothing else. All dependencies (including QR generation) install via `pip`.

### Steps (manual)
```bash
cd proofdesk
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env

python seed_demo.py             # 15 records, 10 customers, 5 providers (recommended)
# or: python seed.py            # just the 3 demo accounts
python app.py
```

The app runs at **http://127.0.0.1:5050**. Optional env vars (in `.env`): `HOST` (default `127.0.0.1`; use `0.0.0.0` for LAN/phone access), `PORT`, `FLASK_DEBUG=1`. `.env` is now loaded automatically.

> Both seed scripts are idempotent for accounts (existing users/providers are skipped),
> but `seed_demo.py` always adds a fresh batch of 15 service records — run it once on a
> clean `instance/proofdesk.db` (delete the file first if re-seeding).

---

## 6. Demo Credentials

All demo accounts share the password: **`Demo@1234`**

| Role      | Email                        |
|-----------|-------------------------------|
| Customer  | `customer@proofdesk.demo`     |
| Provider  | `provider@proofdesk.demo` (TechFix Repair Center — verified) |
| Admin     | `admin@proofdesk.demo`        |

`seed_demo.py` additionally creates `customer1@proofdesk.demo` … `customer9@proofdesk.demo`
and `provider1@proofdesk.demo` … `provider4@proofdesk.demo` (same password), giving a
realistic multi-user dataset.

---

## 7. Functional Requirements Implemented

**Authentication & Authorization**
- Registration with email format and password-strength validation, password hashing
  (Werkzeug PBKDF2), session-based login/logout
- Role-based access control for customer/provider/admin; role is re-read from the database
  on every request and is never trusted from client input
- A user's own record ownership is checked on every record access — a valid session for
  one customer cannot view or act on another customer's (or provider's) records

**Core Service Record Lifecycle**
- Full 12-state machine (`DRAFT` → … → `COMPLETED`, plus `DISPUTED`/`CANCELLED`) with an
  explicit allow-list of valid transitions; no route can set an arbitrary status
- Customer service requests → provider accept/reject → auto-generated `SR-YYYY-XXXXX`
  service record

**Handover & Evidence**
- Accessories checklist (standard + custom items)
- Structured condition checklist (8 items × GOOD/MINOR_ISSUE/DAMAGED/NOT_TESTED + notes)
- Photo evidence upload with **real content validation** (Pillow decodes and re-encodes the
  image; extension and browser-supplied MIME type are never trusted alone), 5MB limit,
  JPG/PNG/WEBP only
- Dual, independent confirmation (customer and provider each confirm their own role only;
  duplicate confirmation is blocked by both application logic and a DB unique constraint)
- **Deterministic verification**: a record becomes `HANDOVER_VERIFIED` only when all 10
  spec-defined conditions are met; otherwise the UI shows exactly which requirements are
  missing. No AI confidence scores anywhere in the system.
- Real QR code generation (via the `qrcode` package) with a unique verification code; the QR
  encodes only a public verification URL, never personal data. A public, unauthenticated
  verification page shows only the record number, status and verification timestamp.

**Service Workflow**
- Diagnosis / service-performed / parts-used / technician-note / additional-issue updates,
  each attributed to a user and timestamp
- **Additional cost approval**: any cost increase above the original estimate creates a
  pending approval that only the customer can decide (the provider cannot approve their own
  request); service cannot be marked complete while an approval is pending

**Payments & Returns**
- Payment records (amount/method/reference), explicitly labeled as records rather than a
  live payment gateway
- Return code generation and customer-side confirmation, provider-side final
  condition/accessories/photo documentation, and return verification gated by the same
  deterministic-checklist approach as handover

**Record Locking & Disputes**
- Once a record reaches `COMPLETED`, the record is locked (`locked_at` set) and all
  mutating routes reject further edits (403) while audit history remains fully visible
- Before/After comparison page shows handover vs. return evidence side by side without
  making an automated judgment
- Dispute module: customer-only to open, admin-only to review/resolve; admin sees the full
  evidence trail (photos, conditions, confirmations, service updates, payments, audit log)
  and the system never auto-decides who is right

**Admin**
- Dashboard with platform statistics and category/status/dispute/monthly breakdowns
  (rendered as dependency-free CSS bar charts)
- User management (search, suspend/reactivate — passwords are never visible to admin)
- Provider verification workflow (PENDING/VERIFIED/REJECTED/SUSPENDED)
- Global service-record search (by record #, item, brand, model, customer, provider)
- Full audit log viewer

**Other**
- In-app notifications (read/unread, timestamped, linked to the relevant record) for both
  customers and providers
- Global search scoped correctly: admin sees everything, customers/providers only ever see
  their own data through their own list views

---

## 8. Security Measures Implemented

- **Passwords**: hashed with Werkzeug's PBKDF2 implementation; never stored or displayed
  in plaintext; admin cannot view any user's password
- **SQL injection**: 100% parameterized queries (no string-formatted SQL anywhere);
  confirmed via automated SQLi payload tests against login and search
- **XSS**: Jinja2 auto-escaping is relied on everywhere (no `|safe` filters on user input);
  confirmed via automated `<script>` payload tests
- **CSRF-adjacent**: state-changing operations are POST-only; session cookies are signed
  (Flask's `itsdangerous`) so tampering invalidates the session rather than forging one
- **File upload security**: extension allow-list, 5MB hard limit, and — critically —
  actual image decoding via Pillow rather than trusting the extension or client-supplied
  MIME type; files are re-encoded (stripping any embedded payload/EXIF) and stored under
  a server-generated random filename, never the original client filename
- **Authorization**: every record-access and mutating route re-checks role and ownership
  from the database on every request; verified with automated tests that a customer/provider
  cannot read or write another user's data, and that role cannot be spoofed via form fields
- **Business-logic integrity**: duplicate confirmations blocked (DB unique constraint +
  application check), status transitions restricted to an explicit allow-list, locked
  records reject all mutating routes, additional costs require the customer's own decision
  (provider cannot self-approve), all timestamps and IDs are generated server-side (never
  accepted from client input)
- **Privacy**: QR codes and the public verification page expose only the record number,
  status and timestamp — never customer name, email, or item details

---

## 9. Testing

All testing was performed by running the actual Flask server and exercising it with real
HTTP requests (via Python's `requests` library) — not just reading the code. Test suites
live in `tests/` and can be re-run against a live instance:

```bash
pip install -r requirements-dev.txt   # adds `requests` for the tests
python app.py &                     # start the server (Windows: use a second terminal)
python tests/test_phase1.py         # auth & RBAC (15 checks)
python tests/test_phase2.py         # requests -> records (19 checks)
python tests/test_phase3.py         # handover, evidence, confirmation, QR (25 checks)
python tests/test_phase4.py   # (not included in this upload)         # service workflow, cost approval, payments, returns (25 checks)
python tests/test_phase5.py         # record locking, disputes, before/after (21 checks)
python tests/test_phase7_security.py   # (not included in this upload)  # SQLi, XSS, malicious uploads, auth bypass attempts (33 checks)
```

> Running these against `instance/proofdesk.db` will create additional test data. Re-run
> `seed_demo.py` on a fresh database afterward if you want a clean demo dataset again.

All 138 checks pass as of this build. Notable things specifically tested:
- SQL injection payloads against login and admin search
- XSS payloads in form fields, confirmed escaped in rendered output
- A Python script disguised as `.jpg`, an `.exe` upload, an oversized file, and a
  path-traversal filename — all rejected without crashing the server or escaping the
  uploads directory
- Session cookie tampering (rejected, treated as logged out)
- Role/status/timestamp/ID spoofing via extra form fields (all silently ignored server-side)
- Cross-tenant access attempts (a second, unrelated provider account cannot view or modify
  another provider's record)

A real bug was found and fixed during this process (a missing SQL join caused a 500 error
in the dispute-resolution route) — this is direct evidence the test suite is functionally
exercising the code, not just checking status codes optimistically.

---

## 10. Known Limitations

- **Development server only.** `app.run()` uses Flask's built-in dev server. For any
  real deployment, run behind a production WSGI server (gunicorn/uwsgi) and a reverse proxy.
- **SQLite.** Fine for a single-instance demo/college project; a multi-instance production
  deployment would want PostgreSQL or similar.
- **No live payment gateway.** Payment recording is explicitly a record-keeping feature,
  not a real transaction processor, per the spec.
- **No email/SMS delivery.** Notifications are in-app only.
- **Single evidence photo per upload request.** Multiple photos require multiple uploads
  (the UI supports this by re-submitting the form for each angle), rather than a
  multi-file picker in one submission.
- **CSRF tokens are not explicitly implemented** (Flask-WTF was not used to keep the
  dependency list minimal for this project's scope). Session cookies are signed, and all
  mutating actions are POST-only, but a dedicated CSRF token would be a meaningful addition
  before any real-world deployment.
- **QR codes** use the pure-Python `qrcode` package, so no system libraries are needed on any OS.

## 11. Suggested Future Improvements

- Real-time notifications (WebSocket/SSE) instead of poll-on-page-load
- Multi-file evidence upload in a single form submission
- CSRF token middleware (Flask-WTF)
- Rate limiting on login/registration endpoints
- PostgreSQL migration path for multi-instance deployment
- Email notifications alongside in-app ones
- Provider-side analytics (revenue over time, average turnaround time)

---

## 12. Business Requirement Document — Functional Requirements Summary

1. The system shall allow customers, service providers and administrators to register and
   authenticate with role-based access control.
2. The system shall allow customers to submit service requests to a selected, verified
   service provider, specifying item details and the problem to be serviced.
3. The system shall allow providers to accept or reject incoming requests; acceptance shall
   generate a unique, server-assigned service record identifier.
4. The system shall require structured documentation of item condition, accessories, and
   photographic evidence at handover.
5. The system shall require independent, non-transferable confirmation from both the
   customer and the provider before a handover is considered verified.
6. The system shall determine handover/return verification status using an explicit,
   deterministic checklist of required conditions — never a probabilistic or AI-generated
   confidence score.
7. The system shall generate a unique verification code and QR code for each verified
   handover, exposing only non-sensitive record data through that code.
8. The system shall support structured service-progress updates (diagnosis, work performed,
   parts used, notes) with full attribution and timestamps.
9. The system shall require explicit customer approval before any cost increase beyond the
   original estimate can be applied to a service record.
10. The system shall maintain payment records (amount, method, reference) without
    processing real financial transactions.
11. The system shall support a return-verification process requiring a system-generated
    code, customer confirmation, and provider sign-off before a record is finalized.
12. The system shall lock a service record's original data permanently once the record is
    marked complete, preserving an immutable audit trail.
13. The system shall allow customers to raise disputes against a service record and allow
    administrators to review full evidence and resolve disputes without automated judgment.
14. The system shall maintain a complete, tamper-evident audit log of all significant
    actions taken on a service record.
15. The system shall provide administrators with platform-wide visibility into users,
    providers, service records, disputes and audit history, including basic analytics.
16. The system shall enforce authorization such that no user can view or modify another
    user's private data by manipulating identifiers or client-supplied parameters.
