# FACTORY.md

How to stand up this factory, why it is built this way, what it cost, and how it catches bad
work. Sections marked `TODO(measure)` are filled in from real runs before submission; nothing
here is estimated.

## 1. Overview

A band of five Claude Code seats in BAND Desktop, sharing one result repository. One seat
plans and routes, one writes code, one verifies independently, one audits the specification
against the shipped checks and seeds faults, and one uses the product as its users would. The
human's dispatch message is the only human input per stage.

```
            dispatch (human)
                  |
                 @coordinator
        /        /        |        \
 @spec-auditor @implementer @reviewer @customer
  ledger, gaps,   commits   reference  real interface,
  fault seeding             model      screenshots
        \        \        |        /
                 @coordinator  -> accept / route back -> final report
```

The mandates in `mandates/` contain no problem-specific detail. Point the same five files at
a different specification and the factory runs unchanged; the specification travels in the
dispatch message and in every handoff.

## 2. Seats

| Seat (as BAND shows it) | Mandate | Harness | Model | Owns | Never does |
|---|---|---|---|---|---|
| coordinator | `mandates/coordinator.md` | Claude Code | claude-sonnet-5-5 | intake, handoffs, routing, final report | writes code or tests |
| implementer | `mandates/implementer.md` | Claude Code | claude-sonnet-5-5 | code and commits | accepts its own work |
| reviewer | `mandates/reviewer.md` | Claude Code | claude-opus-5-5 | independent verification, including a reference model written from the specification and random operation sequences compared against it | edits code |
| spec-auditor | `mandates/spec-auditor.md` | Claude Code | claude-opus-5-5 | requirements ledger, gap list, and fault seeding: breaking one requirement at a time in a throwaway copy to prove the evidence catches it | edits code, writes tests to pass |
| customer | `mandates/customer.md` | Claude Code | claude-sonnet-5-5 | using the product through its real interface at desktop and phone widths, screenshots of every named state | edits code, reads the implementation to judge it |

Model ids in the table match the `Model:` first line of each mandate. Change both together.

## 3. Standing it up

Prerequisites: macOS or Linux, Git, a running Docker daemon, Python 3.12+ (only for the event
harness), BAND Desktop 0.4.12+ with an account, and the Claude Code CLI signed in to a plan that
covers the models in section 2.

1. **Sign the CLI in and update it.** Seats run the terminal `claude` CLI, not the Claude desktop
   app, and it has its own login. Check with `claude auth status` (must show `loggedIn: true`);
   if not, run `claude auth login`. Run `claude update`: `claude-opus-5-5` needs Claude Code
   2.1.280 or newer, and an older CLI fails every Opus turn with an API 400.
