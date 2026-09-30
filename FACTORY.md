# FACTORY.md

How to stand up this factory, why it is built this way, what it cost, and how it catches bad
work. Sections marked `TODO(measure)` are filled in from real runs before submission; nothing
here is estimated.

## 1. Overview

A band of four Claude Code seats in BAND Desktop, sharing one result repository. One seat
plans and routes, one writes code, one verifies independently, one audits the specification
against the shipped checks. The human's dispatch message is the only human input per stage.

```
            dispatch (human)
                  |
            @coordinator
        /         |          \
 @spec-auditor  @implementer  @reviewer
   gap list       commits     runs checks itself
        \         |          /
            @coordinator  -> accept / route back -> final report
```

The mandates in `mandates/` contain no problem-specific detail. Point the same four files at
a different specification and the factory runs unchanged; the specification travels in the
dispatch message and in every handoff.

## 2. Seats

| Seat (as BAND shows it) | Mandate | Harness | Model | Owns | Never does |
|---|---|---|---|---|---|
| coordinator | `mandates/coordinator.md` | Claude Code | claude-sonnet-5-5 | intake, handoffs, routing, final report | writes code or tests |
| implementer | `mandates/implementer.md` | Claude Code | claude-sonnet-5-5 | code and commits | accepts its own work |
| reviewer | `mandates/reviewer.md` | Claude Code | claude-opus-5-5 | independent verification | edits code |
| spec-auditor | `mandates/spec-auditor.md` | Claude Code | claude-opus-5-5 | gap list and its follow-up | edits code, writes tests to pass |

Model ids in the table match the `Model:` first line of each mandate. Change both together.

## 3. Standing it up

TODO(measure): confirm each step on a clean machine and record the time it took.

Prerequisites: Git, a running Docker daemon, Python 3.12+ (only for the event harness),
BAND Desktop with an account, Claude Code access for each seat.

1. Create four seats in BAND Desktop named exactly `coordinator`, `implementer`, `reviewer`
   and `spec-auditor`. Each mandate file is named after its seat.
2. For each seat set the harness to Claude Code and the model from the table in section 2.
   Set each seat's working directory to the absolute path of the result repository, so all
   commits land in the same place.
3. Paste each mandate into its seat's instructions.
4. Configure a Git name and email per seat, so history shows who committed.
5. Grant the permissions an unattended run needs: file edits in the result repository, Git,
   Docker, and browser checks. Keep credentials outside the repository.
6. Confirm a direct `@handle` message reaches each seat and gets a reply.
7. Create a room, add all four seats, and send the dispatch message (section 4).

## 4. The dispatch message

The dispatch is the whole human contribution. It contains: the workspace and result
repository absolute paths, the stage number, the complete specification text for the stage,
where the shipped checks live, and how to carry the previous stage forward. It contains no
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
| Opus for reviewer and auditor, Sonnet for coordinator and implementer | TODO(measure): confirm this split against results and cost |

## 6. Catching and recovering from bad work

| Failure | Caught by | Recovery |
|---|---|---|
| Code special-cased to the checks | reviewer diff read; auditor scenarios not in the checks | reject with reproduction; implementer fixes forward |
| Requirement never exercised by a shipped check | spec-auditor gap list, then follow-up on each revision | gap is blocking until met, with evidence |
| Implementer's claim does not match the tree | reviewer clean build at the reported hash | reject; coordinator trusts evidence over claims |
| Loop of repeated rejects | coordinator's per-item count | split the item or change the approach |
| Silent or absent seat | coordinator resend once, then continue | failure and attempt recorded in the final report |
| Earlier stage broken by extension | reviewer runs all earlier stages' checks | reject; carried-forward behaviour must be intact |
| Build works locally but not clean | reviewer isolated-mode run | reject with the failing command |

TODO(measure): a real example from the submitted run — what was rejected, why, and the
commit that resolved it.

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
| **Total** | | TODO | TODO | TODO |

Source of the numbers: TODO (state where each was read from).

### Outcome

TODO: highest stage claimed on the shipped checks, and the isolated-mode result.

## 8. What we tried that failed

TODO: filled from the practice runs. One line each: what was tried, what happened, what
changed in the mandates as a result.

## 9. Limits and known weaknesses

TODO: honest list. Include anything the factory does not catch.

## 10. Reusing this factory on a different problem

1. Copy `mandates/` and this file.
2. Rename seats and edit the `Harness:` and `Model:` lines if yours differ.
3. Write a dispatch message (section 4) carrying your own specification.
4. Run one stage; read the reject and gap reports; adjust mandates if a seat misbehaves.
