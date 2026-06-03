"""Memorable 4-digit customer codes.

Codes are what a returning caller quotes ("four, eight, two, one") so the agent
can pull up their record. 4 digits (0000-9999) keeps them easy to say and
remember; collisions are resolved by retrying with a fresh random code.
"""

import secrets
from typing import Callable

CODE_LENGTH = 4


def generate_code() -> str:
    """A random zero-padded 4-digit code, e.g. '0427' or '4821'."""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def generate_unique_code(exists: Callable[[str], bool], max_attempts: int = 100) -> str:
    """Generate a code not already taken, per the ``exists`` predicate.

    Args:
        exists: returns True if a code is already in use.
        max_attempts: give up after this many collisions (10k-code space, so
            this only trips if the customer base is enormous).
    """
    for _ in range(max_attempts):
        code = generate_code()
        if not exists(code):
            return code
    raise RuntimeError(
        "Could not allocate a unique customer code — the 4-digit space may be full."
    )
