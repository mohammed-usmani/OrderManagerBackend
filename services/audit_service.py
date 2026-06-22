"""Audit log helper — record who did what (voids, refunds, settles, transfers)."""

from sqlalchemy.orm import Session

from db.models.audit_log import AuditLog


def write_audit(
    db: Session,
    *,
    actor=None,
    action: str,
    entity: str,
    entity_id: str | None = None,
    reason: str | None = None,
    meta: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", None),
            action=action,
            entity=entity,
            entity_id=entity_id,
            reason=reason,
            meta=meta,
        )
    )
    db.flush()
