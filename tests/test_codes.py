"""Tests for 4-digit customer code generation."""

import pytest

from agent.restaurant.codes import generate_code, generate_unique_code


def test_generate_code_is_four_digits():
    for _ in range(50):
        code = generate_code()
        assert len(code) == 4
        assert code.isdigit()


def test_generate_unique_code_avoids_taken():
    taken = {"0000", "0001", "0002"}
    code = generate_unique_code(lambda c: c in taken)
    assert code not in taken
    assert len(code) == 4


def test_generate_unique_code_raises_when_space_exhausted():
    # Every code is "taken" → should give up rather than loop forever.
    with pytest.raises(RuntimeError):
        generate_unique_code(lambda c: True, max_attempts=10)
