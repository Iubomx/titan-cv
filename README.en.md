# TITAN CV

[Español](README.md) · **English**

Local, **evidence-based job search and application system** with a terminal command center
(Python, Playwright, SQLite, Rich).
Every claim that ends up in a CV or an application form traces back to a verifiable fact in the
candidate's profile. The system **never invents** experience, numbers or legal answers.

- 100% local. AI (Claude) is optional and disabled by default.
- The repository ships **no personal data**, only fictitious templates.
- Automatic submission is **disabled by default**. Read [Responsible use](#responsible-use) first.
- Working with an AI coding agent? Start with [`AGENTS.md`](AGENTS.md).

```
Discover (portals, public APIs, company ATS)
  -> Filter (role, duplicates, global registry)
  -> Evaluate (eligibility from your country, evidence match, salary, seniority)
  -> Apply (Playwright, only if you authorize it)
  -> Report (per-offer funnel, discard reasons, metrics)
```

> Note: user-facing messages, comments and most config templates are in Spanish, and the bundled local
> connectors target Chile. Contributions that add other markets or languages are very welcome.

## Requirements

- Python 3.10+
- Google Chrome (recommended) or Playwright Chromium
- Optional: Anthropic API key for the AI features

## Install

```bash
git clone https://github.com/Stoneroadd/titan-cv.git
cd titan-cv
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"       # Windows: .\.venv\Scripts\python.exe
.venv/bin/python -m playwright install chromium    # only if you will not use Google Chrome
.venv/bin/python -m pytest -q
# optional AI features:
.venv/bin/python -m pip install -e ".[ai]"
```

On Windows, `titan.cmd` is a shortcut: `.\titan <command>` is `python -m cvtitan <command>`.

## Set up YOUR data

None of these files are versioned (see `.gitignore`). Never commit them.

```bash
titan init                                              # creates candidate/profile.yaml
cp candidate/declarations.example.yaml candidate/declarations.yaml
cp candidate/question_bank.example.yaml candidate/question_bank.yaml
cp .env.example .env                                    # optional (Anthropic key)
titan validate
```

| File | Purpose | Key rule |
|---|---|---|
| `candidate/profile.yaml` | Single source of truth: contact, experience, achievements (with ids), projects, education, skills, preferences | A skill is `backed` only if `evidence` points to real ids; `to_demonstrate` is never claimed |
| `candidate/declarations.yaml` | Legal facts (citizenship, residence, work authorization, sponsorship) | The only source for legal answers; missing data leaves the question pending |
| `candidate/question_bank.yaml` | Regex-matched FAQ answers | Answers come only from your facts or decisions |
| `candidate/documents/` | Your CVs (PDF, one per language) | Referenced from `cv_files` |

To bootstrap from an existing CV, run `titan import-cv path/to/cv.pdf`. It produces a **draft**: every skill
starts as `to_demonstrate`, and you link evidence by hand.

## Configure the search

- `config/lines.yaml`: Line A (local portals) and Line B (international remote)
- `config/auto.yaml`: title regexes, minimum score, salary rule, daily cap
- `config/search_keywords.yaml`, `config/job_dictionary.json`, `config/companies.yaml`,
  `config/skills_taxonomy.yaml`, `config/settings.yaml`

All are templates (marked `# PLANTILLA`) with a data/software example profile.

## Usage

```bash
titan auto --modo hunter      # discover on Line A, no sending
titan auto --modo global      # international scanner, no sending
titan auto --modo analysis    # evaluate both lines, no sending
titan auto                    # full mission (sends ONLY if send_enabled: true)
titan demo <URL>              # watch the robot fill a form (never submits without --enviar)
titan postular --pendientes --ver   # finish human steps (CAPTCHA, email codes)
titan informe                 # last mission report
```

Tailored CV flow: `analyze` -> `match` -> `approve` -> `generate` -> `render` -> `interview`
(see `docs/agent-policy.md`). A CV whose `audit.md` is BLOCKED is never delivered.

## Responsible use

- No CAPTCHA or anti-bot evasion, no account creation, no password handling. Humans do login, CAPTCHA and email codes.
- Respect each portal's terms. LinkedIn forbids automation: strict limits apply, and `--sin-linkedin` is available.
- Mass applying without criteria hurts the candidate. Keep compatibility rules and a reasonable daily cap.
- The scheduled task (`programar_tarea.ps1`) runs unattended. Use it only after reviewing several manual runs.

## Privacy by design

`cvtitan/privacy.py` masks name, email, phone, city, LinkedIn, national ID and URLs in the terminal, logs and
reports. Forms receive real data; output never does. The AI never receives files, consent boxes or legal questions.

## Architecture

See [`AGENTS.md`](AGENTS.md), sections 3 and 4 (invariants and module map).

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md), [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) and
[`SECURITY.md`](SECURITY.md). License: MIT.
