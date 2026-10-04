"""
Deterministic verification engine.

Verification status is NEVER an AI confidence score. It is a checklist of
explicit, server-checkable facts about the database state. Either every
required condition is present (VERIFIED) or it is not (INCOMPLETE), and the
UI must show exactly which requirements are missing.
"""
from db import query_one, query_all


def check_handover_requirements(record_id):
    """
    Returns (is_verified: bool, satisfied: list[str], missing: list[str])
    Requirements map 1:1 to spec section 4.
    """
    record = query_one("SELECT * FROM service_records WHERE id = ?", (record_id,))
    results = []  # (label, ok: bool)

    # 1 & 2: both parties are authenticated users tied to the record (always true
    # once record exists, since FK requires real user ids) -- included for completeness
    results.append(("Customer identity on record", record["customer_id"] is not None))
    results.append(("Service provider identity on record", record["provider_id"] is not None))

    # 3: item details entered
    item_ok = bool(record["item_name"]) and bool(record["problem_description"])
    results.append(("Item details entered", item_ok))

    # 4: required condition checklist completed (at least one condition entry at handover)
    conditions = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id = ? AND stage = 'HANDOVER'",
        (record_id,),
    )
    results.append(("Condition checklist completed", len(conditions) > 0))

    # 5: required accessories checklist completed (at least one accessory row recorded,
    # i.e. provider has gone through the checklist even if all are NO)
    accessories = query_all(
        "SELECT * FROM accessories WHERE service_record_id = ?", (record_id,)
    )
    results.append(("Accessories checklist completed", len(accessories) > 0))

    # 6: required photographs uploaded (at least 1 handover photo)
    photos = query_all(
        "SELECT * FROM evidence_files WHERE service_record_id = ? AND stage = 'HANDOVER'",
        (record_id,),
    )
    results.append(("Condition photograph(s) uploaded", len(photos) > 0))

    # 7 & 8: both confirmations present
    cust_conf = query_one(
        "SELECT * FROM confirmations WHERE service_record_id = ? AND role='customer' AND confirmation_type='HANDOVER'",
        (record_id,),
    )
    prov_conf = query_one(
        "SELECT * FROM confirmations WHERE service_record_id = ? AND role='provider' AND confirmation_type='HANDOVER'",
        (record_id,),
    )
    results.append(("Customer confirmation", cust_conf is not None))
    results.append(("Service provider confirmation", prov_conf is not None))

    # 9: server timestamp exists (created_at always server-set)
    results.append(("Server-generated timestamp recorded", bool(record["created_at"])))

    # 10: unique service record id exists
    results.append(("Unique service record ID", bool(record["record_number"])))

    missing = [label for label, ok in results if not ok]
    satisfied = [label for label, ok in results if ok]
    is_verified = len(missing) == 0
    return is_verified, satisfied, missing


def check_return_requirements(record_id):
    record = query_one("SELECT * FROM service_records WHERE id = ?", (record_id,))
    results = []

    ret = query_one("SELECT * FROM returns WHERE service_record_id = ?", (record_id,))
    results.append(("Return initiated by provider", ret is not None))
    results.append(("Return code generated", ret is not None and bool(ret["return_code"])))
    results.append(("Return code confirmed by customer", ret is not None and bool(ret["returned_at"])))

    conditions = query_all(
        "SELECT * FROM condition_reports WHERE service_record_id = ? AND stage = 'RETURN'",
        (record_id,),
    )
    results.append(("Final condition recorded", len(conditions) > 0))

    accessories = query_all(
        "SELECT * FROM accessories WHERE service_record_id = ? AND returned IS NOT NULL",
        (record_id,),
    )
    results.append(("Returned accessories recorded", len(accessories) > 0))

    results.append(("Provider return verification", ret is not None and bool(ret["verified_at"])))

    missing = [label for label, ok in results if not ok]
    satisfied = [label for label, ok in results if ok]
    is_verified = len(missing) == 0
    return is_verified, satisfied, missing
