-- ProofDesk database schema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer','provider','admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS service_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    business_name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    contact_phone TEXT,
    address TEXT,
    operating_hours TEXT,
    verification_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (verification_status IN ('PENDING','VERIFIED','REJECTED','SUSPENDED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS service_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES users(id),
    provider_id INTEGER NOT NULL REFERENCES service_providers(id),
    category TEXT NOT NULL,
    item_name TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    serial_number TEXT,
    problem_description TEXT NOT NULL,
    preferred_service TEXT,
    expected_completion_date TEXT,
    additional_notes TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','ACCEPTED','REJECTED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS service_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_request_id INTEGER NOT NULL REFERENCES service_requests(id),
    customer_id INTEGER NOT NULL REFERENCES users(id),
    provider_id INTEGER NOT NULL REFERENCES service_providers(id),
    record_number TEXT NOT NULL UNIQUE,
    item_name TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    serial_number TEXT,
    problem_description TEXT NOT NULL,
    estimated_cost REAL NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
    final_cost REAL CHECK (final_cost IS NULL OR final_cost >= 0),
    expected_completion_date TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT','HANDOVER_PENDING','HANDOVER_VERIFIED','SERVICE_IN_PROGRESS',
        'SERVICE_COMPLETED','PAYMENT_PENDING','READY_FOR_RETURN','RETURN_PENDING',
        'RETURN_VERIFIED','COMPLETED','DISPUTED','CANCELLED'
    )),
    verification_code TEXT UNIQUE,
    return_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    locked_at TEXT
);

CREATE TABLE IF NOT EXISTS accessories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    name TEXT NOT NULL,
    received INTEGER NOT NULL DEFAULT 0,
    returned INTEGER
);

CREATE TABLE IF NOT EXISTS condition_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    stage TEXT NOT NULL CHECK (stage IN ('HANDOVER','RETURN')),
    condition_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('GOOD','MINOR_ISSUE','DAMAGED','NOT_TESTED')),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS evidence_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    stage TEXT NOT NULL CHECK (stage IN ('HANDOVER','RETURN','DISPUTE')),
    angle TEXT,
    file_reference TEXT NOT NULL,
    file_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('customer','provider')),
    confirmation_type TEXT NOT NULL CHECK (confirmation_type IN ('HANDOVER','RETURN')),
    confirmed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(service_record_id, role, confirmation_type)
);

CREATE TABLE IF NOT EXISTS service_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    update_type TEXT NOT NULL CHECK (update_type IN (
        'DIAGNOSIS','SERVICE_PERFORMED','PARTS_USED','TECHNICIAN_NOTE','ADDITIONAL_ISSUE'
    )),
    description TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS cost_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    original_cost REAL NOT NULL,
    additional_cost REAL NOT NULL CHECK (additional_cost >= 0),
    total_cost REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','DECLINED')),
    approved_by INTEGER REFERENCES users(id),
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    amount REAL NOT NULL CHECK (amount >= 0),
    method TEXT NOT NULL,
    reference TEXT,
    status TEXT NOT NULL DEFAULT 'UNPAID' CHECK (status IN ('UNPAID','PAYMENT_PENDING','PAID','REFUNDED')),
    recorded_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL UNIQUE REFERENCES service_records(id),
    returned_by INTEGER REFERENCES users(id),
    received_by INTEGER REFERENCES users(id),
    condition_summary TEXT,
    return_code TEXT,
    returned_at TEXT,
    verified_at TEXT
);

CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER NOT NULL REFERENCES service_records(id),
    opened_by INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL CHECK (category IN (
        'MISSING_ACCESSORY','CONDITION_DISAGREEMENT','ITEM_NOT_RETURNED',
        'INCORRECT_SERVICE','INCORRECT_CHARGE','OTHER'
    )),
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','UNDER_REVIEW','CLOSED')),
    resolution TEXT,
    previous_status TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_record_id INTEGER REFERENCES service_records(id),
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    service_record_id INTEGER REFERENCES service_records(id),
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_records_customer ON service_records(customer_id);
CREATE INDEX IF NOT EXISTS idx_records_provider ON service_records(provider_id);
CREATE INDEX IF NOT EXISTS idx_records_status ON service_records(status);
CREATE INDEX IF NOT EXISTS idx_requests_customer ON service_requests(customer_id);
CREATE INDEX IF NOT EXISTS idx_requests_provider ON service_requests(provider_id);
CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_logs(service_record_id);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_evidence_record ON evidence_files(service_record_id);
