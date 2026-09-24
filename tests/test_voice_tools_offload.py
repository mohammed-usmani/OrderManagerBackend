"""Voice tools must do database work off the event loop.

One asyncio loop streams audio for every live call, so a synchronous query run
on it stalls everyone's audio for the length of the round-trip.
"""

import asyncio
import contextlib
import threading

import pytest

from agent.session_state import CallSession
from pipeline import voice_pipeline


class _Params:
    def __init__(self):
        self.llm = self

    async def push_frame(self, frame):
        pass

    async def result_callback(self, text):
        pass


@pytest.fixture
def db_threads(db, monkeypatch):
    threads = []

    @contextlib.contextmanager
    def recording_session():
        threads.append(threading.get_ident())
        yield db

    monkeypatch.setattr(voice_pipeline, "get_session", recording_session)
    return threads


def _run(tool, **kwargs):
    fns = {f.__name__: f for f in voice_pipeline._make_tool_wrappers(CallSession(), "Asia/Kolkata")}
    loop_thread = []

    async def main():
        loop_thread.append(threading.get_ident())
        await fns[tool](_Params(), **kwargs)

    asyncio.run(main())
    return loop_thread[0]


@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        ("pc_search_menu", {"query": "paneer"}),
        ("pc_get_menu_categories", {}),
        ("pc_filter_menu", {"category": "mains"}),
        ("pc_lookup_customer", {"code_or_phone": "1234", "name": "A", "pincode_or_area": "400050"}),
        ("pc_check_delivery_area", {"area_or_pincode": "400050"}),
    ],
)
def test_tool_queries_run_off_the_event_loop(db_threads, tool, kwargs):
    loop_thread = _run(tool, **kwargs)
    assert db_threads, "tool never touched the database"
    assert loop_thread not in db_threads


def test_building_the_pipeline_does_no_database_work(monkeypatch):
    from unittest.mock import MagicMock

    def boom():
        raise AssertionError("create_pipeline queried the database on the event loop")

    monkeypatch.setattr(voice_pipeline, "GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(voice_pipeline, "get_session", boom)
    context = {"table": None, "hours": None, "timezone": None}
    pipeline, transport = voice_pipeline.create_pipeline(
        MagicMock(), user_timezone="Asia/Kolkata", table_token=None, call_context=context
    )
    assert pipeline is not None and transport is not None


def test_call_context_seats_a_scanned_table(db, monkeypatch):
    import uuid

    from services.table_service import TableService
    from services.zone_service import ZoneService

    @contextlib.contextmanager
    def test_session():
        yield db

    monkeypatch.setattr(voice_pipeline, "get_session", test_session)
    zone = ZoneService(db).create_zone(name=f"Z-{uuid.uuid4().hex[:5]}", is_ac=True)
    table = TableService(db).create_table(zone_id=zone.id, label="T9", seats=2)

    ctx = voice_pipeline.load_call_context(table.qr_token)
    assert ctx["table"]["label"] == "T9" and ctx["table"]["is_ac"] is True
    assert voice_pipeline.load_call_context("not-a-real-token")["table"] is None
