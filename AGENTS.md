# AGENTS.md — TITAN CV

Guide for AI coding agents (Codex, Claude Code, Cursor, Copilot, Gemini, ...). Read this first; it is the
fastest path to a correct change. Human-facing docs: `README.md`. Shared agent policy: `docs/agent-policy.md`.

## 1. What this project is

TITAN CV is a local, evidence-based job search and application system (Python 3.10+, Playwright, SQLite,
Rich). It discovers job offers, scores them against a candidate profile, applies through a browser robot
**only when authorized**, and reports every decision. Nothing it writes into a CV or a form may be invented:
every claim must trace back to `candidate/profile.yaml`.

- Code identifiers: English. User-facing messages and most comments/docs: Spanish. Terminal UI: English.
- Optional LLM (Anthropic API, `cvtitan/llm.py`) is disabled by default; everything works heuristically.

## 2. Setup and verification

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q          # must pass before you finish any code change
.\titan <command>                                # shortcut for .\.venv\Scripts\python.exe -m cvtitan <command>
```

- POSIX: `.venv/bin/python -m cvtitan <command>`.
- Browser end-to-end tests (`tests/test_apply_e2e.py`) skip when Chrome/Playwright is unavailable.
- CI (`.github/workflows/ci.yml`): `scripts/public_scan.py` (secrets, personal files, local paths, control
  characters), then pytest on Ubuntu and Windows.
- A test rejects control characters in source/config. If your tool writes `\b` through a shell heredoc,
  check that it did not become a backspace byte (0x08).

## 3. Invariants (never break these)

1. **No fabrication.** Only `backed` skills (with `evidence` ids) reach a CV or an answer; `to_demonstrate`
   never does. Numbers in a CV bullet must exist in its source. Keep every `source` field.
2. **Legal answers only from `candidate/declarations.yaml`** (citizenship, residence, work authorization,
   sponsorship, clearance). Missing data -> the question stays pending. See `apply/legal.py`.
3. **No CAPTCHA/anti-bot evasion, no account creation, no password handling.** Login, CAPTCHA and email
   codes are done by a human (`postular --pendientes --ver`).
4. **Sending is opt-in**: `lines.<A|B>.send_enabled` in `config/lines.yaml` (default `false`). Enforced for BOTH lines by `cvtitan/send_policy.py` (only a boolean `true` enables it). `lines.<A|B>.review_mode` (default `always`) leaves each application in `awaiting_review` for a human; `auto` is an explicit opt-in. Daily caps
   (`daily_max`, `config/settings.yaml -> daily_limits`, LinkedIn limits) are protections, not targets.
5. **Privacy**: terminal, logs and reports go through `cvtitan/privacy.py` (`redact`, `RedactingStream`);
   URLs are shown as `domain #JOB-XXXXXXXX` (`privacy.ref`). Forms receive real data; output never does.
6. **Real mode never shows fabricated metrics.** Simulated data exists only in `showcase` and is labeled SIM.
7. **Never commit personal data**: `candidate/*` (except `*.example.yaml`), `data/`, `.env` and browser
   sessions are git-ignored. Tests use fictitious data only (`@example.com`, invented names and places).
8. **The registry decides duplicates** (`cvtitan/registry.py`): never submit when a vacancy is in a
   BLOCKING state, and do not rewrite historical states.

## 4. Architecture map

```
discover -> filter -> evaluate -> apply (optional) -> report
```

| Area | Files | Notes |
|---|---|---|
| CLI and mission control | `cli.py`, `__main__.py` | `cmd_*` functions; `cmd_auto` runs a mission (UI, run log, funnel CSV, report) |
| Line A (local portals) | `autopilot.py`, `apply/search.py` | `load_rules` + `decide(row, rules, prefs)`; rules in `config/auto.yaml` |
| Line B (international remote) | `line_b.py`, `apply/intl_sources.py` | `collect_offers`, `title_matches`, eligibility by region, `score_line`; `FETCHERS` registry; world scan via `known_boards` |
| Browser robot | `apply/runner.py`, `apply/forms.py`, `apply/batch.py`, `apply/platforms.py` | open -> fill -> validate -> submit/pause; per-portal texts in `PLATFORMS`; circuit breaker in `batch.py` |
| Answers | `apply/answers.py`, `apply/question_bank.py`, `apply/legal.py` | profile rules -> question bank (regex patterns) -> evidence engine -> legal guard |
| Duplicates and history | `registry.py`, `db.py` | states: DISCOVERED, QUALIFIED, QUEUED, IN_PROGRESS, SUBMITTED_CONFIRMED, SUBMISSION_UNKNOWN, PENDING_REVIEW, FAILED, REJECTED, CLOSED |
| Funnel and telemetry | `funnel.py`, `telemetry.py` | every offer gets a tier (`high/held/manual/potential/review/no`) and a reason; event bus `subscribe` / `_publish`, `STATE` |
| CV pipeline | `job_intel.py` (01), `evidence.py` (02), `cv_writer.py` (03), `recruiter.py` (04), `interview.py` | analyze -> match -> generate -> render/audit -> interview |
| UI | `ui/` (`dashboard.py` CommandCenter, `ascii_helmet.py`, `theme.py`, `showcase.py`), `report.py`, `colors.py` | text tags `[SENT] [DONE] [PEND] [SKIP] [FAIL]`, no emoji |
| Infra | `privacy.py`, `net.py` (shared httpx client), `utils.py` (`Workspace`, `load_yaml`), `taxonomy.py`, `job_dictionary.py` | |
| Release | `publish.py` | audited export from a private repo (whitelist, sanitizers, scans, tests); used by maintainers |
| Web UI | `web/app.py`, `web/static/` | `cvtitan web` -> http://127.0.0.1:8765 |

