"""A voice caller must prove who they are before a customer record is theirs.

Anyone can dial in and say a phone number or guess a 4-digit code, so lookup
needs the name and delivery pincode (or area) on file too, a failed attempt
must not reveal whether the number exists, and registering an existing number
must not sign the caller in as that customer.
"""

import asyncio
import contextlib
import uuid

import pytest

from agent.session_state import CallSession
from pipeline import voice_pipeline
from services.customer_service import CustomerService


def _customer(db, **over):
    fields = dict(name="Priya Sharma", phone=f"98{uuid.uuid4().int % 10**8:08d}",
                  address_line="12 Pali Hill Road", area="Bandra West", pincode="400050",
                  allergies="peanuts")
    fields.update(over)
    return CustomerService(db).create_customer(**fields)


# --- service: verify ---------------------------------------------------------

def test_verify_needs_matching_name_and_pincode(db):
    c = _customer(db)
    svc = CustomerService(db)
    assert svc.verify(c.phone, name="Priya", place="400050") == c
    assert svc.verify(c.code, name="priya sharma", place="400 050") == c
    assert svc.verify(c.phone, name="Rahul", place="400050") is None
    assert svc.verify(c.phone, name="Priya", place="400001") is None
    assert svc.verify(c.phone, name="", place="") is None


def test_verify_accepts_the_area_when_no_pincode_is_on_file(db):
    c = _customer(db, pincode=None)
    assert CustomerService(db).verify(c.phone, name="Priya", place="bandra west") == c


# --- voice tools -------------------------------------------------------------

class _Params:
    """Minimal stand-in for Pipecat's FunctionCallParams."""

    def __init__(self):
        self.results, self.frames = [], []
        self.llm = self

    async def push_frame(self, frame):
        self.frames.append(frame.message)

    async def result_callback(self, text):
        self.results.append(text)


@pytest.fixture
def tools(db, monkeypatch):
    @contextlib.contextmanager
    def test_session():
        yield db

    monkeypatch.setattr(voice_pipeline, "get_session", test_session)
    session = CallSession()
    fns = {f.__name__: f for f in voice_pipeline._make_tool_wrappers(session, "Asia/Kolkata")}
    return session, fns


def _call(fn, **kwargs):
    p = _Params()
    asyncio.run(fn(p, **kwargs))
    return p


def test_lookup_by_phone_alone_does_not_identify(tools, db):
    session, fns = tools
    c = _customer(db)
    p = _call(fns["pc_lookup_customer"], code_or_phone=c.phone, name="", pincode_or_area="")
    assert not session.is_identified
    assert "12 Pali Hill" not in " ".join(p.results)


def test_wrong_details_look_the_same_as_an_unknown_number(tools, db):
    session, fns = tools
    c = _customer(db)
    wrong = _call(fns["pc_lookup_customer"], code_or_phone=c.phone, name="Rahul", pincode_or_area="400050")
    unknown = _call(fns["pc_lookup_customer"], code_or_phone="9000000000", name="Rahul", pincode_or_area="400050")
    assert not session.is_identified
    assert wrong.results == unknown.results
    assert not wrong.frames  # no customer card


def test_verified_lookup_identifies_without_exposing_address_or_phone(tools, db):
    session, fns = tools
    c = _customer(db)
    p = _call(fns["pc_lookup_customer"], code_or_phone=c.phone, name="Priya", pincode_or_area="400050")
    assert session.customer_id == c.id
    card = p.frames[0]["data"]
    assert card["address_line"] is None and card["landmark"] is None
    assert c.phone not in str(card)
    spoken = " ".join(p.results)
    assert "12 Pali Hill" not in spoken and c.phone not in spoken


def test_lookups_stop_after_three_failures(tools, db):
    session, fns = tools
    c = _customer(db)
    for name in ("A", "B", "C"):
        _call(fns["pc_lookup_customer"], code_or_phone=c.phone, name=name, pincode_or_area="400050")
    p = _call(fns["pc_lookup_customer"], code_or_phone=c.phone, name="Priya", pincode_or_area="400050")
    assert not session.is_identified


def test_registering_an_existing_number_does_not_sign_in(tools, db):
    from db.seeds.areas_seed import seed_service_areas

    seed_service_areas(db)  # so registration gets past the delivery-area check
    session, fns = tools
    c = _customer(db)
    p = _call(fns["pc_register_customer"], name="Mallory", phone=c.phone,
              address="1 Other St", area="Bandra West", pincode="400050")
    assert not session.is_identified
    assert c.code not in " ".join(p.results)


def test_dine_in_needs_the_table_qr(db, monkeypatch):
    from services.order_lifecycle import OrderType

    session = CallSession(order_type=OrderType.DINE_IN)  # QR didn't resolve: not seated
    names = {f.__name__ for f in voice_pipeline._make_tool_wrappers(session, "Asia/Kolkata")}
    assert "pc_request_bill" in names  # it is the dine-in tool set
    assert "pc_set_table" not in names  # no binding to a table by saying its number
