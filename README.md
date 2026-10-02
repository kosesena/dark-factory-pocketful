# Stitch Check — a dark factory that tests its own tests

Entry for the WeAreDevelopers x BAND "Dark Factory" hackathon (lablab.ai), track **pocketful**.
Team: Sena Köse (solo). Submission deadline: **6 Oct 2026, 09:59 Türkiye time** (5 Oct 23:59 PDT).

> This README is a working brief until submission. At submission it is rewritten to say:
> team, track, and how to read this repository.

## Meet the crew

![The five seats as felt mascots in their workshop](docs/crew/crew.jpg)

Each seat in the band has a felt mascot. The mascots are only a storytelling layer for the
video and this page: the mandates contain no personality, and the seats behave exactly as
`mandates/` and `FACTORY.md` describe.

<img src="docs/crew/coordinator.png" align="left" height="220" alt="Blue cone with a conductor's baton">

### coordinator

*Blue cone with a conductor's baton*

Reads the dispatch, splits the work, routes every handoff and closes the stage with a report.

**Never writes code.**

<br clear="all">

<img src="docs/crew/implementer.png" align="right" height="220" alt="Orange craftsperson with a beret and tool apron">

### implementer

*Orange craftsperson with a beret and tool apron*

Writes the code one small, separately committed change at a time, then hands it over to be checked.

**Never accepts its own work.**

<br clear="all">

<img src="docs/crew/reviewer.png" align="left" height="220" alt="Purple long-nosed detective with a magnifying glass">

### reviewer

*Purple long-nosed detective with a magnifying glass*

Verifies independently: builds its own reference model from the specification and compares it with the service over random sequences of operations.

**Never edits code.**

<br clear="all">

<img src="docs/crew/spec-auditor.png" align="right" height="220" alt="Green book with round glasses and a checklist">

### spec-auditor

*Green book with round glasses and a checklist*

Turns the specification into a requirements ledger, then breaks one requirement at a time in a throwaway copy and runs all the evidence against it, to prove the checks would notice.

**Never edits code or writes tests to pass.**

<br clear="all">

<img src="docs/crew/customer.png" align="left" height="220" alt="Pink floppy-eared character holding a phone">

### customer

*Pink floppy-eared character holding a phone*

Uses the product through its real interface at desktop and phone widths, without reading the implementation, and reports what a user would see.

**Never reads the code to judge it.**

<br clear="all">

## What is being built

A software factory in BAND Desktop: at least three coding-agent seats (each a separate
Claude Code window on the participant's machine) that plan work, implement it, hand off
evidence and independently check results. The factory builds a wallet/payments service
(the `pocketful` track) one stage at a time.

Authoritative rules: https://github.com/band-ai/dark-factory-wearedevs/blob/main/docs/participant-guide.md

## Scoring (what to optimise)

| Weight | Criterion | Read from |
|---|---|---|
| 50% | **Factory** — mandates are generic (another team could point them at a different problem); `FACTORY.md` is enough to stand it up: seat setup, design rationale, measured time and model spend, how bad work is caught and recovered | this repo |
| 25% | **Agent teamwork** — seats shared the work, review changed something, handoffs carried the whole task; the only human input per stage is the dispatch message | `room.json` + git history |
| 25% | **App** — what the factory built; UI quality matters from stage 2 | harness suites |

A complete `stage-1/` alone makes the entry eligible. Goal: strong mandates + clean stage-1
(stage-2 if time allows) + honest `FACTORY.md` + a video that shows the room working.

## Disqualifiers (never break these)

- A mandate that names track-specific detail: endpoint paths, field names, error codes,
  fixture ids. `python -m harness check` scans `mandates/` against the organisers' vocabulary
  list. Track detail goes only into the task message pasted into the room.
- Hand-written code. Only code produced through the BAND room counts.
- Code written to the shipped tests (only 79% of stage-1 checks are shipped; judges run the full set).
- A video without the BAND Desktop room recording.
- A `stage-1/` that does not build and serve from a clean container (no outbound network at run time,
  2 vCPU, 2 GiB, healthy within 60 s, `PORT` env, `GET /health`, `POST /_test/reset`).
- Any human steering in the submitted run: no "looks good, continue", no reruns, no approvals.

## Repository layout required at submission

```
README.md          team, track, how to read this repository
FACTORY.md         seats, design choices, measured costs, failure handling
mandates/          one .md per seat, named after the seat as BAND shows it (>= 3);
                   first lines:  Harness: Claude Code  /  Model: <exact model id>
room.json          the room export downloaded from BAND
stage-1/           Dockerfile, RUN.md, source  (no .git inside)
stage-2/ ...       each a complete service = previous stage carried forward + extended
```

## Workspace on the participant's Mac (local only)

```
~/Desktop/dark-factory/dark-factory-wearedevs   kickoff package: specs, shipped tests, harness (.venv ready)
~/Desktop/dark-factory/band-work/result         this repository
~/Desktop/dark-factory/band-work/checks         harness run outputs
```

Check a stage (host mode while iterating, isolated mode for the final check):

```sh
cd ~/Desktop/dark-factory/dark-factory-wearedevs && . .venv/bin/activate
python -m harness run --track pocketful --repo ../band-work/result --stage 1 --out ../band-work/checks/s1-01
python -m harness run --track pocketful --repo ../band-work/result --stage 1 --mode isolated --out ../band-work/checks/s1-final
python -m harness check --repo ../band-work/result --track pocketful
```

## Plan

1. **Setup (local):** Docker Desktop, BAND account + BAND Desktop + Claude Code plugin, lablab enrol, BAND Discord.
2. **Factory design (this repo, can be done in a cloud session):** write `mandates/` for a
   coordinator, an implementer, an independent reviewer that runs the checks itself, and a
   spec auditor that lists what the shipped checks never asked for; write the `FACTORY.md`
   skeleton with placeholders for measured costs.
3. **Practice (local):** run the factory on the unscored `toy` track in a scratch room and a scratch
   repo; fix mandates until the seats hand off and reject correctly without a human.
4. **Final dark run (local):** fresh room + this repo; dispatch stage 1 (then 2) with the full spec
   pasted in; do not intervene. Export `room.json`. Run the isolated harness check.
5. **Submission:** rewrite this README, finish `FACTORY.md` with real numbers, record the video
   (room recording + walkthrough), make the repo public, submit on lablab.

## Division of labour

- Cloud session: everything that is a file in this repository (mandates, FACTORY.md, README, notes).
- Local session: BAND Desktop, seats, Docker, harness runs, the final run, the video.