## 5. Data layout

| Path | Content | Versioned |
|---|---|---|
| `candidate/profile.yaml` | single source of truth (experience, achievements with ids, skills with status/evidence, preferences) | no (template: `profile.example.yaml`) |
| `candidate/declarations.yaml`, `candidate/question_bank.yaml` | legal facts; FAQ answers by regex | no (templates: `*.example.yaml`) |
| `config/*.yaml`, `config/job_dictionary.json` | search rules, sources, limits, UI, skills taxonomy, role catalog | yes (templates marked `# PLANTILLA`) |
| `data/cvtitan.db` | SQLite: applications, events, vacancy registry | no |
| `data/auto/runs/<stamp>-<mode>.*` | run log, report (txt/json), `*-funnel.csv` (no URLs; codes resolve via `data/auto/refs.json`) | no |
| `data/jobs/<id>/`, `data/outputs/<id>/` | job analysis; CV draft, audit, interview guide | no |
| `data/browser-profile/` | persistent Chrome profile (human-made sessions) | no, never read or copy it |

## 6. Commands

| Command | Purpose |
|---|---|
| `init`, `validate` | create / check the candidate profile |
| `auto [--modo hunter\|global\|analysis\|apply\|stealth\|debug] [--linea A\|B] [--sin-linkedin]` | full mission; only `apply` can send, and only if `send_enabled` |
| `buscar`, `postular`, `postular --pendientes --ver` | search portals; apply to URLs/listings; finish human steps |
| `demo <URL> [--enviar]` | watch the robot fill a form (no submit without `--enviar`) |
| `informe [--historial] [--ref JOB-XXXXXXXX]` | last mission report, history, resolve a masked code |
| `showcase` | command center with SIMULATED data |
| `analyze`, `generate`, `render`, `run`, `jobs`, `track`, `import-cv` | tailored-CV pipeline (see `docs/agent-policy.md`) |
| `registro`, `mercado`, `geo`, `sesiones`, `web` | registry, market stats, geo catalog, portal logins (human), web UI |

Use `--help` on any command. Safe commands for exploring a fresh clone: `validate`, `auto --modo analysis`,
`showcase`, `informe`.

## 7. Common tasks (where to change what)

- **New job source**: add a fetcher in `apply/intl_sources.py` returning dicts with
  `source, url, title, company, text, regions, salary`; register it in `FETCHERS` and in
  `config/lines.yaml -> lines.B.sources`. Use `net.fetch` and `_cached` (one request per source per day).
- **New application portal**: add a `Platform` in `apply/platforms.py` (success / already-applied / blocked texts).
- **New FAQ answer**: `candidate/question_bank.yaml` (user data) or `candidate/question_bank.example.yaml` (generic).
- **New technology**: `config/skills_taxonomy.yaml` (category + aliases).
- **New roles**: `config/job_dictionary.json` (roles + priority P1/P2/P3) or keywords in `config/lines.yaml`.
- **New dashboard metric**: publish it through `telemetry.py` (`count`, `market`, `funnel`) and render it in
  `ui/dashboard.py`; it must come from real events.
- **New config option**: add it to the config file, its `# PLANTILLA` template, and `README.md`.

## 8. Change checklist

1. Small, focused diff; follow existing style (type hints, `pathlib`, Spanish user messages).
2. Add or update tests in `tests/` with fictitious data; engine tests build their own rule fixtures instead
   of reading the user's `config/`.
3. Run `pytest -q` (all green) and, if you touched output, check that nothing personal or a full URL is printed.
4. Never touch `candidate/*.yaml`, `data/` or `.env` without the user's explicit request.
5. Do not change send gating, CAPTCHA handling, legal answers or privacy masking without explicit approval.
