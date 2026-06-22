"""Context-aware billing (services/billing.py). Pure logic — no DB needed."""

from services.billing import compute_bill


def _labels(bill):
    return [c["label"] for c in bill["charges"]]


def test_parcel_bill_splits_gst_into_cgst_sgst():
    """Parcel: service (10%) + GST split into CGST 2.5% + SGST 2.5%."""
    bill = compute_bill(1000)  # defaults: parcel, non-AC
    assert _labels(bill) == ["Service charge (10%)", "CGST (2.5%)", "SGST (2.5%)"]
    assert [round(c["amount"]) for c in bill["charges"]] == [100, 25, 25]
    assert round(bill["total"]) == 1150


def test_dine_in_non_ac_has_no_ac_charge():
    bill = compute_bill(1000, order_type="dine_in", is_ac=False)
    assert "AC charge (5%)" not in _labels(bill)
    assert round(bill["total"]) == 1150


def test_dine_in_ac_adds_ac_charge():
    bill = compute_bill(1000, order_type="dine_in", is_ac=True)
    assert _labels(bill) == ["Service charge (10%)", "AC charge (5%)", "CGST (2.5%)", "SGST (2.5%)"]
    assert round(bill["total"]) == 1200


def test_ac_charge_never_applies_to_parcel():
    """is_ac on a parcel order must not pull in the dine-in-only AC charge."""
    bill = compute_bill(1000, order_type="parcel", is_ac=True)
    assert "AC charge (5%)" not in _labels(bill)
    assert round(bill["total"]) == 1150


def test_charges_carry_rate_and_amount_shape():
    bill = compute_bill(200, order_type="dine_in", is_ac=True)
    for c in bill["charges"]:
        assert set(c) == {"label", "rate", "amount"}
    assert bill["subtotal"] == 200


def test_zero_subtotal():
    bill = compute_bill(0, order_type="dine_in", is_ac=True)
    assert bill["total"] == 0
    assert all(c["amount"] == 0 for c in bill["charges"])
