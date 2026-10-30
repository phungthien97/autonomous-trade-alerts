"""Account→USD sizing via IBKR FX map; never treat native cash as USD."""

from __future__ import annotations

import pytest

from app.account_snapshot import (
    AccountSnapshot,
    convert_amount,
    derive_usd_cad_rate,
    to_usd,
)


def test_convert_same_currency_passthrough() -> None:
    assert convert_amount(100.0, from_currency="USD", to_currency="USD", fx_rates=None) == 100.0


def test_convert_cad_to_usd_with_map() -> None:
    rates = {"USD": 1.4, "BASE": 1.0, "CAD": 1.0}
    assert convert_amount(
        140.0,
        from_currency="CAD",
        to_currency="USD",
        fx_rates=rates,
        account_currency="CAD",
    ) == pytest.approx(100.0)


def test_convert_usd_to_cad_with_map() -> None:
    rates = {"USD": 1.4, "BASE": 1.0, "CAD": 1.0}
    assert convert_amount(
        100.0,
        from_currency="USD",
        to_currency="CAD",
        fx_rates=rates,
        account_currency="CAD",
    ) == pytest.approx(140.0)


def test_convert_usd_to_cad_with_usd_as_account_is_noop() -> None:
    """Regression: wallet display must use IBKR account ccy, not USD.

    ``_rate_for`` forces account_currency→1.0, so USD→CAD with
    account_currency=\"USD\" silently returns the USD amount unchanged.
    """
    rates = {"USD": 1.4, "BASE": 1.0, "CAD": 1.0}
    assert convert_amount(
        100.0,
        from_currency="USD",
        to_currency="CAD",
        fx_rates=rates,
        account_currency="USD",
    ) == pytest.approx(100.0)


def test_convert_eur_to_usd_with_map() -> None:
    # BASE=EUR account: 1 EUR = 1 BASE; 1 USD = 0.92 EUR → 92 EUR = 100 USD
    rates = {"USD": 0.92, "BASE": 1.0, "EUR": 1.0}
    assert convert_amount(
        92.0,
        from_currency="EUR",
        to_currency="USD",
        fx_rates=rates,
        account_currency="EUR",
    ) == pytest.approx(100.0)


def test_convert_missing_rate_returns_zero() -> None:
    assert (
        convert_amount(
            140.0,
            from_currency="CAD",
            to_currency="USD",
            fx_rates={"BASE": 1.0},
            account_currency="CAD",
        )
        == 0.0
    )


def test_to_usd_converts_cad_with_rate() -> None:
    assert to_usd(140.0, account_currency="CAD", usd_cad_rate=1.4) == 100.0


def test_to_usd_blocks_cad_without_rate() -> None:
    assert to_usd(140.0, account_currency="CAD", usd_cad_rate=None) == 0.0
    assert to_usd(140.0, account_currency="BASE", usd_cad_rate=0.0) == 0.0


def test_to_usd_blocks_eur_without_map() -> None:
    assert to_usd(100.0, account_currency="EUR", usd_cad_rate=None, fx_rates=None) == 0.0


def test_to_usd_eur_with_fx_rates() -> None:
    rates = {"USD": 0.92, "BASE": 1.0, "EUR": 1.0}
    assert to_usd(92.0, account_currency="EUR", fx_rates=rates) == pytest.approx(100.0)


def test_spendable_usd_zero_when_cad_fx_missing() -> None:
    snap = AccountSnapshot(
        cash_usd=977_000.0,
        buying_power_usd=2_000_000.0,
        equity_usd=977_000.0,
        available_funds_usd=977_000.0,
        gross_position_value_usd=0.0,
        account_currency="CAD",
        usd_cad_rate=None,
    )
    assert snap.spendable_native == pytest.approx(977_000.0)
    assert snap.spendable_usd == 0.0


def test_spendable_usd_uses_fx_rates_map() -> None:
    snap = AccountSnapshot(
        cash_usd=140.0,
        buying_power_usd=140.0,
        equity_usd=140.0,
        available_funds_usd=140.0,
        gross_position_value_usd=0.0,
        account_currency="CAD",
        fx_rates={"USD": 1.4, "BASE": 1.0, "CAD": 1.0},
    )
    assert snap.spendable_usd == pytest.approx(100.0)


def test_derive_usd_cad_rate() -> None:
    assert derive_usd_cad_rate({"USD": 1.41, "BASE": 1.0}) == pytest.approx(1.41)
    assert derive_usd_cad_rate({"BASE": 1.0}) is None
