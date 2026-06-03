"""Tests for the delivery sphere-of-influence matching (DB-free)."""

import pytest

from db.models.service_area import ServiceArea
from services.service_area_service import ServiceAreaService


class _FakeRepo:
    """In-memory stand-in for ServiceAreaRepo."""

    def __init__(self, areas):
        self._areas = areas

    def list_all(self, active_only=False):
        return [a for a in self._areas if a.active or not active_only]


def _service():
    svc = ServiceAreaService.__new__(ServiceAreaService)
    svc.repo = _FakeRepo(
        [
            ServiceArea(name="Bandra West", pincode="400050",
                        aliases=["hill road", "linking road", "bandstand"], active=True),
            ServiceArea(name="Pali Hill", pincode="400050",
                        aliases=["pali", "pali naka"], active=True),
            ServiceArea(name="Khar West", pincode="400052",
                        aliases=["khar", "khar danda"], active=True),
            ServiceArea(name="Old Zone", pincode="400099",
                        aliases=["old"], active=False),  # disabled
        ]
    )
    return svc


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Pali Hill", True),
        ("pali naka", True),
        ("hill road, bandra", True),
        ("bandstand", True),
        ("400050", True),
        ("400052", True),
        ("khar danda", True),
        ("Andheri", False),
        ("Juhu", False),
        ("400099", False),   # matches only a disabled area
        ("400088", False),   # unknown pincode
        ("", False),
    ],
)
def test_is_serviceable(query, expected):
    ok, _area = _service().is_serviceable(query)
    assert ok is expected


def test_disabled_area_not_matched_by_name():
    ok, area = _service().is_serviceable("old")
    assert ok is False
    assert area is None


def test_returns_matched_area():
    ok, area = _service().is_serviceable("pali")
    assert ok is True
    assert area.name == "Pali Hill"
