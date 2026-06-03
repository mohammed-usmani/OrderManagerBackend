"""Tests for customer phone normalization (DB-free)."""

import pytest

from services.customer_service import normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+91 98200 12345", "9820012345"),
        ("098200-12345", "9820012345"),
        ("9820012345", "9820012345"),
        ("91 9820012345", "9820012345"),
        ("(98200) 12345", "9820012345"),
        ("", None),
        (None, None),
        ("   ", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected
