"""Date and time tools for the agent."""

from datetime import datetime

from langchain_core.tools import tool


@tool
def get_current_datetime() -> str:
    """Get the current date, time, and day of week."""
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y at %I:%M %p")
