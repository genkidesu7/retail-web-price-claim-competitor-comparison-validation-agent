"""Unit tests for the shared mock-mode helper (src/services/mock_mode.py)."""

from __future__ import annotations

import pytest

from src.services.mock_mode import MOCK_FLAG_NAMES, mock_mode_enabled


@pytest.fixture(autouse=True)
def _clean_flags(monkeypatch):
    for name in MOCK_FLAG_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_both_canonical_and_ci_flag_are_accepted():
    assert set(MOCK_FLAG_NAMES) == {"USE_MOCK", "STG_MOCK_MODE"}


def test_off_when_no_flag_set():
    assert mock_mode_enabled() is False


@pytest.mark.parametrize("flag", MOCK_FLAG_NAMES)
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_on_when_either_flag_truthy(monkeypatch, flag, value):
    monkeypatch.setenv(flag, value)
    assert mock_mode_enabled() is True


@pytest.mark.parametrize("flag", MOCK_FLAG_NAMES)
@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_off_when_flag_falsy(monkeypatch, flag, value):
    monkeypatch.setenv(flag, value)
    assert mock_mode_enabled() is False


def test_ci_flag_alone_enables_mock_when_canonical_flag_is_false(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    assert mock_mode_enabled() is True
