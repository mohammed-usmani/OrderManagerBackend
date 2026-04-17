"""Date and time tools for the agent."""

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

RESTAURANT_TZ = ZoneInfo("Asia/Kolkata")


def _safe_zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


@tool
def get_current_datetime(config: RunnableConfig = None) -> str:
    """Get the current date and time, both restaurant-local (IST) and customer-local.

    The restaurant is in Mumbai (IST). If the customer's timezone is known it
    is included too so you can answer questions without timezone confusion.
    """
    user_tz_name = (config or {}).get("configurable", {}).get("user_timezone")
    now_rest = datetime.now(RESTAURANT_TZ)
    rest_line = now_rest.strftime("%A, %B %d, %Y at %I:%M %p %Z")

    user_zone = _safe_zone(user_tz_name)
    if user_zone:
        now_user = now_rest.astimezone(user_zone)
        user_line = now_user.strftime("%A, %B %d, %Y at %I:%M %p %Z")
        return (
            f"Restaurant (IST, Mumbai): {rest_line}\n"
            f"Customer ({user_tz_name}): {user_line}"
        )
    return f"Restaurant (IST, Mumbai): {rest_line}"
