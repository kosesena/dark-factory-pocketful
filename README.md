<p align="center">
  <img src="docs/crew/crew-with-outsider.png" width="860" alt="The Felt Five and a golden wool-plush outsider in their workshop">
</p>

<h1 align="center">The Felt Five</h1>

<p align="center">
  <b>a very dark factory that tests its own tests</b><br>
  WeAreDevelopers x BAND "Dark Factory" hackathon (lablab.ai) · track: pocketful · Sena Köse (solo) · stages 1–4
</p>

<p align="center">
  <img src="docs/readme/headline.svg" width="860" alt="81 faults planted; the shipped checks caught 8; the band's own evidence caught 75. 4/4 stages, one dispatch, six seats on two model families, 4 h 09 min, 131 USD at list price.">
</p>

> **The spec-auditor seeded 81 faults across four stages, one at a time, in the requirements it
> judged highest-risk. The shipped checks, a partial sample by design, caught 8; our band's own
> evidence caught 75** (the other 6 changed nothing observable). Six seats, two model families,
> one dispatch, no human message after it. On five revisions three Claude verifiers accepted and
> only the Codex seat said no; twice the customer said no to a layout the reviewer had accepted.

<p align="center">
  <a href="FACTORY.md"><b>FACTORY.md</b></a> ·
  <a href="#the-submitted-run-at-a-glance">the run at a glance</a> ·
  <a href="#autonomy-and-what-we-do-not-claim">autonomy and limits</a> ·
  <a href="#evidence-index">evidence index</a> ·
  <a href="https://felt-five-pocketful.onrender.com">live demo</a> ·
  <a href="#meet-the-crew-seat-by-seat">the crew</a>
</p>

<p align="center"><img src="docs/readme/stitch.svg" width="860" alt=""></p>

## The submitted run at a glance

| | |
|---|---|
| Human input | one dispatch message for all four stages (`room.json`: 6,783 messages, 1 from a human) |
| Duration | 10:53 → 16:00 on 4 Oct 2026; 57 min of that was a plan usage-limit pause |
| Stages closed (all four verifiers accepted the same revision) | 1 at 12:17 · 2 at 13:14 · 3 at 15:04 · 4 at 15:59 |
| Reject verdicts before those accepts | 27 (cross-auditor 13, reviewer 8, spec-auditor 4, customer 2) |
| Isolated harness on the final repository | stages 1–4 pass, **claimed stage: 4** |
| Shipped checks untouched | `shasum -c` on all 11 check files: OK |
| Model spend | 131.29 USD at Anthropic list prices for the five Claude seats, plus the Codex seat on a ChatGPT plan |

Every figure is derived, with its source, in [FACTORY.md](FACTORY.md) section 7.

### Stage by stage

| Stage | Closed on | Closed at | Shipped checks | Reject verdicts before close | Revisions judged | Faults seeded / caught by shipped checks / caught by the band |
|---|---|---|---|---|---|---|
| 1 | `999fda2` | 12:17 | 147/147 | 6 | 5 | 32 / 6 / 27 (5 equivalent) |
| 2 | `d78f1bd` | 13:14 | 35/35 | 4 | 5 | 16 / 1 / 16 |
| 3 | `397a149` | 15:04 | 6/6 | 4 | 5 | 18 / 1 / 18 |
| 4 | `000d7ac` | 15:59 | 5/5 | 13 | 11 | 15 / 0 / 14 (1 equivalent) |

Shipped-check counts are from the final isolated run, `docs/evidence/isolated-stage-4/report.json`.

### Seat by seat

| | Seat | Model | Commits | Tool calls in the room | Text messages | Reject verdicts | Spend (USD, list) |
|---|---|---|---|---|---|---|---|
| <img src="docs/crew/implementer.png" height="48" alt=""> | **implementer** | claude-sonnet-5-5 | 56 | 487 | 34 | (fixes) | 37.89 |
| <img src="docs/crew/reviewer.png" height="48" alt=""> | **reviewer** | claude-opus-5-5 | 27 | 425 | 28 | 8 | 32.90 |
| <img src="docs/crew/cross-auditor.png" height="48" alt=""> | **cross-auditor** | gpt-6-astra | 23 | 615 | 54 | 13 | ChatGPT plan |
| <img src="docs/crew/customer.png" height="48" alt=""> | **customer** | claude-sonnet-5-5 | 19 | 206 | 20 | 2 | 11.82 |
| <img src="docs/crew/spec-auditor.png" height="48" alt=""> | **spec-auditor** | claude-opus-5-5 | 17 | 392 | 25 | 4 | 35.79 |
| <img src="docs/crew/coordinator.png" height="48" alt=""> | **coordinator** | claude-sonnet-5-5 | 2 | 251 | 187 | (routing) | 12.89 |

All 56 commits under `stage-1/` to `stage-4/` are the implementer's; each verifier commits only in
its own folder.

## Autonomy, and what we do not claim

One human message entered the room: the dispatch. No seat asked the human anything, and nothing
was approved, hinted or dispatched again. Three things did happen on the host, outside the room,
during the run; FACTORY.md section 8 lists them in full:

