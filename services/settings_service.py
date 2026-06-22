"""Settings service — admin-editable runtime config (currently the bill policy).

The active charge policy lives in the ``app_settings`` table under the
``charge_policy`` key. On startup we load it into the billing module's in-process
cache (so ``compute_bill`` never hits the DB); on edit we persist and refresh the
cache. If the row is absent we fall back to ``config.CHARGE_POLICY``.
"""

import re

from sqlalchemy.orm import Session

from config import CHARGE_POLICY
from db.models.app_setting import AppSetting
from services import billing

CHARGE_POLICY_KEY = "charge_policy"
RESTAURANT_PROFILE_KEY = "restaurant_profile"

# Required keys per charge entry; ``ac_only`` is optional (defaults False).
_REQUIRED_FIELDS = {"key", "label", "rate", "applies_to"}
_VALID_APPLIES_TO = {"all", "dine_in", "parcel"}

# --- Restaurant profile (identity + GST details + weekly hours) ---
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_PROFILE_STR_FIELDS = [
    "name", "legal_name", "cuisine", "tagline", "address_line1", "address_line2",
    "phone", "email", "website", "gstin", "fssai", "currency", "timezone",
]
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Mirrors the static brand.ts / agent defaults so first boot looks intentional.
DEFAULT_RESTAURANT_PROFILE = {
    "name": "Saffron & Smoke",
    "legal_name": "Saffron & Smoke",
    "cuisine": "Modern Indian",
    "tagline": "Modern Indian · Bandra West, Mumbai",
    "address_line1": "14, Hill Road",
    "address_line2": "Bandra West, Mumbai 400050",
    "phone": "+91 22 2640 1234",
    "email": "",
    "website": "saffronandsmoke.com",
    "gstin": "27AABCS1234Z1Z5",
    "fssai": "11520003000987",
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    # Per-weekday service windows; an empty list means closed that day.
    "hours": {
        "mon": [],
        "tue": [{"open": "11:00", "close": "15:00"}, {"open": "18:00", "close": "23:00"}],
        "wed": [{"open": "11:00", "close": "15:00"}, {"open": "18:00", "close": "23:00"}],
        "thu": [{"open": "11:00", "close": "15:00"}, {"open": "18:00", "close": "23:00"}],
        "fri": [{"open": "11:00", "close": "15:00"}, {"open": "18:00", "close": "23:00"}],
        "sat": [{"open": "11:00", "close": "15:00"}, {"open": "18:00", "close": "23:00"}],
        "sun": [{"open": "11:00", "close": "15:00"}, {"open": "18:00", "close": "23:00"}],
    },
}


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

    # --- restaurant profile ---

    def get_restaurant_profile(self) -> dict:
        row = self.db.get(AppSetting, RESTAURANT_PROFILE_KEY)
        stored = row.value if row and isinstance(row.value, dict) else {}
        # Merge over defaults so every key the UI/receipt expects is always present.
        return {**DEFAULT_RESTAURANT_PROFILE, **stored,
                "hours": {**DEFAULT_RESTAURANT_PROFILE["hours"], **stored.get("hours", {})}}

    def set_restaurant_profile(self, data: dict) -> dict:
        clean = self._validate_profile(data)
        row = self.db.get(AppSetting, RESTAURANT_PROFILE_KEY)
        if row:
            row.value = clean
        else:
            row = AppSetting(key=RESTAURANT_PROFILE_KEY, value=clean)
            self.db.add(row)
        self.db.flush()
        return clean

    def _validate_profile(self, data) -> dict:
        if not isinstance(data, dict):
            raise ValueError("Restaurant profile must be an object")
        clean: dict = {}
        for f in _PROFILE_STR_FIELDS:
            clean[f] = str(data.get(f, DEFAULT_RESTAURANT_PROFILE[f]) or "").strip()
        if not clean["name"]:
            raise ValueError("Restaurant name is required")
        # Hours: per weekday, a list of {open, close} HH:MM windows (empty = closed).
        raw_hours = data.get("hours") or {}
        if not isinstance(raw_hours, dict):
            raise ValueError("hours must be an object keyed by weekday")
        hours: dict = {}
        for day in WEEKDAYS:
            windows = raw_hours.get(day, [])
            if not isinstance(windows, list):
                raise ValueError(f"hours.{day} must be a list")
            clean_windows = []
            for w in windows:
                if not isinstance(w, dict) or "open" not in w or "close" not in w:
                    raise ValueError(f"hours.{day} windows need open/close")
                o, c = str(w["open"]), str(w["close"])
                if not _TIME_RE.match(o) or not _TIME_RE.match(c):
                    raise ValueError(f"hours.{day} times must be HH:MM (24h)")
                if o >= c:
                    raise ValueError(f"hours.{day}: open must be before close")
                clean_windows.append({"open": o, "close": c})
            hours[day] = clean_windows
        clean["hours"] = hours
        return clean

    # --- startup ---

    def load_into_cache(self) -> None:
        """Seed the default policy + profile if absent, then prime the billing cache."""
        row = self.db.get(AppSetting, CHARGE_POLICY_KEY)
        if not row:
            row = AppSetting(key=CHARGE_POLICY_KEY, value=[dict(c) for c in CHARGE_POLICY])
            self.db.add(row)
            self.db.flush()
        billing.set_policy_override(row.value)
        if not self.db.get(AppSetting, RESTAURANT_PROFILE_KEY):
            self.db.add(AppSetting(key=RESTAURANT_PROFILE_KEY, value=DEFAULT_RESTAURANT_PROFILE))
            self.db.flush()
