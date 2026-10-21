# Docs index

## Active (live trading)

| Doc | Role |
|-----|------|
| [bot_architecture.md](bot_architecture.md) | How the bot decides and how the pieces fit (diagrams) |
| [live_trading_investigation.md](live_trading_investigation.md) | Locked product decisions (picker §12, remote viewer §13, fees, risk) |
| [live_trading_blueprint.md](live_trading_blueprint.md) | Historical TDD / implementer prompt series (Parts I–III) |
| [live_trading_todo.md](live_trading_todo.md) | Ops checklist and next actions |

Do **not** merge these three — they serve different jobs (spec / prompts / checklist).

## Ops / deploy

- OVH Gateway + workers + Streamlit: [`deploy/ibgateway/README.md`](../deploy/ibgateway/README.md)
- Project overview: [`README.md`](../README.md)

## Archived

| Path | Contents |
|------|----------|
| [`archive/docs/`](../archive/docs/) | Completed paper V2 blueprint + todo |
| [`archive/analysis/`](../archive/analysis/) | V1/V2 newsletters and timeline charts |
| [`archive/research/`](../archive/research/) | ZSP.TO walk-forward CSV outputs |
| [`archive/one_offs/`](../archive/one_offs/) | OVH helpers, walkforward script, sleeve one-offs |
| [`archive/ibgateway_probes/`](../archive/ibgateway_probes/) | Retired Gateway probe scripts |