1. At 13:24 the operator replaced the running restart script (the "window kicker") with a version
   that ignores the Codex seat's commits.
2. At 14:31 that script restarted all six seats, after the plan's usage limit had paused the
   Claude seats for 57 minutes.
3. At 14:32 the operator accepted an Xcode licence on the host so that `git` worked again.

None of the three wrote to the room or to the repository.

We do not claim:

- a result on the hidden checks: only the shipped part of each stage's suite was run;
- a run on the other scored track: the same mandates ran only the unscored `toy` track as a
  second problem (FACTORY.md section 11);
- an invoice: spend is the list-price equivalent of subscription use, and the Codex seat is not
  priced;
- that 8 of 81 is a fair score for the shipped checks: the auditor chose the faults, and the
  shipped set is a partial sample by design;
- that stage 4 is free of defects: one limitation is open, an import of about 300 older-format
  saved statements over 10,000 later payments takes 5.2 to 6.7 s against a 5 s limit
  (FACTORY.md section 9).

## Evidence index

| Claim | Where | Check it |
|---|---|---|
| 1 human message in 6,783 | `room.json` | `python3 -c "import json,collections;print(collections.Counter(m['senderType'] for m in json.load(open('room.json'))['messages']))"` prints Agent 6782, User 1 |
| No human commit under a stage folder | Git history | `git log --format=%an -- stage-1 stage-2 stage-3 stage-4 \| sort \| uniq -c` prints 56 implementer |
| 27 reject verdicts (13, 8, 4, 2) | `cross-audit/<revision>.md`, `reviewer/<revision>.md`, `audit/verdict-*`, `customer/verdict-*` | the verdict line at the top of each file |
| 81 seeded, 8 caught by shipped checks, 75 by the band | `audit/seed-results-stage-*.json`, `ledger/stage-*-faults.md` | the "caught by" column of each row; FACTORY.md section 7 names the five result files |
| Five revisions only the Codex seat rejected | `cross-audit/` and `reviewer/` files for `69289b3`, `0e8dea4`, `7c35a2a`, `8bbd03a`, `2bd67ec` | FACTORY.md section 6 |
| Claimed stage 4, isolated | `docs/evidence/isolated-stage-4/report.json` | or run the command under "Reproduce the checks" |
| Shipped checks not edited | `docs/evidence/checks.sha256` | `shasum -a 256 -c` against the kickoff package |
| Restarts and operator tooling | `docs/evidence/window-kicker.log`, `docs/evidence/seat-watchdog.log` | FACTORY.md section 8 |
| Mandates are generic | `mandates/` | `python -m harness check ../result --track pocketful` |
| Spend | FACTORY.md section 7 | any row can be priced again from its token counts and `tools/prices.json` |


**Live demo:** https://felt-five-pocketful.onrender.com — the delivered `stage-4/`, built from its own
Dockerfile, unchanged. Sign in as `ada@demo.felt` / `felt-demo-ada` or `bob@demo.felt` /
`felt-demo-bob` (demo data only), or create an account. State lives in memory, as the
specification allows, and `POST /_test/reset` is public by specification, so anyone can clear the
demo; if it looks empty, sign up and use it fresh.

