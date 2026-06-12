"""Analytics router: richer business metrics for the admin analytics dashboard.

The compact dashboard summary stays in admin.py (`/admin/analytics/summary`);
these endpoints power the dedicated analytics page (splits, zones, time series,
peak hours).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from dependencies import require_admin
from services.analytics_service import RANGE_DAYS, AnalyticsService

router = APIRouter(prefix="/admin/analytics", tags=["analytics"])

_GRANULARITIES = {"day", "month", "year"}


def _check_range(range: str) -> None:
    if range not in RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range '{range}'. Valid: {sorted(RANGE_DAYS)}",
        )


class SplitBucket(BaseModel):
    orders: int
    revenue: float


class ZoneStat(BaseModel):
    zone: str
    orders: int
    revenue: float


class TopItem(BaseModel):
    menu_item_id: str
    name: str
    quantity: int
    revenue: float


class OverviewResponse(BaseModel):
    range: str
    range_start: datetime
    total_orders: int
    billable_orders: int
    orders_by_status: dict[str, int]
    revenue_subtotal: float
    revenue_total: float
    avg_ticket: float
    split: dict[str, SplitBucket]
    by_zone: list[ZoneStat]
    top_items: list[TopItem]
    dine_in_sessions: int
    active_tables: int
    table_turnover: float


class TimeseriesBucket(BaseModel):
    bucket: str
    orders: int
    revenue: float
    dine_in: float
    parcel: float


class PeakHour(BaseModel):
    hour: int
    orders: int
    revenue: float


@router.get("/overview", response_model=OverviewResponse)
def overview(
    range: str = Query("today", description="today | 7d | 30d | 90d | year | all"),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    _check_range(range)
    return AnalyticsService(db).overview(range)


@router.get("/timeseries", response_model=list[TimeseriesBucket])
def timeseries(
    range: str = Query("30d"),
    granularity: str = Query("day", description="day | month | year"),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    _check_range(range)
    if granularity not in _GRANULARITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid granularity '{granularity}'. Valid: {sorted(_GRANULARITIES)}",
        )
    return AnalyticsService(db).timeseries(range, granularity)


@router.get("/peak-hours", response_model=list[PeakHour])
def peak_hours(
    range: str = Query("30d"),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    _check_range(range)
    return AnalyticsService(db).peak_hours(range)