2. **Create the five seats** from the directory the band works in. Each seat's instructions are
   live-linked to its mandate file, so editing a mandate updates the seat and the file in this
   repository is exactly what the seat ran:

   ```sh
   for seat in coordinator:claude-sonnet-5-5 implementer:claude-sonnet-5-5 \
               reviewer:claude-opus-5-5 spec-auditor:claude-opus-5-5 \
               customer:claude-sonnet-5-5; do
     name=${seat%%:*}; model=${seat#*:}
     band agent create --session "df-$name" --name "$name" \
       --description "Dark Factory seat: $name" --cwd "$WORKSPACE" \
       --transport claude-code-cli --runtime-model "$model" \
       --instructions-file "$RESULT_REPO/mandates/$name.md"
   done
   band list    # all five: Connected running=true
   ```

   Defaults kept: permission mode `auto` (unattended, with Claude Code's own safety checks) and
   context mode `local_config` (the only mode that can use a subscription login; `bare` needs an
   API key).
3. **Restart after any CLI change:** `band restart --as <owner>/<seat>`. A pending message is
   redelivered to the restarted seat, so work resumes where it stopped.
4. **Dispatch** from BAND Desktop: Home, Assign work, pick `coordinator`, paste the dispatch
   message (section 4). The coordinator adds the other seats to the room itself.
5. **Start the seat watchdog** just before dispatching, in a terminal that stays open:
   `tools/seat-watchdog.sh <owner> 60 seat-watchdog.log`. Every minute it reads `band status`
   for each seat and restarts any room session whose runtime has disconnected; BAND then
   redelivers the pending message. It never writes to the room or the repository, so it adds
   no human input. Its log is kept with the run.
6. **Fingerprint the shipped checks** before dispatch, so anyone can confirm they were not
   edited during the run: `find <kickoff>/<track>/test -type f -name '*.py' | sort | xargs shasum -a 256 > checks.sha256`,
   then `shasum -a 256 -c checks.sha256` after the final report. Both results go in section 7.
7. **Record the room**: room menu, Open in Band, Download full session, save as `room.json`.
8. **Measure**: `tools/factory_numbers.py --transcripts <claude-projects-dir-for-the-workspace>
   --repo <result-repo> --since <dispatch-time> --room room.json` prints the spend, time and
   verdict tables used in section 7 from the seats' transcripts, the git history and the room
   export, so every figure can be regenerated. It also lists every ACCEPT and REJECT with its
   time, revision and `room.json` message id; claims in sections 6 and 7 cite those ids.

TODO(measure): time the full setup on a clean machine.

## 4. The dispatch message

The dispatch is the whole human contribution. It contains: the workspace and result
repository absolute paths, the stage number, the complete specification text for the stage,
where the shipped checks live, the run contract (how the deliverable is built, started and
checked: configuration and port, network use at run time, start-up time limit), and how to
carry the previous stage forward. The mandates deliberately hold none of these details. It
contains no
opinions about how to build, and nothing else is sent until the stage report arrives.

TODO(measure): add the exact template used in the submitted run, with the specification text
replaced by a placeholder.

## 5. Design choices and why

| Choice | Reason |
|---|---|
| Self-contained handoffs, specification pasted every time | A seat sees only messages addressed to it; pointers to earlier messages fail silently |
| Reviewer runs checks itself from a clean build | The implementer's report is a claim, not evidence |
| A separate spec-auditor | Shipped checks cover part of the specification; the audit targets the rest |
| Implementer builds from a checklist taken from the specification, not from the checks | Code written to the checks is disqualifying and does not generalise |
| Reject rounds counted per item, with a change of approach after three | Prevents loops in which the same instruction is repeated |
| Fix forward, no history rewriting | The commit trail is the evidence of who did what |
| Each seat commits under its own Git identity | History and room log can be matched seat by seat |
| Reviewer also reads the commit history, not only the code | Catches mixed commits, committed caches and signs of building to the checks |
| Fault seeding by the auditor | Passing evidence proves little unless it fails against wrong code; the auditor breaks one requirement at a time and counts how many breaks the evidence catches |
| A reference model written from the specification only | The reviewer's model cannot inherit the implementation's mistakes; random operation sequences find orderings no hand-written test tries |
| The look of a visual interface is a requirement: the implementer builds a design system first and checks every screen at the narrowest and a desktop width; the customer rejects layout breaks and low contrast with screenshots and measured ratios | The specification asks for a presentation-ready product; in practice run 3 a navigation label wrapped mid-word at phone width and nothing in the process was set up to stop it |
| A customer seat that never reads the code | Judges only what a user can observe, which is what the interface part of the specification describes |
| An accept stays provisional until the auditor's walk is closed | In practice run 2 the reviewer accepted a revision the auditor then showed to break a stated rule |
| Every report is a new top-level message tagged with its recipients, checked after sending | A seat wakes only when a message addressed to it arrives; a lost or threaded report stops the run silently |
| No seat ends a turn with a background job still running | A job left running when the turn ends can be stopped with its results unreported |
| Stages are pipelined: the next one starts once reviewer and customer accept, while the auditor finishes | The auditor's fault seeding was the slowest step of practice run 3; the implementer no longer waits for it, and a late finding is fixed in both stage folders |
| Fault seeding is capped at 12–15 faults per stage, full set once, fix-scoped afterwards | Enough faults to compare the band's evidence with the shipped checks, without a 25-minute walk on every revision |
| The auditor reports a blocking gap the moment it finds one | The implementer can fix while fault seeding continues, instead of waiting for the full report |
| The coordinator treats committed report files as verdicts | A report that reached the repository but not the room still moves the stage forward |
| A watchdog restarts disconnected seats | A crashed runtime cannot report or wake; restarting it redelivers its pending message |
| Opus for reviewer and auditor, Sonnet for coordinator, implementer and customer | TODO(measure): confirm this split against results and cost |

## 6. Catching and recovering from bad work

| Failure | Caught by | Recovery |
|---|---|---|
| Code special-cased to the checks | reviewer diff read; auditor scenarios not in the checks | reject with reproduction; implementer fixes forward |
| Requirement never exercised by a shipped check | spec-auditor gap list, then follow-up on each revision | gap is blocking until met, with evidence |
| Implementer's claim does not match the tree | reviewer clean build at the reported hash | reject; coordinator trusts evidence over claims |
| Loop of repeated rejects | coordinator's per-item count | split the item or change the approach |
| Silent or absent seat | coordinator resend once, then continue | failure and attempt recorded in the final report |
| Seat runtime crashes mid-stage | seat watchdog (`band status` shows the session disconnected) | `band restart` of that session; the pending message is redelivered |
| Shipped checks blind to a broken requirement | spec-auditor fault seeding | the surviving fault is an open gap until the band's evidence catches it |
| Earlier stage broken by extension | reviewer runs all earlier stages' checks | reject; carried-forward behaviour must be intact |
| Build works locally but not clean | reviewer isolated-mode run | reject with the failing command |

Example from practice run 2 (`pocketful` stage 1, 30 Sep 2026; the submitted run will add its
own). The first revision passed all 147 shipped checks. The auditor had split the specification
into 37 numbered requirements and walked the code against them; three reject rounds followed:

| Time | What happened |
|---|---|
| 08:48 | First revision handed to reviewer and auditor; shipped checks 147/147 |
| 08:53 | Reject 1: oversized integers, invalid imported state and oversized `limit`/`offset` values returned the wrong error class or a server error, although the specification says requests must never produce 5xx |
| 08:58 | Reject 2: auditor gap O4, a remaining input-validation case |
| 09:02 | Reviewer accepts revision `50703dd` |
| 09:03 | Reject 3: auditor gap O5, an oversized request header returned the web server's HTML error page instead of the specification's JSON error body. The coordinator withdrew the accept and sent the fixed revision to both checkers again |
| 09:07 | Accept of `86121fc`; isolated check claims stage 1 |

None of these three rejects was visible to the shipped checks. That is the reason the auditor
exists.

TODO(measure): replace or extend with the submitted run's example.

## 7. Measured results

All figures come from the submitted run. Leave blank until measured.

### Time

| Stage | Dispatch | Final report | Wall clock | Reject rounds |
|---|---|---|---|---|
| 1 | TODO | TODO | TODO | TODO |
| 2 | TODO | TODO | TODO | TODO |
| 3 | TODO | TODO | TODO | TODO |
| 4 | TODO | TODO | TODO | TODO |

### Model spend

| Seat | Model | Input tokens | Output tokens | Cost |
|---|---|---|---|---|
| coordinator | claude-sonnet-5-5 | TODO | TODO | TODO |
| implementer | claude-sonnet-5-5 | TODO | TODO | TODO |
| reviewer | claude-opus-5-5 | TODO | TODO | TODO |
| spec-auditor | claude-opus-5-5 | TODO | TODO | TODO |
| customer | claude-sonnet-5-5 | TODO | TODO | TODO |
| **Total** | | TODO | TODO | TODO |

Source of the numbers: TODO (state where each was read from).

### Outcome

TODO: highest stage claimed on the shipped checks, and the isolated-mode result.

## 8. What we tried that failed

Practice run 1 (unscored `toy` track, stage 1, 30 Sep 2026): dispatch to accepted revision in
about 10 minutes with no human input after dispatch; the implementer waited for the auditor's
gap list before building; 12 of 12 audited requirements met; reviewer passed host and isolated
checks. What we changed as a result:

- Setup failed twice before any work: the seats' CLI was signed out, then too old for
  `claude-opus-5-5`. Both are now explicit setup steps (section 3).
- Every commit carried the repository's default Git identity, so history could not show which
  seat wrote the code. The implementer mandate now commits under the seat's own identity.

Practice run 2 (`pocketful` stage 1, 30 Sep 2026): 29 minutes, 10 commits, three reject rounds
(section 6), accepted with the isolated check claiming stage 1. About 13% of a five-hour Max
plan window. The coordinator's report listed three process faults, and each changed a mandate:

- The implementer put several work items into two commits. It now commits one item per commit,
  and the reviewer rejects mixed commits.
- The implementer opened a shipped check file to see the project layout, and said it used
  nothing from it. Opening the check files is now forbidden outright; the check command's output
  is the only interface, and the reviewer looks for signs of it in the history.
- A cache directory was committed and later removed. The implementer now adds an ignore file
  before the first commit.
- One handoff to the reviewer went missing; the coordinator's resend-once rule recovered it
  without human input.

Practice run 3 (`pocketful` stages 1 and 2, five seats, 2 Oct 2026). Stage 1 was written in
ten single-item commits and passed all 147 shipped checks in host and isolated mode. The
reviewer accepted it after a reference model ran 14,400 random steps and 750 concurrent
operations without a mismatch. The auditor then found a blocking defect none of that had
caught: a lone UTF-16 surrogate in a note moved the money, closed the connection without a
response, and broke every later activity read that included the record. The implementer fixed
it with a regression test, and the reviewer and customer re-verified the fix.

Fault seeding on stage 1 showed why the auditor exists:

| Evidence | Faults caught, of 25 seeded |
|---|---|
| Shipped checks | 3 |
| The band's evidence (auditor probes, reviewer model, implementer tests) | 23 |
| Only a static check added during the walk (a removed global lock) | 1 |
| Not caught: equivalent at the specification's one-second timestamp resolution | 1 |

One fault slipped through on the first walk; the auditor strengthened that probe and caught it
on the second. What we changed as a result:

- The auditor's commits carried the repository's default identity. Every mandate now carries
  the seat-identity commit rule, not only the implementer's and the customer's.
- The auditor's runtime crashed while it was sending its report: the report never reached the
  room, no seat woke, and the run stood still until the seat was restarted. The mandates now
  require top-level, tagged messages checked after sending and forbid ending a turn with a
  background job running; the coordinator reads committed reports when it wakes; and a seat
  watchdog restarts disconnected runtimes (section 3).
- The auditor held a blocking finding until fault seeding finished. It now reports blocking
  gaps at once.
- The auditor's ledger folder was named differently from this file. Folder names are now fixed
  in the mandates: `ledger/`, `verification/`, `customer/`.

## 9. Limits and known weaknesses

- The auditor and reviewer read the same specification as the implementer. A requirement all
  three misread is not caught; only the hidden checks would show it.
- Rules about process (one item per commit, not opening check files) are enforced by review
  after the fact, not prevented. A seat can break one and be rejected, which costs a round.
- Seats run on the host with Claude Code's `auto` permission mode, not in a sandbox; the
  factory trusts the model's own safety checks for commands.
- A lost message is recovered by one resend; a seat that stays silent after that is reported,
  not replaced. A seat only acts when a message wakes it, so a report that never reaches the
  room can stall a stage; the committed-report rule and the watchdog narrow this gap but do
  not close it.
- TODO(measure): add anything the submitted run shows.

## 10. What we did not test

- Hidden checks: only the shipped part of each stage's suite was run; the rest is the judges'.
- A container restart in the middle of a write: the specification allows state to be lost on
  restart, and no seat tried to kill the service during a request.
- Load beyond the specification's stated concurrency (50 requests in flight).
- Browsers other than the headless Chromium the customer seat drives.
- Long runs: each practice and the submitted run covered hours, not days.

## 11. Reusing this factory on a different problem

1. Copy `mandates/` and this file.
2. Rename seats and edit the `Harness:` and `Model:` lines if yours differ.
3. Write a dispatch message (section 4) carrying your own specification.
4. Run one stage; read the reject and gap reports; adjust mandates if a seat misbehaves.
