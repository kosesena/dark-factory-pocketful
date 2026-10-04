# The Felt Five — a very dark factory that tests its own tests

> **The spec-auditor seeded 81 faults across four stages, one at a time. The shipped checks caught
> 8; our band's own evidence caught 75** (the other 6 changed nothing observable). Six seats, two
> model families, one dispatch, no human message after it. On five revisions three Claude
> verifiers accepted and only the Codex seat said no.

Entry for the WeAreDevelopers x BAND "Dark Factory" hackathon (lablab.ai).
**Track:** pocketful. **Team:** Sena Köse (solo). **Stages delivered:** 1–4.

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

![The delivered wallet at desktop width, from the customer seat's final screenshots](customer/screens-stage4-final/d-home-held.png)

*The delivered wallet (stage 4), as the customer seat saw it at 1280 px. Every screen at desktop
and phone width is in `customer/screens-stage4-final/`.*

## Meet the crew

![The Felt Five and a golden wool-plush outsider in their workshop](docs/crew/crew-with-outsider.png)

The Felt Five now welcome **one outsider**: a cross-auditor from a different model family.
The original crew keeps its stitched felt; the visitor is a soft golden wool-plush pebble
with a monocle. The mascots are only a storytelling layer for the video and this page:
the mandates contain no personality, and the seats behave exactly as
`mandates/` and `FACTORY.md` describe.

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
| `docs/crew/` | the mascot images on this page | operator |

The Git history shows the same split: each seat commits under its own name. Two commits after
the run are the operator's and are explained in FACTORY.md section 8.

## Reproduce the checks

```sh
git clone <this repository> result
git clone https://github.com/band-ai/dark-factory-wearedevs && cd dark-factory-wearedevs
python3 -m venv .venv && . .venv/bin/activate && python -m pip install -r harness/requirements.txt
python -m harness check ../result --track pocketful
python -m harness run --track pocketful --repo ../result --stage 4 --mode isolated --out ../checks/final
python3 ../result/tools/factory_numbers.py --help   # the spend, time and verdict tables
```

The video of the room working is attached to the lablab submission. Authoritative rules:
https://github.com/band-ai/dark-factory-wearedevs/blob/main/docs/participant-guide.md
