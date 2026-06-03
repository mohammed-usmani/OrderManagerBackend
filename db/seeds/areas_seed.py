"""Seed the delivery sphere-of-influence around Saffron & Smoke.

Saffron & Smoke sits at 14 Hill Road, Bandra West (400050). These are the
localities within a sensible hot-food delivery radius, with spoken aliases the
agent's check_delivery_area matches against. Admins can edit/extend this list
from the admin panel afterwards.
"""

from loguru import logger

from db.models.service_area import ServiceArea
from db.repositories.service_area_repo import ServiceAreaRepo

# (name, pincode, [spoken aliases / sub-localities])
SERVICE_AREAS: list[tuple[str, str, list[str]]] = [
    (
        "Bandra West",
        "400050",
        [
            "bandra", "bandra w", "hill road", "linking road", "bandstand",
            "band stand", "chapel road", "turner road", "perry road",
            "mount mary", "bazaar road", "bandra reclamation", "sv road bandra",
            "waterfield road", "ranwar",
        ],
    ),
    ("Pali Hill", "400050", ["pali", "pali hill", "pali naka", "pali road", "union park"]),
    ("Carter Road", "400050", ["carter road", "carter rd", "joggers park", "jogger's park"]),
    (
        "Khar West",
        "400052",
        ["khar", "khar w", "khar danda", "khar colony", "khar pali", "linking road khar"],
    ),
    (
        "Santacruz West",
        "400054",
        ["santacruz", "santa cruz", "santacruz w", "milan subway"],
    ),
    (
        "Bandra East",
        "400051",
        ["bandra east", "bandra e", "kalanagar", "kala nagar", "government colony"],
    ),
    ("BKC", "400051", ["bkc", "bandra kurla complex", "bandra kurla"]),
]


def seed_service_areas(db) -> None:
    """Insert any missing service areas (idempotent by name)."""
    repo = ServiceAreaRepo(db)
    existing = {a.name for a in repo.list_all()}
    added = 0
    for name, pincode, aliases in SERVICE_AREAS:
        if name in existing:
            continue
        db.add(ServiceArea(name=name, pincode=pincode, aliases=aliases, active=True))
        added += 1
    if added:
        db.flush()
        logger.info(f"Seeded {added} service area(s)")
