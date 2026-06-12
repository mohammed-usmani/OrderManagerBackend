"""Table service: floor tables, QR resolution, and the live floor map.

Also owns the dine-in seating helpers the voice flow will call in Phase 4
(opening a table session, creating a dine-in cart bound to a table). Those are
written here so the data rules live in one place.
"""

from sqlalchemy.orm import Session

from db.repositories.order_repo import OrderRepo
from db.repositories.table_repo import TableRepo
from db.repositories.table_session_repo import TableSessionRepo
from db.repositories.zone_repo import ZoneRepo
from services import order_lifecycle as lifecycle
from services.billing import bill_for_order


class TableService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TableRepo(db)
        self.zone_repo = ZoneRepo(db)
        self.session_repo = TableSessionRepo(db)
        self.order_repo = OrderRepo(db)

    # --- CRUD ---

    def list_tables(self, zone_id: str | None = None, active_only: bool = False):
        return self.repo.list_all(zone_id=zone_id, active_only=active_only)

    def get_table(self, table_id: str):
        table = self.repo.get_by_id(table_id)
        if not table:
            raise ValueError("Table not found")
        return table

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
        self.repo.delete(table_id)

    # --- QR resolution (public) ---

    def resolve_qr(self, qr_token: str) -> dict:
        """Resolve a scanned QR token → table + zone context for the voice app."""
        table = self.repo.get_by_qr_token(qr_token)
        if not table or not table.active:
            raise ValueError("Unknown or inactive table")
        zone = self.zone_repo.get_by_id(table.zone_id)
        return {
            "table_id": table.id,
            "label": table.label,
            "seats": table.seats,
            "zone_id": zone.id if zone else None,
            "zone_name": zone.name if zone else None,
            "is_ac": bool(zone.is_ac) if zone else False,
        }

    # --- Live floor map ---

    def floor_map(self) -> list[dict]:
        """Zones (with their tables and any live session) for the admin map."""
        sessions = {s.table_id: s for s in self.session_repo.list_active()}
        out: list[dict] = []
        for zone in self.zone_repo.list_all():
            tables = []
            for t in self.repo.list_all(zone_id=zone.id):
                sess = sessions.get(t.id)
                tables.append(
                    {
                        "id": t.id,
                        "label": t.label,
                        "seats": t.seats,
                        "pos_x": t.pos_x,
                        "pos_y": t.pos_y,
                        "qr_token": t.qr_token,
                        "status": t.status,
                        "active": t.active,
                        "session": self._session_summary(sess) if sess else None,
                    }
                )
            out.append(
                {
                    "id": zone.id,
                    "name": zone.name,
                    "is_ac": zone.is_ac,
                    "display_order": zone.display_order,
                    "active": zone.active,
                    "tables": tables,
                }
            )
        return out

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
            "is_ac": bool(zone.is_ac) if zone else False,
            "orders": orders_out,
            "grand_subtotal": grand_subtotal,
            "grand_total": grand_total,
        }

    def _session_summary(self, sess) -> dict:
        orders = self.order_repo.list_for_table_session(sess.id)
        live = [o for o in orders if o.status not in lifecycle.CLOSED_STATUSES]
        running = sum(bill_for_order(o)["total"] for o in live)
        return {
            "id": sess.id,
            "status": sess.status,
            "opened_at": sess.opened_at.isoformat() if sess.opened_at else None,
            "party_size": sess.party_size,
            "order_count": len(live),
            "running_total": running,
        }
