"""Demo data seeder — populates a realistic week+ of business for demos.

NOT run on startup. Invoke manually:

    cd server && uv run python -m db.seeds.demo_seed          # seed
    cd server && uv run python -m db.seeds.demo_seed --force  # re-seed

Creates ~30 days of paid dine-in + parcel orders (varied dishes, zones, hours)
so the analytics dashboards show real trends, plus a handful of *live* orders
and open table sessions so the Kitchen board and Floor map are populated. Bills
are frozen with the same context-aware billing the app uses. Backdated orders
are written directly (bypassing the lifecycle) so timestamps land in the past.

Idempotent: refuses to run twice unless --force (guarded by an app_settings key).
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

_IST = ZoneInfo("Asia/Kolkata")


def _utc_for_ist(day: datetime, hour: int, minute: int) -> datetime:
    """Naive-UTC timestamp for a given IST service hour on `day`'s date.

    Orders are stored as naive UTC; the dashboards convert back to IST. So a
    realistic "8 PM IST dinner" must be stored as its UTC equivalent.
    """
    ist_dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=_IST)
    return ist_dt.astimezone(timezone.utc).replace(tzinfo=None)

from db.base import get_session
from db.models.app_setting import AppSetting
from db.models.customer import Customer
from db.models.order import Order, OrderItem
from db.models.table_session import TableSession
from services.billing import compute_bill

# Running standalone (python -m), import every FK-target model so SQLAlchemy can
# resolve Order's foreign keys at flush time (the app loads these via startup).
import db.models.user  # noqa: F401, E402
import db.models.menu  # noqa: F401, E402
import db.models.chat  # noqa: F401, E402

_MARKER = "demo_seeded"
_DAYS = 30
_SEED = 4821  # deterministic runs


def _available_menu(db):
    from db.models.menu import MenuItem

    return db.query(MenuItem).filter(MenuItem.available == True).all()  # noqa: E712


def _tables(db):
    from db.models.restaurant_table import RestaurantTable
    from db.models.dining_zone import DiningZone

    rows = db.query(RestaurantTable).filter(RestaurantTable.active == True).all()  # noqa: E712
    zones = {z.id: z for z in db.query(DiningZone).all()}
    return [(t, zones.get(t.zone_id)) for t in rows]


def _ensure_customers(db, n=6) -> list[Customer]:
    names = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sara", "Vivaan", "Anaya"]
    out = []
    for i in range(n):
        code = f"70{i:02d}"
        cust = db.query(Customer).filter(Customer.code == code).first()
        if not cust:
            cust = Customer(
                code=code,
                name=random.choice(names),
                phone=f"9{random.randint(100000000, 999999999)}",
                area="Bandra West",
                pincode="400050",
            )
            db.add(cust)
        out.append(cust)
    db.flush()
    return out


def _make_order(db, menu, *, order_type, status, when, table=None, zone=None, customer=None):
    """Build a fully-formed order with backdated timestamps + frozen bill."""
    lines = random.sample(menu, k=random.randint(1, 4))
    is_ac = bool(zone.is_ac) if zone else False
    order = Order(
        order_type=order_type,
        status=status,
        customer_id=customer.id if customer else None,
        table_id=table.id if table else None,
        zone_name=zone.name if zone else None,
        is_ac=is_ac,
        created_at=when,
        updated_at=when,
    )
    if order_type == "parcel" and customer:
        order.contact_name = customer.name
        order.contact_phone = customer.phone
        order.delivery_address = "Flat, Bandra West"
        order.delivery_area = customer.area
        order.delivery_pincode = customer.pincode
    db.add(order)
    db.flush()

    subtotal = 0.0
    for mi in lines:
        qty = random.randint(1, 3)
        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=mi.id,
                quantity=qty,
                price_at_order=float(mi.price),
                created_at=when,
            )
        )
        subtotal += float(mi.price) * qty

    bill = compute_bill(subtotal, order_type=order_type, is_ac=is_ac)
    order.charges_json = bill["charges"]
    order.total = bill["total"]
    order.confirmed_at = when
    if status == "paid":
        order.paid_at = when + timedelta(minutes=random.randint(30, 90))
    db.flush()
    return order


def seed_demo(force: bool = False) -> None:
    random.seed(_SEED)
    with get_session() as db:
        marker = db.get(AppSetting, _MARKER)
        if marker and not force:
            logger.info("Demo data already seeded — pass --force to re-seed.")
            return

        menu = _available_menu(db)
        tables = _tables(db)
        if not menu or not tables:
            logger.error("Seed the menu + floor first (run the app once).")
            return
        customers = _ensure_customers(db)

        now = datetime.utcnow()
        n_hist = 0
        # --- 30 days of paid history ---
        for d in range(_DAYS, 0, -1):
            day = now - timedelta(days=d)
            for _ in range(random.randint(3, 6)):  # parcel (IST service hours)
                hour = random.choice([11, 12, 13, 14, 19, 20, 21, 22])
                when = _utc_for_ist(day, hour, random.randint(0, 59))
                _make_order(db, menu, order_type="parcel", status="paid", when=when,
                            customer=random.choice(customers))
                n_hist += 1
            for _ in range(random.randint(2, 4)):  # dine-in (IST service hours)
                hour = random.choice([12, 13, 14, 20, 21, 22])
                when = _utc_for_ist(day, hour, random.randint(0, 59))
                table, zone = random.choice(tables)
                _make_order(db, menu, order_type="dine_in", status="paid", when=when,
                            table=table, zone=zone)
                n_hist += 1

        # --- live orders for the Kitchen board ---
        live_parcel = ["cooking", "ready", "delivered"]
        for st in live_parcel:
            _make_order(db, menu, order_type="parcel", status=st,
                        when=now - timedelta(minutes=random.randint(5, 40)),
                        customer=random.choice(customers))

        # --- a few open dine-in tables for the Floor map ---
        from db.repositories.table_repo import TableRepo

        used = random.sample(tables, k=min(3, len(tables)))
        for idx, (table, zone) in enumerate(used):
            sess = TableSession(
                table_id=table.id,
                status="billed" if idx == 0 else "open",
                party_size=random.randint(2, 5),
                opened_at=now - timedelta(minutes=random.randint(15, 70)),
            )
            db.add(sess)
            db.flush()
            order = _make_order(
                db, menu, order_type="dine_in",
                status=random.choice(["confirmed", "cooking", "served"]),
                when=sess.opened_at, table=table, zone=zone,
            )
            order.table_session_id = sess.id
            TableRepo(db).update(table.id, status="needs_bill" if idx == 0 else "occupied")
        db.flush()

        if marker:
            marker.value = {"at": now.isoformat()}
        else:
            db.add(AppSetting(key=_MARKER, value={"at": now.isoformat()}))
        db.flush()
        logger.info(
            f"Demo seeded: {n_hist} paid history orders + {len(live_parcel)} live "
            f"parcel + {len(used)} open dine-in tables."
        )


if __name__ == "__main__":
    seed_demo(force="--force" in sys.argv)
