"""Settings service — admin-editable runtime config (currently the bill policy).

The active charge policy lives in the ``app_settings`` table under the
``charge_policy`` key. On startup we load it into the billing module's in-process
cache (so ``compute_bill`` never hits the DB); on edit we persist and refresh the
cache. If the row is absent we fall back to ``config.CHARGE_POLICY``.
"""

from sqlalchemy.orm import Session

from config import CHARGE_POLICY
from db.models.app_setting import AppSetting
from services import billing

CHARGE_POLICY_KEY = "charge_policy"

# Required keys per charge entry; ``ac_only`` is optional (defaults False).
_REQUIRED_FIELDS = {"key", "label", "rate", "applies_to"}
_VALID_APPLIES_TO = {"all", "dine_in", "parcel"}


class SettingsService:
    def __init__(self, db: Session):
        self.db = db

    # --- charge policy ---

    def get_charge_policy(self) -> list[dict]:
        row = self.db.get(AppSetting, CHARGE_POLICY_KEY)
        if row and isinstance(row.value, list):
            return row.value
        return [dict(c) for c in CHARGE_POLICY]

    def set_charge_policy(self, policy: list[dict]) -> list[dict]:
        clean = self._validate_policy(policy)
        row = self.db.get(AppSetting, CHARGE_POLICY_KEY)
        if row:
            row.value = clean
        else:
            row = AppSetting(key=CHARGE_POLICY_KEY, value=clean)
            self.db.add(row)
        self.db.flush()
        billing.set_policy_override(clean)  # refresh the live cache
        return clean

    def _validate_policy(self, policy) -> list[dict]:
        if not isinstance(policy, list) or not policy:
            raise ValueError("Charge policy must be a non-empty list")
        clean: list[dict] = []
        for c in policy:
            if not isinstance(c, dict) or not _REQUIRED_FIELDS <= set(c):
                raise ValueError(
                    f"Each charge needs {sorted(_REQUIRED_FIELDS)}; got {c}"
                )
            if c["applies_to"] not in _VALID_APPLIES_TO:
                raise ValueError(
                    f"applies_to must be one of {sorted(_VALID_APPLIES_TO)}"
                )
            try:
                rate = float(c["rate"])
            except (TypeError, ValueError):
                raise ValueError(f"rate must be a number; got {c['rate']!r}")
            if not 0 <= rate < 1:
                raise ValueError("rate must be a fraction in [0, 1)")
            clean.append(
                {
                    "key": str(c["key"]),
                    "label": str(c["label"]),
                    "rate": rate,
                    "applies_to": c["applies_to"],
                    "ac_only": bool(c.get("ac_only", False)),
                }
            )
        return clean

    # --- startup ---

    def load_into_cache(self) -> None:
        """Seed the default policy if absent, then prime the billing cache."""
        row = self.db.get(AppSetting, CHARGE_POLICY_KEY)
        if not row:
            row = AppSetting(key=CHARGE_POLICY_KEY, value=[dict(c) for c in CHARGE_POLICY])
            self.db.add(row)
            self.db.flush()
        billing.set_policy_override(row.value)
