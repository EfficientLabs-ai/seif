# GAEO Provisioning — making Claude/Codex/Gemini real GitHub contributors

> Turns GAEO from ARCHITECTURE into CLAIM. Every step marked 🔒 is a **protected action (founder-only)** — secrets never enter agent context; tokens live in the vault and are reached only via vault-aware helpers.

## Today-truth (the starting line)
- Only **Claude (as `neo`'s `gh`)** can execute `git`/`gh`. → the "hands".
- **Codex**: read-only profile + broken bwrap exec sandbox on this host → cannot run `gh`/`git`.
- **Gemini**: advisory text only; free tier (`gemini-3.5-flash`, 20 req/day) currently exhausted.
- **No per-model GitHub identities exist.**

So today GAEO runs as **"three minds, one pair of hands"**: Claude executes; Codex + Gemini verdicts are recorded into GitHub artifacts (review comments, `Co-Authored-By`, validation notes). Real consensus, single executor.

## The identity decision (the crux of "all as Contributors")
| Model | What it is | Pros | Cons |
|---|---|---|---|
| **A. GitHub App** ("SEIF-Bot", or one app per model) | bot identity, installation tokens (short-lived), scoped perms | least secret-management; short-lived tokens; clean audit; can open PRs/issues/reviews/checks | bots aren't CODEOWNERS humans; "by SEIF-Bot" attribution not per-model unless 3 apps |
| **B. Machine-user accounts** (`claude-efl`, `codex-efl`, `gemini-efl`) | 3 real GitHub accounts added as collaborators | distinct per-model contributors; CODEOWNERS-compatible; "feels like a team" | 3 accounts + 3 long-lived PATs to manage 🔒; ToS-bound automation accounts |
| **C. Hands + attributed (today)** | one identity, co-author trailers | zero provisioning; works now | no real autonomy |

**Recommendation:** **A (GitHub App)** for autonomy with the smallest secret surface — or **B** if per-model contributor identity matters more than token hygiene. Start on **C** today regardless; A/B is the upgrade.

## Provisioning steps (founder-gated)
1. 🔒 **Choose org** for new repos: `EfficientLabs-ai` (company) vs `Neo-The-Architect` (personal brand).
2. 🔒 **Choose identity model** (A/B/C above).
3. 🔒 **Provision identity:**
   - *App:* create GitHub App → permissions: Contents RW, Pull requests RW, Issues RW, Checks RW, Metadata RO → install on target repos → store private key in **vault**.
   - *Machine users:* create accounts → fine-grained PATs scoped to *specific repos*, least privilege → store in **vault**, wire to each model's runner.
4. **Fix Codex GitHub agency**: repair/replace the bwrap exec sandbox, OR route Codex's git ops through a kernel-mediated `gh` tool (SEIF task → approval → receipt). Until then Codex stays a recorded reviewer.
5. 🔒 **Lift Gemini**: add a billed `GEMINI_API_KEY` to the vault (free tier is too thin for a teammate).
6. 🔒 **Branch protection** on `main` (+`develop`): no direct push, required reviews, required status checks, linear history; **`neo` = required approver** on protected branches.
7. **Drop-in GAEO pack** (I author once org+identity chosen): `CODEOWNERS`, issue/PR/ADR templates, labels manifest, GitHub Actions (build·test·security·validation), branch-protection-as-code.

## Hard invariants (non-negotiable)
- `neo` holds **merge authority** on protected branches. Agents may open/review/approve PRs but **not** merge to `main`.
- **Repo creation, visibility flips, and `main` merges remain protected actions** (`governance/protected_actions.yaml`).
- Every agent GitHub action flows through the SEIF kernel (task → approval → receipt) → fully **audited** (this is the "audit everything" requirement, satisfied).
- Tokens/keys: **vault only, never in agent context** ([[feedback_no_raw_tokens_to_agents]]).

## v0.1 first slice (smallest enforceable loop)
One repo, one cycle: **Issue → feature branch → PR (Codex + Gemini reviews recorded) → required checks green → `neo` merges.** Prove that, then scale roles/boards/metrics from real events. The organization *emerges from proven primitives* — it is not declared into existence.
