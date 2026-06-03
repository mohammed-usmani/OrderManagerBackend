"""Service-area service: the delivery sphere-of-influence check.

`is_serviceable` is what the agent calls before taking a parcel order. It
matches a customer's spoken area or pincode against the admin-managed
allowlist (name + aliases + pincode), tolerant of casing and partial phrasing.
"""

import re

from sqlalchemy.orm import Session

from db.models.service_area import ServiceArea
from db.repositories.service_area_repo import ServiceAreaRepo


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


class ServiceAreaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ServiceAreaRepo(db)

    def list_areas(self, active_only: bool = False) -> list[ServiceArea]:
        return self.repo.list_all(active_only=active_only)

    def is_serviceable(self, area_or_pincode: str) -> tuple[bool, ServiceArea | None]:
        """Return (serviceable, matched_area).

        - A 6-digit token is treated as a pincode and matched exactly.
        - Otherwise the text is matched against each active area's name and
          aliases, in both directions (so "pali" matches "Pali Hill" and
          "bandra west" matches "Bandra").
        """
        token = _norm(area_or_pincode)
        if not token:
            return (False, None)

        areas = self.repo.list_all(active_only=True)

        # Pincode path.
        digits = re.sub(r"\D", "", token)
        if len(digits) == 6:
            for area in areas:
                if area.pincode and re.sub(r"\D", "", area.pincode) == digits:
                    return (True, area)
            # A 6-digit pincode with no match is decisively out of range.
            return (False, None)

        # Name / alias path. Substring either direction so partial spoken
        # phrasing still matches.
        for area in areas:
            candidates = [_norm(area.name)] + [_norm(a) for a in (area.aliases or [])]
            for cand in candidates:
                if not cand:
                    continue
                if cand in token or token in cand:
                    return (True, area)
        return (False, None)

    # --- Admin CRUD ---

    def get_area(self, area_id: str) -> ServiceArea:
        area = self.repo.get_by_id(area_id)
        if not area:
            raise ValueError(f"Service area '{area_id}' not found")
        return area

    def create_area(self, **kwargs) -> ServiceArea:
        return self.repo.create(**kwargs)

    def update_area(self, area_id: str, **kwargs) -> ServiceArea:
        clean = {k: v for k, v in kwargs.items() if v is not None}
        area = self.repo.update(area_id, **clean)
        if not area:
            raise ValueError(f"Service area '{area_id}' not found")
        return area

    def delete_area(self, area_id: str) -> None:
        if not self.repo.delete(area_id):
            raise ValueError(f"Service area '{area_id}' not found")
