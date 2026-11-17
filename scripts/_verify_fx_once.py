from app.account_snapshot import to_usd

assert to_usd(140, account_currency="CAD", usd_cad_rate=1.4) == 100
assert to_usd(92, account_currency="EUR", fx_rates={"USD": 0.92, "EUR": 1.0, "BASE": 1.0}) == 100
assert to_usd(100, account_currency="EUR") == 0
print("ovh-ok")
