"""
Deterministic, server-enforced state machine for service records.
No user (customer, provider or admin) may set status directly;
all transitions must go through `transition`.
"""

ALLOWED_TRANSITIONS = {
    "DRAFT": {"HANDOVER_PENDING", "CANCELLED"},
    "HANDOVER_PENDING": {"HANDOVER_VERIFIED", "CANCELLED"},
    "HANDOVER_VERIFIED": {"SERVICE_IN_PROGRESS", "DISPUTED"},
    "SERVICE_IN_PROGRESS": {"SERVICE_COMPLETED", "DISPUTED"},
    "SERVICE_COMPLETED": {"PAYMENT_PENDING", "DISPUTED"},
    "PAYMENT_PENDING": {"READY_FOR_RETURN", "DISPUTED"},
    "READY_FOR_RETURN": {"RETURN_PENDING", "DISPUTED"},
    "RETURN_PENDING": {"RETURN_VERIFIED", "DISPUTED"},
    "RETURN_VERIFIED": {"COMPLETED", "DISPUTED"},
    "COMPLETED": {"DISPUTED"},  # locked for normal edits, but a dispute can still be opened
    "DISPUTED": {"HANDOVER_VERIFIED", "SERVICE_IN_PROGRESS", "SERVICE_COMPLETED",
                 "PAYMENT_PENDING", "READY_FOR_RETURN", "RETURN_PENDING", "RETURN_VERIFIED", "COMPLETED"},
    "CANCELLED": set(),
}


class InvalidTransitionError(Exception):
    pass


def can_transition(current_status, new_status):
    return new_status in ALLOWED_TRANSITIONS.get(current_status, set())


def assert_transition(current_status, new_status):
    if not can_transition(current_status, new_status):
        raise InvalidTransitionError(
            f"Cannot move service record from {current_status} to {new_status}."
        )
