"""Staff role constants + helpers (single source of truth for RBAC)."""

OWNER = "owner"
MANAGER = "manager"
CASHIER = "cashier"
WAITER = "waiter"
CHEF = "chef"

# Non-staff (e.g. legacy/public registrants) — no admin-panel access.
NONE = "none"

# Every role that can access the back-office at all.
STAFF_ROLES = {OWNER, MANAGER, CASHIER, WAITER, CHEF}
# Roles with full management access (kept in sync with the is_admin flag).
ADMIN_ROLES = {OWNER, MANAGER}
# Roles allowed to settle / take payment.
CASHIER_ROLES = {OWNER, MANAGER, CASHIER}
# Roles allowed to manage staff.
OWNER_ROLES = {OWNER, MANAGER}

ALL_ROLES = STAFF_ROLES | {NONE}


def is_admin_role(role: str | None) -> bool:
    return (role or "") in ADMIN_ROLES
