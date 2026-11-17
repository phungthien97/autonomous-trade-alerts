from app.live.budget import effective_buy_pool, plan_reduce_to_budget

assert effective_buy_pool(150, invested_usd=100, spendable_usd=500) == 50
assert effective_buy_pool(200, invested_usd=0, spendable_usd=80) == 80
sells = plan_reduce_to_budget({"A": 100.0}, {"A": 1.0}, budget_usd=0.0)
assert sells and sells[0].shares == 100.0
print("ovh-ok")
