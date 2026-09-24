"""Table service: floor tables, QR resolution, and the live floor map.

Also owns the dine-in seating helpers the voice flow will call in Phase 4
(opening a table session, creating a dine-in cart bound to a table). Those are
written here so the data rules live in one place.
"""

from collections import defaultdict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.repositories.floor_repo import FloorRepo
from db.repositories.order_repo import OrderRepo
from db.repositories.table_repo import TableRepo
from db.repositories.table_session_repo import TableSessionRepo
from db.repositories.zone_repo import ZoneRepo
from services import order_lifecycle as lifecycle
from services.billing import bill_for_order
from services.money import money_float


class TableService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TableRepo(db)
        self.zone_repo = ZoneRepo(db)
        self.floor_repo = FloorRepo(db)
        self.session_repo = TableSessionRepo(db)
        self.order_repo = OrderRepo(db)

    # --- CRUD ---

    def list_tables(self, zone_id: str | None = None, active_only: bool = False):
        return self.repo.list_all(zone_id=zone_id, active_only=active_only)

    def create_table(self, **kwargs):
        zone_id = kwargs.get("zone_id")
        if not self.zone_repo.get_by_id(zone_id):
            raise ValueError("Zone not found")
        return self.repo.create(**kwargs)

    def update_table(self, table_id: str, **kwargs):
        if "zone_id" in kwargs and not self.zone_repo.get_by_id(kwargs["zone_id"]):
            raise ValueError("Zone not found")
        table = self.repo.update(table_id, **kwargs)
        if not table:
            raise ValueError("Table not found")
        return table

    def delete_table(self, table_id: str) -> None:
        table = self.repo.get_by_id(table_id)
        if not table:
            raise ValueError("Table not found")
        if self.session_repo.get_open_for_table(table_id):
            raise ValueError("Table has an open session; settle it first")
        try:
            self.repo.delete(table_id)
        except IntegrityError:
            # Closed sessions / past orders still reference this table.
            self.db.rollback()
            raise ValueError(
                "Table has order history; deactivate it instead of deleting"
            )

    # --- QR resolution (public) ---

    def resolve_qr(self, qr_token: str) -> dict:
        """Resolve a scanned QR token → table + zone + floor context."""
        table = self.repo.get_by_qr_token(qr_token)
        if not table or not table.active:
            raise ValueError("Unknown or inactive table")
        zone = self.zone_repo.get_by_id(table.zone_id)
        if zone and not zone.active:
            raise ValueError("This section is not taking orders right now")
        floor = self.floor_repo.get_by_id(zone.floor_id) if zone and zone.floor_id else None
        if floor and not floor.active:
            raise ValueError("This floor is not taking orders right now")
        return {
            "table_id": table.id,
            "label": table.label,
            "seats": table.seats,
            "zone_id": zone.id if zone else None,
            "zone_name": zone.name if zone else None,
            "is_ac": bool(zone.is_ac) if zone else False,
            "floor_id": floor.id if floor else None,
            "floor_name": floor.name if floor else None,
        }

    # --- Live floor map ---

    def floor_map(self) -> list[dict]:
        """Floors → zones → tables (with live session) for the admin floor plan.

        Zones with no/unknown floor_id fall into a synthetic "Unassigned" bucket
        so nothing is ever hidden.
        """
        sessions = {s.table_id: s for s in self.session_repo.list_active()}
        zones_by_floor: dict[str | None, list] = defaultdict(list)
        for z in self.zone_repo.list_all():
            zones_by_floor[z.floor_id].append(z)
        # Prefetch ALL tables once and group by zone (avoids a query per zone).
        tables_by_zone: dict[str, list] = defaultdict(list)
        for t in self.repo.list_all():
            tables_by_zone[t.zone_id].append(t)

        out: list[dict] = []
        known: set[str] = set()
        for floor in self.floor_repo.list_all():
            known.add(floor.id)
            out.append(
                {
                    "id": floor.id,
                    "name": floor.name,
                    "display_order": floor.display_order,
                    "active": floor.active,
                    "width": floor.width,
                    "height": floor.height,
                    "zones": [
                        self._zone_dict(z, sessions, tables_by_zone.get(z.id, []))
                        for z in zones_by_floor.get(floor.id, [])
                    ],
                }
            )

        orphan = [z for fid, zs in zones_by_floor.items() if fid not in known for z in zs]
        if orphan:
            out.append(
                {
                    "id": None,
                    "name": "Unassigned",
                    "display_order": 9999,
                    "active": True,
                    "width": 1000,
                    "height": 640,
                    "zones": [
                        self._zone_dict(z, sessions, tables_by_zone.get(z.id, []))
                        for z in orphan
                    ],
                }
            )
        return out

    def _zone_dict(self, zone, sessions: dict, tables: list) -> dict:
        return {
            "id": zone.id,
            "name": zone.name,
            "is_ac": zone.is_ac,
            "display_order": zone.display_order,
            "active": zone.active,
            "pos_x": zone.pos_x,
            "pos_y": zone.pos_y,
            "width": zone.width,
            "height": zone.height,
            "tables": [
                {
                    "id": t.id,
                    "label": t.label,
                    "seats": t.seats,
                    "pos_x": t.pos_x,
                    "pos_y": t.pos_y,
                    "shape": t.shape,
                    "qr_token": t.qr_token,
                    "status": t.status,
                    "active": t.active,
                    "session": self._session_summary(sessions[t.id]) if t.id in sessions else None,
                }
                for t in sorted(tables, key=lambda x: x.label)
            ],
        }

    def save_positions(self, updates: list[dict]) -> int:
        """Bulk-apply table layout edits: [{table_id, pos_x, pos_y, shape?, zone_id?}].

        Skips unknown tables; validates any zone reassignment. Returns the count
        of tables updated.
        """
        n = 0
        for u in updates:
            table = self.repo.get_by_id(u.get("table_id"))
            if not table:
                continue
            if u.get("zone_id") is not None and not self.zone_repo.get_by_id(u["zone_id"]):
                raise ValueError(f"Zone '{u['zone_id']}' not found")
            for key in ("pos_x", "pos_y", "shape", "zone_id"):
                if key in u and u[key] is not None:
                    setattr(table, key, u[key])
            n += 1
        self.db.flush()
        return n

    # --- Table session detail / receipt ---

    def session_detail(self, session_id: str) -> dict:
        """Full running tab for a table session: every round with its bill and a
        combined grand total (the check)."""
        from db.repositories.menu_repo import MenuRepo

        sess = self.session_repo.get_by_id(session_id)
        if not sess:
            raise ValueError("Table session not found")
        table = self.repo.get_by_id(sess.table_id) if sess.table_id else None
        zone = self.zone_repo.get_by_id(table.zone_id) if table else None
        floor = self.floor_repo.get_by_id(zone.floor_id) if zone and zone.floor_id else None
        menu_repo = MenuRepo(self.db)

        orders_out: list[dict] = []
        grand_subtotal = grand_total = 0.0
        for o in self.order_repo.list_for_table_session(session_id):
            if o.status == "cancelled":
                continue
            bill = bill_for_order(o)
            items = []
            for it in o.items:
                mi = menu_repo.get_by_id(it.menu_item_id)
                items.append(
                    {
                        "name": mi.name if mi else it.menu_item_id,
                        "quantity": it.quantity,
                        "line_total": float(it.price_at_order) * it.quantity,
                    }
                )
            orders_out.append(
                {
                    "id": o.id,
                    "status": o.status,
                    "items": items,
                    "subtotal": bill["subtotal"],
                    "charges": bill["charges"],
                    "total": bill["total"],
                }
            )
            grand_subtotal += bill["subtotal"]
            grand_total += bill["total"]

        return {
            "id": sess.id,
            "status": sess.status,
            "opened_at": sess.opened_at.isoformat() if sess.opened_at else None,
            "closed_at": sess.closed_at.isoformat() if sess.closed_at else None,
            "party_size": sess.party_size,
            "table_label": table.label if table else None,
            "zone_name": zone.name if zone else None,
            "floor_name": floor.name if floor else None,
            "is_ac": bool(zone.is_ac) if zone else False,
            "orders": orders_out,
            "grand_subtotal": money_float(grand_subtotal),
            "grand_total": money_float(grand_total),
        }

    def _session_summary(self, sess) -> dict:
        orders = self.order_repo.list_for_table_session(sess.id)
        live = [o for o in orders if o.status not in lifecycle.CLOSED_STATUSES]
        running = money_float(sum(bill_for_order(o)["total"] for o in live))
        return {
            "id": sess.id,
            "status": sess.status,
            "opened_at": sess.opened_at.isoformat() if sess.opened_at else None,
            "party_size": sess.party_size,
            "order_count": len(live),
            "running_total": running,
        }