![The delivered wallet at desktop width, from the customer seat's final screenshots](customer/screens-stage4-final/d-home-held.png)

*The delivered wallet (stage 4), as the customer seat saw it at 1280 px. Every screen at desktop
and phone width is in `customer/screens-stage4-final/`.*

<p align="center"><img src="docs/readme/stitch.svg" width="860" alt=""></p>

## The crew

<p align="center">
  <img src="docs/crew/coordinator.png" height="130" alt="coordinator: blue cone with a conductor's baton">
  <img src="docs/crew/implementer.png" height="130" alt="implementer: orange craftsperson with a beret and tool apron">
  <img src="docs/crew/reviewer.png" height="130" alt="reviewer: purple long-nosed detective with a magnifying glass">
  <img src="docs/crew/spec-auditor.png" height="130" alt="spec-auditor: green book with round glasses and a checklist">
  <img src="docs/crew/customer.png" height="130" alt="customer: pink floppy-eared character holding a phone">
  <img src="docs/crew/cross-auditor.png" height="130" alt="cross-auditor: golden wool-plush pebble with a monocle">
</p>

The Felt Five now welcome **one outsider**: a cross-auditor from a different model family.
The original crew keeps its stitched felt; the visitor is a soft golden wool-plush pebble
with a monocle. The mascots are only a storytelling layer for the video and this page:
the mandates contain no personality, and the seats behave exactly as
`mandates/` and `FACTORY.md` describe. Each seat has its own card at the end of this page.

## How to read this repository

| Path | What it is | Written by |
|---|---|---|
| [FACTORY.md](FACTORY.md) | how to stand the factory up, why it is built this way, measured time and cost, how it catches bad work, what failed | operator |
| `mandates/` | one generic mandate per seat; the first lines name its harness and model | operator |
| [docs/decisions/](docs/decisions/) | ADR-001 (keep the expensive spec-auditor), ADR-002 (a second model family) | operator |
| `tools/` | measurement script, list prices, seat watchdog, usage-window kicker | operator |
| `room.json` | the BAND room of the submitted run, downloaded unchanged | BAND |
| `stage-1/` … `stage-4/` | the service, one complete copy per stage, each with `Dockerfile` and `RUN.md` | implementer |
| `ledger/` | requirements ledgers and fault-seeding tables per stage | spec-auditor |
| `audit/` | the auditor's verdicts, probes and seeding results | spec-auditor |
| `reviewer/`, `verification/` | the reviewer's verdicts, reference models, probes | reviewer |
| `customer/` | journeys and screenshots at desktop and phone width | customer |
| `cross-audit/` | the Codex seat's atomized requirements, probes, evidence and verdicts | cross-auditor |
| `coordinator/final-report.md` | the coordinator's closing report: accepts per stage, rejects and fixes, rulings, open limitation | coordinator |
| `docs/evidence/` | files FACTORY.md cites from the submitted run: check fingerprints, kicker and watchdog logs, the final isolated report, the visual brief and its two images, the measurement script's output | operator, harness |
| `docs/experiments/` | the scripts and results behind ADR-001 and ADR-002 | operator |
| `docs/crew/`, `docs/readme/` | the mascot images and the headline card on this page | operator |

"Operator" is Sena Köse, working with Claude Code as a writing and tooling assistant outside the
room. Two early commits (30 Sep) that added the first mandates and the FACTORY.md skeleton carry
Claude's name as author. No seat of the band wrote any of the operator's files.

The Git history shows the same split: each seat commits under its own name. Every commit after
the coordinator's final report (`cd6e904`) is the operator's: one escapes a character in an audit
record (FACTORY.md section 8), one adds `room.json`, and the rest edit documents, `docs/` and
`tools/window-kicker.sh`. None touches a stage folder.

## Reproduce the checks

```sh
git clone <this repository> result
git clone https://github.com/band-ai/dark-factory-wearedevs && cd dark-factory-wearedevs
python3 -m venv .venv && . .venv/bin/activate && python -m pip install -r harness/requirements.txt
python -m harness check ../result --track pocketful
python -m harness run --track pocketful --repo ../result --stage 4 --mode isolated --out ../checks/final
python3 ../result/tools/factory_numbers.py --help   # spend and time tables; needs the seats' transcripts, which are not in this repository
```

The video of the room working is attached to the lablab submission. Authoritative rules:
https://github.com/band-ai/dark-factory-wearedevs/blob/main/docs/participant-guide.md

<p align="center"><img src="docs/readme/stitch.svg" width="860" alt=""></p>

## Meet the crew, seat by seat

<img src="docs/crew/coordinator.png" align="left" height="220" alt="Blue cone with a conductor's baton">

### coordinator

*Blue cone with a conductor's baton*

Runs on Claude Code with `claude-sonnet-5-5`. Reads the dispatch, splits the work, routes every handoff and closes the stage with a report.

**Never writes code.**

<br clear="all">

<img src="docs/crew/implementer.png" align="right" height="220" alt="Orange craftsperson with a beret and tool apron">

### implementer

*Orange craftsperson with a beret and tool apron*

Runs on Claude Code with `claude-sonnet-5-5`. Writes the code one small, separately committed change at a time, then hands it over to be checked.

**Never accepts its own work.**

<br clear="all">

<img src="docs/crew/reviewer.png" align="left" height="220" alt="Purple long-nosed detective with a magnifying glass">

### reviewer

*Purple long-nosed detective with a magnifying glass*

Runs on Claude Code with `claude-opus-5-5`. Verifies independently: builds its own reference model from the specification and compares it with the service over random sequences of operations.

**Never edits code.**

<br clear="all">

<img src="docs/crew/spec-auditor.png" align="right" height="220" alt="Green book with round glasses and a checklist">

### spec-auditor

*Green book with round glasses and a checklist*

Runs on Claude Code with `claude-opus-5-5`. Turns the specification into a requirements ledger, then breaks one requirement at a time in a throwaway copy and runs all the evidence against it, to prove the checks would notice.

**Never edits code or writes tests to pass.**

<br clear="all">

<img src="docs/crew/customer.png" align="left" height="220" alt="Pink floppy-eared character holding a phone">

### customer

*Pink floppy-eared character holding a phone*

Runs on Claude Code with `claude-sonnet-5-5`. Uses the product through its real interface at desktop and phone widths, without reading the implementation, and reports what a user would see.

**Never reads the code to judge it.**

<br clear="all">

## And one outsider

<img src="docs/crew/cross-auditor.png" align="right" height="220" alt="Golden fuzzy pebble with tiny black eyes and a teal-tinted monocle">

### cross-auditor

*Golden wool-plush pebble with a different lens*

Runs on Codex with `gpt-6-astra`. Independently walks each revision against the specification,
exercises requirements with concrete inputs and reports gaps before reading the other
verifiers' findings. Fault seeding remains the spec-auditor's responsibility.

**Never edits code or writes tests meant to make the build pass.**

<br clear="all">
