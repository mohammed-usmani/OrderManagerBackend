"""Note-taking tools for the agent."""

import json
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

from langchain_core.tools import tool

NOTES_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "notes.json")


def _load_notes() -> list[dict]:
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE) as f:
        return json.load(f)


def _save_notes(notes: list[dict]) -> None:
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f, indent=2)


@tool
def save_note(content: str, category: str = "general") -> str:
    """Save a note with a category.

    Args:
        content: The content of the note to save.
        category: The category for the note, e.g. 'reminder', 'order', 'general'.
    """
    notes = _load_notes()
    note = {
        "id": str(uuid4())[:8],
        "content": content,
        "category": category,
        "timestamp": datetime.now().isoformat(),
    }
    notes.append(note)
    _save_notes(notes)
    return f"Note saved: '{content}' in category '{category}'."


@tool
def list_notes(category: Optional[str] = None) -> str:
    """List saved notes, optionally filtered by category.

    Args:
        category: Optional category to filter notes by.
    """
    notes = _load_notes()
    if category:
        notes = [n for n in notes if n["category"] == category]

    if not notes:
        return "No notes found." if not category else f"No notes found in category '{category}'."

    lines = []
    for n in notes:
        ts = datetime.fromisoformat(n["timestamp"]).strftime("%b %d %I:%M %p")
        lines.append(f"[{n['category']}] {n['content']} ({ts}) (id: {n['id']})")
    return "\n".join(lines)


@tool
def delete_note(note_id: str) -> str:
    """Delete a note by its ID.

    Args:
        note_id: The ID of the note to delete.
    """
    notes = _load_notes()
    original_count = len(notes)
    notes = [n for n in notes if n["id"] != note_id]

    if len(notes) == original_count:
        return f"No note found with ID '{note_id}'."

    _save_notes(notes)
    return f"Note '{note_id}' deleted."
