# FACTORY.md

> **In the submitted run the spec-auditor seeded 81 faults, one at a time, across the four
> stages, in the requirements it judged highest-risk. The shipped checks, a partial sample by
> design, caught 8 of them; the band's own evidence caught 75, those 8 included.** The other 6 changed no observable
> behaviour. On five revisions, three Claude verifiers accepted and only the Codex cross-auditor
> rejected; twice the customer rejected a layout the reviewer had accepted (section 6). The
> factory is built to measure whether its evidence works, not only whether the checks are green.

How to stand up this factory, why it is built this way, what it cost, and how it catches bad
work. Figures in sections 6 and 7 come from the submitted run (4 Oct 2026, one dispatch, all four
stages). Counts of verdicts, commits, messages and seeded faults can be checked against this
repository (the README's evidence index gives the commands). Spend and token counts were read
from the seats' transcripts by `tools/factory_numbers.py`; the transcripts are not in this
repository, so those rows can be priced again from `tools/prices.json` but not regenerated from a
clone. Files this document cites from outside the seats' folders are in `docs/evidence/`.

## 1. Overview

A band of six seats in BAND Desktop, sharing one result repository: five Claude Code seats and
one Codex seat. One seat plans and routes, one writes code, one verifies independently, one
audits the specification against the shipped checks and seeds faults, one uses the product as
its users would, and one audits every revision again on a different model family, without
seeing the others' work. The human's dispatch message is the only human input per stage.

```
            dispatch (human)
                  |
                 @coordinator
        /        /        |        \          \
 @spec-auditor @implementer @reviewer @customer @cross-auditor
  ledger, gaps,   commits   reference  real      own walk on a
  fault seeding             model      interface second model family
        \        \        |        /          /
                 @coordinator  -> accept (all four verifiers) / route back -> final report
```

The mandates in `mandates/` contain no problem-specific detail. Point the same six files at
a different specification and the factory runs unchanged; the specification travels in the
dispatch message and in every handoff. What we have to show for that, and what we do not, is in
section 11.

## 2. Seats

| Seat (as BAND shows it) | Mandate | Harness | Model | Owns | Never does |
|---|---|---|---|---|---|
| coordinator | `mandates/coordinator.md` | Claude Code | claude-sonnet-5-5 | intake, handoffs, routing, final report | writes code or tests |
| implementer | `mandates/implementer.md` | Claude Code | claude-sonnet-5-5 | code and commits | accepts its own work |
| reviewer | `mandates/reviewer.md` | Claude Code | claude-opus-5-5 | independent verification, including a reference model written from the specification and random operation sequences compared against it | edits code |
| spec-auditor | `mandates/spec-auditor.md` | Claude Code | claude-opus-5-5 | requirements ledger, gap list, and fault seeding: breaking one requirement at a time in a throwaway copy to prove the evidence catches it | edits code, writes tests to pass |
| customer | `mandates/customer.md` | Claude Code | claude-sonnet-5-5 | using the product through its real interface at desktop and phone widths, screenshots of every named state, and whether each screen looks finished as a whole | edits code, reads the implementation to judge it |
| cross-auditor | `mandates/cross-auditor.md` | Codex | gpt-6-astra | a second, independent walk of every revision against the specification on a different model family ([ADR-002](docs/decisions/ADR-002-a-second-model-family.md)) | edits code, reads other verifiers' files before its own verdict, reads shipped check sources |

Model ids in the table match the `Model:` first line of each mandate. Change both together.

## 3. Standing it up

Prerequisites: macOS or Linux, Git, a running Docker daemon, Python 3.12+ (only for the event
harness), BAND Desktop 0.4.12+ with an account, the Claude Code CLI signed in to a plan that covers the
Claude models in section 2, and the Codex CLI signed in to a ChatGPT plan (it ships inside the
ChatGPT desktop app; BAND needs Codex 0.146.0 or newer).

1. **Sign the CLI in and update it.** Seats run the terminal `claude` CLI, not the Claude desktop
   app, and it has its own login. Check with `claude auth status` (must show `loggedIn: true`);
   if not, run `claude auth login`. Run `claude update`: `claude-opus-5-5` needs Claude Code
   2.1.280 or newer, and an older CLI fails every Opus turn with an API 400.
2. **Create the six seats** from the directory the band works in. Each seat's instructions are
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
   # the sixth seat runs on Codex; probe first with --dry-run (without --instructions-file)
   band agent create --session df-cross-auditor --name cross-auditor \
     --description "Dark Factory seat: cross-auditor" --cwd "$WORKSPACE" \
     --transport codex-app-server --spawn-command "$CODEX_BIN" \
     --runtime-auth subscription --runtime-model gpt-6-astra --runtime-effort high \
     --runtime-approval never --runtime-sandbox danger-full-access \
     --instructions-file "$RESULT_REPO/mandates/cross-auditor.md"
   band list    # all six: Connected running=true
   ```

   Defaults kept: permission mode `auto` (unattended, with Claude Code's own safety checks) and
   context mode `local_config` (the only mode that can use a subscription login; `bare` needs an
   API key).
3. **Restart after any CLI change:** `band restart --as <owner>/<seat>`. A pending message is
   redelivered to the restarted seat, so work resumes where it stopped.
4. **Dispatch** from BAND Desktop: open a new room with all six seats in it, tag `coordinator`
   and paste the dispatch message (section 4). In the submitted run the six seats joined the room
   at 10:50 and the dispatch followed at 10:53.
5. **Start the seat watchdog** just before dispatching, in a terminal that stays open:
   `tools/seat-watchdog.sh <owner> 60 seat-watchdog.log`. Every minute it reads `band status`
   for each seat and restarts any room session whose runtime has disconnected; BAND then
   redelivers the pending message. It never writes to the room or the repository, so it adds
   no human input. The submitted run's log is `docs/evidence/seat-watchdog.log` (started, never
   needed), and the kicker's is `docs/evidence/window-kicker.log`.
   If the run may outlast the plan's usage window, also start the window kicker:
   `tools/window-kicker.sh <owner> <HH:MM of the reset> <result-repo> 20 window-kicker.log`. One
   minute after the reset it checks the history; if no Claude seat has committed in 20 minutes it
   restarts every bound room session, and BAND redelivers the work the limit interrupted. It
   ignores the Codex seat's commits, because that seat runs on a separate plan and keeps working
   while the Claude seats wait. Like the watchdog, it never writes to the room or the repository.
6. **Fingerprint the shipped checks** before dispatch, so anyone can confirm they were not
   edited during the run: `find <kickoff>/<track>/test -type f -name '*.py' | sort | xargs shasum -a 256 > checks.sha256`,
   then `shasum -a 256 -c checks.sha256` after the final report. Both results go in section 7; the
   submitted run's file is `docs/evidence/checks.sha256`.
7. **Record the room**: room menu, Open in Band, then in the console scroll the session up to its
   first message before choosing Download full session, and save as `room.json`. The console
   loads messages as you scroll: in the submitted run the first download held only the last 1,700
   of 6,783 messages (the last hour). Count the messages, or compare with
   `band room messages <room-id> --json` (it reports `total_pages`), before committing.
8. **Measure**: `tools/factory_numbers.py --transcripts <claude-projects-dir-for-the-workspace>
   --repo <result-repo> --since <dispatch-time> --room room.json --prices tools/prices.json --workspace <band working directory>`
   prints the spend, time and verdict tables used in section 7 from the seats' transcripts, the
   git history, the Codex seat's session logs and the room export (the submitted run's output is `docs/evidence/factory-numbers.txt`). Cost is at Anthropic's
   public API list prices (`tools/prices.json`; the seats run on a subscription, so this is the
   equivalent API cost, not an invoice). It also lists every ACCEPT and REJECT with its
   time, revision and `room.json` message id; claims in sections 6 and 7 cite those ids. That
   list counts verdict messages in the room, which is not the same as the verdict files the seats
   committed: a seat may restate a verdict, and the coordinator relays some. The reject counts in
   this document are from the committed verdict files.

## 4. The dispatch message

The dispatch is the whole human contribution. It contains: the workspace and result
repository absolute paths, the stage number, the complete specification text for the stage,
where the shipped checks live, the run contract (how the deliverable is built, started and
checked: configuration and port, network use at run time, start-up time limit), and how to
carry the previous stage forward. The mandates deliberately hold none of these details. It
contains no
opinions about how to build, and nothing else is sent until the stage report arrives.

For a stage with a visual interface the dispatch may also carry a short written visual direction
(character, palette, type and layout principles, no code) and images of materials and colours
(no screens or layouts). In the submitted run it did: the brief and its two images, a mood image
and a palette swatch, are in `docs/evidence/visual-brief/`. Every screen, component and line of
code was still designed and written by the band, and the room log shows it.

The submitted run's dispatch (3,579 characters, `room.json` message at 07:53:48 UTC, the only
human message in the room), with paths shortened to placeholders:

```text
@coordinator Build all four stages of this job end to end with the band, without asking me
anything. Work the stages in order, pipelined as your instructions describe: the next stage
starts once the reviewer and the customer have accepted the current one, and every stage must
still close with all four verifiers' accepts.

Kickoff package (specs and shipped checks): <KICKOFF>
Track: <TRACK>
Specifications: <KICKOFF>/<TRACK>/spec/stage-1.md through stage-4.md (read each in full; paste
the full text of the current stage into every handoff; every earlier stage's requirements
continue to apply).
Shipped checks (partial, read-only; never build to them; run them only through the check
command): <KICKOFF>/<TRACK>/test/stage_1/ through stage_4/
Result repository (absolute path, commit here, every file the band produces goes inside it): <RESULT>
Stage folders: <RESULT>/stage-1/ through stage-4/. Each is a complete service with its own
Dockerfile and RUN.md; stage N+1 starts as a copy of the accepted stage N, carried forward and
extended. Stage folders contain no .git. Do not change mandates/, tools/, docs/, README.md or
FACTORY.md.

Run contract (from spec sections 2-3; it applies to every stage):
- <the specification's build, port, health, reset, network and resource rules, copied as stated>

Check command (run from the kickoff package directory; use a new --out name every time):
<the event harness command for stage N>. The final check of each stage must also pass with
--mode isolated added.

Tools: <where Docker and the headless browser are installed>.

Visual direction for the browser interface: <path to the written brief>; read it in full and
paste its whole text, with the two image paths it names, into the stage-2 handoff to
@implementer and @customer.

Done means, for each stage: the isolated check prints "claimed stage: N"; the spec-auditor has
no open gaps that cite a specification sentence and has reported its fault-seeding results; the
reviewer has accepted the committed revision; the customer has accepted it (from stage 2:
screens at desktop and phone widths, screenshots committed in the result repository); the
cross-auditor has accepted it. A stage is closed only with all four accepts on the same
revision. Then report back here once, covering all four stages, with the measurement table
your instructions ask for.
```

## 5. Design choices and why

What the main choices cost in the submitted run:

| Choice | Cost |
|---|---|
| A separate spec-auditor on Opus | 35.79 USD, 27 % of the Claude seats' spend |
| A cross-auditor on a second model family | 71.30 USD at OpenAI list prices, 35 % of the run's 202.59; a second subscription and harness; 22 points of the ChatGPT plan's weekly allowance; 13 of the run's 27 reject verdicts, each a further round |
| Four accepts on the same revision | stage 4 took 11 revisions and 13 rejects over 3 h 18 min |
| The specification pasted into every handoff | the coordinator wrote 1.74 million characters of room text, against 35,000 to 79,000 for each other seat, and cost 12.89 USD |
| Pipelined stages | a late finding in one stage is fixed in every later stage folder too |
| Seats on plan subscriptions | 57 minutes of wall clock lost to the usage window |

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
| Fault seeding is capped at 12–15 faults per stage, full set once, fix-scoped afterwards | Enough faults to compare the band's evidence with the shipped checks, without a 25-minute walk on every revision. Stage 1 ended at 32 because each fix-scoped round added faults in the code the fix changed (15 on the first revision, then 24, 30 and 32) |
| The spec-auditor is the only seat that reads the shipped check sources | It lists what they do not exercise. Its mandate forbids telling the implementer how the checks work; the implementer and the cross-auditor never open them |
| The auditor reports a blocking gap the moment it finds one | The implementer can fix while fault seeding continues, instead of waiting for the full report |
| The coordinator treats committed report files as verdicts | A report that reached the repository but not the room still moves the stage forward |
| A watchdog restarts disconnected seats | A crashed runtime cannot report or wake; restarting it redelivers its pending message |
| A sixth seat and fourth verifier, the cross-auditor, on a different model family, blind to the other verifiers until its own verdict | On one revision Codex found seven specification breaks the all-Claude band had accepted, and Opus found the one Codex missed: the blind spots do not overlap ([ADR-002](docs/decisions/ADR-002-a-second-model-family.md)) |
| Every verifier commits its verdict as a file named after the revision, for every revision | In practice run 5 the reviewer's verdict went into a thread, the coordinator never saw it, and the run stopped one message short of closing |
| The implementer does not commit while a revision is under review; findings are fixed together in one revision | In practice run 6 test-only commits made five revisions in 25 minutes, and every one voided the accepts already given |
| "The evidence" in fault seeding means all of the band's committed checks; a fault only the auditor's own probe catches is a suggested test, not a blocking gap | In practice run 6 the auditor seeded against the implementer's tests alone and rejected correct code |
| The customer judges each screen as a whole, not only rule by rule | In practice run 4 every measured rule passed while the desktop layout left a large empty column |
| The dispatch stays under about 3,600 characters (the submitted one is 3,579); a visual direction travels as a file path | BAND turns a longer paste into an attachment instead of a message |
| Opus for reviewer and auditor, Sonnet for coordinator, implementer and customer | The auditor is the most expensive seat (48 % of practice run 3's spend) and the only one that caught what the reviewer accepted; the trade-off, the rejected options and what we do not know are in [ADR-001](docs/decisions/ADR-001-keep-the-spec-auditor.md). In the submitted run the auditor was 27 % of the Claude seats' spend (35.79 of 131.29 USD) and ran the fault seeding behind the headline numbers |
| A kicker restarts the seats after the plan's usage window resets | In the submitted run the Claude seats stopped at the session limit at 13:32–13:34 with stages 3 and 4 open; the kicker woke them at 14:31 and the run closed without a human message |

## 6. Catching and recovering from bad work

One defect, start to finish (submitted run, stage 1; the full timeline is below). At 11:00
revision `69289b3` passed the shipped stage-1 checks, and by 11:25 the customer, the reviewer and
the spec-auditor had accepted it. At 11:21 the cross-auditor rejected it [`8744646d`] with 529
assertions of its own, 21 of them failed: among others, a fractional amount such as
`1.0000000000000001` was rounded to 1 and moved money. The implementer fixed case by case, and
the cross-auditor rejected two more revisions (`145b98e`, `0e8dea4`), the last for a hand-edited
import that let a paid request be paid twice [`2fbfbb49`]. At 11:56 the implementer replaced the
case-by-case fixes with one state checker shared by reset and import. By 12:17 all four verifiers
had accepted `999fda2`. Before: three accepts and green shipped checks on code that moved money
on a malformed amount. After: one validator, and all 27 behaviour-changing faults seeded on that
revision caught.

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
| A blind spot shared by every Claude verifier | cross-auditor on Codex, which reads none of their files before its own verdict | reject with its own reproduction; the fix goes back to all four verifiers |
| Import of hand-edited or adversarial state that is slow rather than wrong | timing probes on a 2 CPU / 2 GiB container (reviewer, spec-auditor, cross-auditor) | reject with the measured time; after three rounds on one item the coordinator records a bound as a limitation (section 9) |
| Plan usage limit stops every Claude seat | window kicker after the reset | `band restart` of each bound session; the interrupted work is redelivered |

### The submitted run, stage 1

Times are local (UTC+3); ids in brackets are `room.json` message ids, other hashes are commits.

| Time | What happened |
|---|---|
| 10:53 | Dispatch, the only human message in the room |
| 11:00 | First complete revision `69289b3`, with the implementer's own tests |
| 11:05–11:25 | customer [`2bb07019`], reviewer [`a347a36e`] and spec-auditor (`fb683c9`) accept `69289b3` |
| 11:17–11:24 | implementer fixes, one by one, the gaps the cross-auditor sends as it confirms them |
| 11:21 | cross-auditor's verdict on `69289b3` [`8744646d`]: REJECT, 529 assertions of its own, 21 failed. Fractional amounts such as `1.0000000000000001` rounded to 1 and moved money; a 5,000-digit `limit` gave a 500; an import with a malformed timestamp or an over-limit amount was accepted |
| 11:30 | reviewer's stage-2 reject [`650cff19`] finds a fourth, also present in stage 1: equal JSON numbers `1.5` and `1.50` treated as different request bodies |
| 11:38 | cross-auditor rejects the fix `145b98e` [`f364c7a9`]: the number `0.1` and the string `"0.1"` count as the same body; an import with a tampered idempotency receipt is accepted |
| 11:49–11:59 | customer [`5ef8fd84`], reviewer [`1106c397`] and spec-auditor (`dc95184`, fault seeding 30 of 30) accept `0e8dea4` |
| 11:54 | cross-auditor rejects `0e8dea4` [`2fbfbb49`] with four import gaps, one of them a paid request that a hand-edited import lets be paid a second time |
| 11:56 | implementer replaces the case-by-case fixes with one state checker shared by reset and import, with property and mutation tests |
| 12:10–12:17 | all four accept `999fda2`: cross-auditor [`94e8164a`], reviewer, customer, spec-auditor (fault seeding 32: 27 caught, 5 equivalent). Stage 1 closed |

Three Claude verifiers accepted `69289b3` and `0e8dea4`; the Codex seat alone rejected both. The
same pattern repeated on `7c35a2a` (stage 3), `8bbd03a` and `2bd67ec` (stage 4): five revisions in
all. The Claude verifiers in turn caught what others accepted: in stage 2 the customer rejected
`9992acd` for a desktop layout with a large empty column, and then `94e856c` for a button label
crowding the edge of its pill. The reviewer had accepted both, and the cross-auditor went on to
accept `94e856c` [`d38303fb`] after the customer's reject [`960f2442`].

An earlier example, from practice run 2 (`pocketful` stage 1, 30 Sep 2026). The first revision passed all 147 shipped checks. The auditor had split the specification
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

## 7. Measured results

All figures come from the submitted run on 4 Oct 2026: one dispatch at 10:53:48 (UTC+3) for all
four stages, coordinator's final report at 16:00 (`coordinator/final-report.md`).

### Time

| Stage | First stage commit | Closed (fourth accept) | Wall clock from first stage commit | Reject verdicts | Revisions judged |
|---|---|---|---|---|---|
| 1 | 10:57 | 12:17 (`999fda2`) | 1 h 20 min (1 h 23 min from dispatch) | 6 | 5 |
| 2 | 11:11 | 13:14 (`d78f1bd`) | 2 h 03 min | 4 | 5 |
| 3 | 12:21 | 15:04 (`397a149`) | 2 h 43 min, of which 57 min paused | 4 | 5 |
| 4 | 12:41 | 15:59 (`000d7ac`, the reviewer's accept under a coordinator ruling) | 3 h 18 min, of which 57 min paused | 13 | 11 |
| **Run** | | | **5 h 06 min to the final report, of which 57 min paused: about 4 h 09 min working** | **27** | |

Stages overlap because they are pipelined. The pause: four of the five Claude seats logged the
plan's session-limit error between 13:32 and 13:34 (coordinator, implementer, customer and
spec-auditor; `room.json` error messages). The reviewer logged none; its last commit before the
pause was at 13:32. The window kicker restarted all six seats at 14:31, and the next verdict was
committed at 14:34. Reject verdicts are counted from the verdict
files the seats committed, as they stand at the end of the run (one file per seat per revision; the
reviewer's reject of `000d7ac`, superseded a minute later by its accept under the coordinator's
ruling, would be a 28th); "revisions judged" counts distinct
revisions with at least one verdict file.

| Seat | Reject verdicts | Commits |
|---|---|---|
| cross-auditor | 13 | 23 |
| reviewer | 8 | 27 |
| spec-auditor | 4 | 17 |
| customer | 2 | 19 |
| implementer | (fixes) | 56 |
| coordinator | (routing, rulings, report) | 2 |

### Model spend

| Seat | Model | Input | Output | Cache write | Cache read | Cost (USD, list) |
|---|---|---|---|---|---|---|
| coordinator | claude-sonnet-5-5 | 654 | 154,994 | 444,187 | 47,813,881 | 12.89 |
| implementer | claude-sonnet-5-5 | 836 | 511,375 | 1,056,390 | 142,757,336 | 37.89 |
| reviewer | claude-opus-5-5 | 694 | 379,594 | 891,757 | 90,851,348 | 32.90 |
| spec-auditor | claude-opus-5-5 | 718 | 375,155 | 950,425 | 103,391,076 | 35.79 |
| customer | claude-sonnet-5-5 | 398 | 224,099 | 584,655 | 36,190,642 | 11.82 |
| **Claude seats** | | 3,300 | 1,645,217 | 3,927,414 | 421,004,283 | **131.29** |
| cross-auditor | gpt-6-astra | 1,298,238 | 233,098 | – | 46,662,400 | 71.30 |
| **All six seats** | | | | | | **202.59** |

Source: the seats' Claude Code transcripts and the Codex seat's session logs, read by
`tools/factory_numbers.py` for the window from dispatch to 16:02 (its output is
`docs/evidence/factory-numbers.txt`; the transcripts themselves are not in this repository), priced with
`tools/prices.json` (Anthropic API list prices, cache writes at the 1-hour rate; cache reads are
listed at 0.20 USD per million tokens for both Opus 5.5 and Sonnet 5.5). The seats ran on
subscriptions, so this is the equivalent API cost, not an invoice. The Codex seat's row is priced
by hand from its token counts at OpenAI's list prices for gpt-6-astra (10 USD per million input
tokens, 1 cached, 50 output; none of its 346 requests passed the 272,000-token threshold of the
long-context rate, the largest prompt being 233,942 tokens); the script itself prints that row
without a cost. BAND's own estimate for the
room, which also prices the Codex seat, was about 182 USD. Plan meters read before and after the
run: Claude Max weekly 3 % to 14 % and one full five-hour window; ChatGPT Pro weekly 87 % to 65 %
remaining. The Claude weekly figure also includes the operator's own monitoring session, so it is
an upper bound. That session was a Claude Code session outside the room: it watched the result
repository's Git history and the kicker and watchdog logs, and at 13:24 it replaced the kicker
(section 8). It sent nothing to the room and committed nothing during the run.

### Outcome

| Check | Result |
|---|---|
| Isolated harness, `--stage 4 --mode isolated`, on the final repository | stages 1–4 pass, including each upgrade from the previous stage; **claimed stage: 4** on the shipped checks, 147/147, 35/35, 6/6 and 5/5 (`docs/evidence/isolated-stage-4/report.json`) |
| Shipped checks unchanged during the run | `shasum -a 256 -c` on the 11 check files: 11 OK (`docs/evidence/checks.sha256`) |
| Human messages in the room | 1, the dispatch |
| Seat restarts | watchdog: none needed; window kicker: one, all six seats, at 14:31 (`docs/evidence/window-kicker.log`) |

Fault seeding on the full set of each stage (one fault per throwaway copy; "caught" means a check
that passes on the unmodified copy fails):

| Stage | Revision | Seeded | Shipped checks caught | Band's evidence caught | Equivalent (no observable change) |
|---|---|---|---|---|---|
| 1 | `999fda2` | 32 | 6 | 27 | 5 |
| 2 | `d78f1bd` | 16 | 1 | 16 | 0 |
| 3 | `65dd709`, `7c35a2a` | 18 | 1 | 18 | 0 |
| 4 | `8bbd03a` | 15 | 0 | 14 | 1 |
| **All** | | **81** | **8** | **75** | **6** |

In these full-set seedings no fault that changed behaviour survived the band's evidence. The band's catches
do not rest on the auditor: the implementer's own tests caught 71 of the 75, and only 1 was caught
by the auditor's probe alone. Results
are in `audit/seed-results-stage-*.json` and `ledger/stage-*-faults.md`; later fix-scoped seedings
on revisions after these are in the same folder. In one of those, on stage 4, two faults (M01 and
M03 in `ledger/stage-4-faults.md`) were caught at first only by a probe the spec-auditor added
during the walk; the implementer then added tests that catch both. The auditor chooses the
faults and writes some of the probes, so this table compares two bodies of evidence on the
auditor's own sample; it is not a score of the shipped checks.

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

Practice run 4 (`pocketful` stage 2 only, built on run 3's accepted stage 1, 3 Oct 2026): a
rehearsal of the visual direction. Dispatch to three accepts in about 40 minutes, one reviewer
reject fixed in a minute. The palette check found all 13 brief colours in the source (run 3,
without a brief: 0 of 13). The customer measured every rule and accepted, but did not object to a
desktop layout that left one column mostly empty. The customer mandate now asks for a judgement
of each screen as a whole.

The cross-family experiment (3 Oct 2026, no room): the spec-auditor mandate run headless on
Codex against run 3's revision `1a0af59`, the one reviewer and customer had accepted. Codex did
not find the lone-surrogate defect. It did report nine others; seven reproduce on that revision
and on `ba26a06`, the revision all three Claude verifiers finally accepted (equal JSON numbers
treated as different bodies and different values as equal, an import accepting a negative
amount, 500 on very long `limit`/`offset` digits, a malformed body changing state, 500 on a
wrongly typed reset reference, an HTML 501 for OPTIONS). That result added the sixth seat.

Practice run 5 (`toy` stage 1, six seats): the Codex seat took handoffs, committed under its own
identity and posted verdicts. The run then stopped: the reviewer's last verdict went into a
thread and was never committed, the coordinator woke on another message, saw three accepts out
of four and ended its turn. Every verifier now commits a verdict file per revision.

Practice run 6 (`toy` stage 1, six seats, rerun): closed in about 28 minutes with all four
verdicts committed. The cross-auditor rejected the first build for connections reset under
200 concurrent requests; the fix came from its report. Two process faults remained and changed
mandates: test-only commits during review produced five revisions, and the auditor rejected
correct code because it counted only the implementer's tests as evidence.

The submitted run (all four stages, six seats, 4 Oct 2026) closed without a human message after
the dispatch. What went wrong around it, and every action the operator took outside the room:

- **The plan's usage limit stopped the band.** The Claude seats stopped at the session limit at
  13:32–13:34, with stages 3 and 4 open (four of the five logged the error in the room; the
  reviewer logged none); the Codex seat, on a separate plan, kept working. The
  window kicker had been started before the dispatch for this case.
- **The kicker would not have fired.** It woke the seats only if nothing had been committed in the
  last 20 minutes, and the Codex seat could still commit. At 13:24, before the limit and with the Claude plan's usage meter at 97 %, the operator
  replaced the running kicker with a version that ignores the Codex seat's commits (the one now
  in `tools/`). It fired at 14:31 and restarted all six seats.
- **Git stopped working on the host.** At 14:31 macOS had updated Xcode in the background, and
  every `git` command failed until its licence was accepted. The kicker's own history check failed
  with it (it read the last commit as missing, which happened to give the right decision). The
  operator ran `sudo xcodebuild -license accept` at 14:32; the first commit after the pause came at
  14:34. Nothing was sent to the room.
- **The Codex seat's safety filter ended three of its turns.** At 13:08, 13:31 and 14:44 a
  cross-auditor turn stopped with "flagged for possible cybersecurity risk" (`room.json` error
  messages). Nobody intervened; the seat posted its later verdicts in the turns that followed.
- **The laptop was on battery** at 20 % around 13:00 and was plugged in; a sleeping host would
  have stopped every seat.
- **The screen recording is in two files** (10:50–13:34 and 14:31–16:02); the room was idle
  between them.
- **The first room download was partial** (section 3, step 7).
- **Performance on adversarial imports took three rounds.** The implementer's first legacy import
  was quadratic; the second was near-linear except on two tampered inputs found by the
  spec-auditor and the cross-auditor; the third bounded those. The coordinator then recorded the
  remaining linear cost as a limitation instead of asking for a fourth revision (section 9). The reviewer had rejected `000d7ac`
  for exactly this at 15:59 (`512be73`) and issued its verdict again as an accept under the
  ruling a minute later (`bdca469`, restated in `28d24f0`). The ruling was the coordinator's own;
  no human message was involved.
- **One post-run edit.** The offline check read `key=lambda` in one of the auditor's mutation
  records as a credential. The operator rewrote `=` as `\u003d` in that JSON file in a separate
  commit; the parsed data is identical.

## 9. Limits and known weaknesses

- The auditor and reviewer read the same specification as the implementer. A requirement all
  of them misread is not caught; only the hidden checks would show it. The cross-auditor on a
  second model family narrows this, and the experiment above shows it does, but two families
  can still share a misreading.
- The Codex seat runs with approvals off and full disk access, like the Claude seats in `auto`
  mode; the factory trusts each harness's own safety checks.
- Rules about process (one item per commit, not opening check files) are enforced by review
  after the fact, not prevented. A seat can break one and be rejected, which costs a round.
- Seats run on the host with Claude Code's `auto` permission mode, not in a sandbox; the
  factory trusts the model's own safety checks for commands.
- A lost message is recovered by one resend; a seat that stays silent after that is reported,
  not replaced. A seat only acts when a message wakes it, so a report that never reaches the
  room can stall a stage; the committed-report rule and the watchdog narrow this gap but do
  not close it.
- Known open limitation in the delivered stage 4: importing an export that carries older-format
  saved statements costs time linear in (statements × later payments). On 2 CPU / 2 GiB at 10,000
  later payments, about 200 such statements fit in the 5 s request limit; 300 take 5.2–6.7 s. The
  coordinator accepted this as a bound after three rounds; the fix direction is in
  `coordinator/final-report.md`.
- The coordinator made judgement calls the specification does not settle, listed in its final
  report for the human to review (which earlier states an older-format statement may match on
  import, and judging a revision on its net diff). The verifiers then applied them; a different
  reading by the hidden checks would not be caught.
- The coordinator's final report is thinner for stages 1 and 2 than its mandate asks: it took
  their accepts from the commit log and did not read those verdict files again, and its table of
  rejects and fixes covers stages 3 and 4 only. The verdict files themselves are complete.
- The run depends on the plan's usage window. A limit stops the Claude seats mid-stage; the kicker
  resumes them, but the wall clock grows by the wait.
- The kicker restarts every bound session, including seats that had nothing pending; BAND's
  redelivery makes that harmless in our runs, but it is not a targeted restart.
- The host is part of the factory: a background OS update (the Xcode licence) stopped `git` for
  every seat. Nothing in the band can detect or repair that.

## 10. What we did not test

- Hidden checks: only the shipped part of each stage's suite was run; the rest is the judges'.
- A container restart in the middle of a write: the specification allows state to be lost on
  restart, and no seat tried to kill the service during a request.
- Load beyond the specification's stated concurrency (50 requests in flight).
- Browsers other than the headless Chromium the customer seat drives.
- Long runs: each practice and the submitted run covered hours, not days.
- Setup time on a clean machine: the steps in section 3 were done once, over several sessions,
  and never timed end to end.

## 11. Reusing this factory on a different problem

What we have to show that the mandates are generic:

- The six files in `mandates/` name no route, field or error code of the track, and
  `harness check` passes its mandate gate on a clean clone of this repository.
- The same mandates built two different problems. Practice runs 1, 5 and 6 (section 8) pointed
  the band at the unscored `toy` track, a shared counter: four seats in run 1, all six in runs 5
  and 6. Practice runs 2 to 4 and the submitted run pointed it at this track. Between those runs
  only the dispatch message changed problem. The mandate edits made along the way are process
  rules (a verdict file per revision, no commits while a revision is under review, what counts
  as evidence), and each applies to both.
- Everything a seat knows about the problem arrives in the dispatch (section 4): the paths to the
  specification, the run contract, and the visual brief. The run contract used to sit in the
  mandates; it was moved out for this reason.

- **The same factory built the other scored track, 4 of 4.** On 5 Oct 2026, after the submitted
  run, the same six seats with the same six mandate files (unchanged since `046f9e8`, 3 Oct) took
  one dispatch for `tablekeeper`, a restaurant reservation service. The dispatch is the submitted
  one with the track name and paths changed and the visual-brief line removed
  (`docs/evidence/tablekeeper-run/dispatch.md`). Nothing else was changed.

| | `tablekeeper` run, 5 Oct |
|---|---|
| Human input | one dispatch (`room.json`: 3,322 messages, 1 from a human) |
| Duration | 20:16 → 22:55, 2 h 39 min, no pause |
| Stages closed (commit of the fourth accept) | 1 at 21:45 · 2 at 22:15 · 3 at 22:34 · 4 at 22:54 |
| Isolated harness, `--all`, on a fresh clone | each of stage-1/ to stage-4/ claims its own stage |
| Reject rounds | 9, each citing a specification section; stage 3 closed on its first revision |
| Fault seeding (spec-auditor) | 74 seeded on the closing revisions, all caught by the band's evidence |
| Commits | implementer 31, cross-auditor 16, reviewer 13, spec-auditor 12, customer 12, coordinator 1 |
| Spend at list prices | 118.71 USD: 78.70 for the five Claude seats, 40.01 for the Codex seat |

  Its own report, room log, harness summary and logs are in `docs/evidence/tablekeeper-run/`.
  The result repository of that run is not part of this submission; its code was not judged by
  us beyond the shipped checks.

What the second run does not show: the fault counts and shipped-check catches above are from the
coordinator's report and were not recomputed by us, and the run had no visual brief. It is one run
on each scored track, not a measured average.

1. Copy `mandates/` and this file.
2. Rename seats and edit the `Harness:` and `Model:` lines if yours differ.
3. Write a dispatch message (section 4) carrying your own specification.
4. Run one stage; read the reject and gap reports; adjust mandates if a seat misbehaves.
