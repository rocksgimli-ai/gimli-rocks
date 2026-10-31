"""Regression tests for the telephony fixes.

These deliberately need no provider credentials: they exercise the pure helpers
and the constants, not a live LiveKit session.
"""

import types

import pytest

from telephony.inbound import agent as inbound
from telephony.outbound import agent as outbound
from telephony.outbound import dial


def test_participant_wait_is_bounded() -> None:
    """A job must not hold a worker slot forever if no caller arrives."""
    assert inbound.PARTICIPANT_TIMEOUT_S > 0


def test_caller_phone_number_ignores_browser_participants() -> None:
    participant = types.SimpleNamespace(
        kind=object(), attributes={"sip.phoneNumber": "+15105550100"}
    )
    assert inbound.caller_phone_number(participant) is None


def test_phone_number_from_json_metadata() -> None:
    ctx = types.SimpleNamespace(
        job=types.SimpleNamespace(metadata='{"phone_number": "+15551234567"}')
    )
    assert outbound.phone_number_from_metadata(ctx) == "+15551234567"


def test_phone_number_from_bare_metadata() -> None:
    ctx = types.SimpleNamespace(job=types.SimpleNamespace(metadata="  +15551234567 "))
    assert outbound.phone_number_from_metadata(ctx) == "+15551234567"


def test_phone_number_absent() -> None:
    ctx = types.SimpleNamespace(job=types.SimpleNamespace(metadata=None))
    assert outbound.phone_number_from_metadata(ctx) is None


@pytest.mark.parametrize("number", ["+15551234567", "+919876543210"])
def test_e164_accepts_valid_numbers(number: str) -> None:
    assert dial.E164.match(number)


@pytest.mark.parametrize("number", ["5551234567", "+0123", "not-a-number", "+1"])
def test_e164_rejects_invalid_numbers(number: str) -> None:
    """Validation was commented out, so any string reached the SIP trunk."""
    assert not dial.E164.match(number)
