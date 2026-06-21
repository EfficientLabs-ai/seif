# Founder-Gated Queue — items needing Neo (review when back)

> Anything requiring secrets, a merge to main, production, publishing, or runtime self-modification is
> parked here per the deny-by-default doctrine. I (Claude) execute everything else autonomously and log
> it. Updated 2026-06-21 (founder at gym + Fortnite content; available remote).

## ⏳ Awaiting your call
| # | Item | Why gated | Action for you |
|---|---|---|---|
| 1 | **content-engine PR #2** (claim-discipline gate + CI) | merge to main | review + merge: `gh pr merge 2 --merge` (Neo-The-Architect/content-engine) |
| 2 | **Gemini API key** still 403 (unrestricted-key) | secret | restrict/mint in Cloud Console → unlocks the multi-model verifier panel (Codex+Gemini) |
| 3 | **`/seif` dogfood PR(s) on StratosAgent** (autonomous tonight) | merge to main | I'll open branch/PRs; you review + merge the good ones |
| 4 | **Composio (self-hosted) + Nango** for Stratos integrations | secrets/keys | provide keys when we reach P3 (Stratos-as-runtime) |
| 5 | **Hard branch protection** on EfficientLabs-ai/seif | org/plan | enable ruleset (was applied on content-engine) |
| 6 | **Publish/OSS decision** for SEIF (Apache) | public surface | hold until founder gate |
| 7 | **Social posting / content distribution** | public, brand | the poster stays gated; approve per-campaign |

## ✅ Done autonomously today (for your awareness)
- SEIF **action-ledger hook LIVE** (records every tool call, hash-chained, secrets redacted, fail-open).
- **P0 eval closed:** A 75.7% / v1 70.3% / **v2 81.1%** at n=37 (`logos/FINDINGS_001.md`).
- **Agent Harness** (eval-mode `logos/harness.py` + project-mode `logos/project_harness.py`) built + selftested.
- **EFL_OPERATING_SYSTEM.md** master architecture committed.
- content-engine **PR #1 merged** (content factory).

## 🤖 Executing autonomously tonight (no gate needed)
- Build + Codex-review the `/seif` driver; dogfood on StratosAgent (→ PRs land in queue item #3).
- Launch the **no-gate ablation** + **seed** runs (firms up gate-vs-just-more-turns); analyze on completion.
- Keep findings + receipts committed; update this file as items arise.
