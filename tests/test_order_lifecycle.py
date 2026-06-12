"""Order lifecycle state machine (services/order_lifecycle.py). Pure logic."""

import pytest

from services import order_lifecycle as lc


def test_dine_in_happy_path():
    assert lc.can_transition("dine_in", "cart", "confirmed")
    assert lc.can_transition("dine_in", "confirmed", "cooking")
    assert lc.can_transition("dine_in", "cooking", "served")
    assert lc.can_transition("dine_in", "served", "paid")


def test_parcel_happy_path():
    assert lc.can_transition("parcel", "cart", "confirmed")
    assert lc.can_transition("parcel", "confirmed", "cooking")
    assert lc.can_transition("parcel", "cooking", "ready")
    assert lc.can_transition("parcel", "ready", "delivered")
    assert lc.can_transition("parcel", "delivered", "paid")


def test_flows_do_not_cross_contaminate():
    # 'served' is dine-in only; 'ready'/'delivered' are parcel only.
    assert not lc.can_transition("parcel", "cooking", "served")
    assert not lc.can_transition("dine_in", "cooking", "ready")
    assert not lc.can_transition("dine_in", "cooking", "delivered")


def test_cannot_skip_kitchen():
    assert not lc.can_transition("parcel", "confirmed", "paid")
    assert not lc.can_transition("dine_in", "confirmed", "paid")


def test_terminal_states_are_dead_ends():
    assert lc.allowed_next("parcel", "paid") == set()
    assert lc.allowed_next("dine_in", "cancelled") == set()
    assert not lc.can_transition("parcel", "paid", "cooking")


def test_cancellation_allowed_pre_payment_only():
    assert lc.can_transition("dine_in", "cooking", "cancelled")
    assert lc.can_transition("parcel", "ready", "cancelled")
    assert not lc.can_transition("dine_in", "served", "cancelled")  # served → only paid


def test_legacy_awaiting_payment_can_settle():
    # Old parcel rows may still hold this status; allow them to be paid.
    assert lc.can_transition("parcel", "awaiting_payment", "paid")


def test_assert_transition_raises_on_illegal():
    with pytest.raises(ValueError):
        lc.assert_transition("parcel", "confirmed", "paid")
    # legal one does not raise
    lc.assert_transition("parcel", "confirmed", "cooking")


def test_status_timestamp_mapping():
    assert lc.STATUS_TIMESTAMP["served"] == "served_at"
    assert lc.STATUS_TIMESTAMP["delivered"] == "delivered_at"
    assert lc.STATUS_TIMESTAMP["paid"] == "paid_at"
