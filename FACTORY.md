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

Prerequisites: macOS or Linux, Git, a running Docker daemon, Python 3.12+ (only for the event
harness), BAND Desktop 0.4.12+ with an account, and the Claude Code CLI signed in to a plan that
covers the models in section 2.

1. **Sign the CLI in and update it.** Seats run the terminal `claude` CLI, not the Claude desktop
   app, and it has its own login. Check with `claude auth status` (must show `loggedIn: true`);
   if not, run `claude auth login`. Run `claude update`: `claude-opus-5-5` needs Claude Code
   2.1.280 or newer, and an older CLI fails every Opus turn with an API 400.
2. **Create the four seats** from the directory the band works in. Each seat's instructions are
   live-linked to its mandate file, so editing a mandate updates the seat and the file in this
   repository is exactly what the seat ran:

   ```sh
   for seat in coordinator:claude-sonnet-5-5 implementer:claude-sonnet-5-5 \
               reviewer:claude-opus-5-5 spec-auditor:claude-opus-5-5; do
     name=${seat%%:*}; model=${seat#*:}
     band agent create --session "df-$name" --name "$name" \
       --description "Dark Factory seat: $name" --cwd "$WORKSPACE" \
       --transport claude-code-cli --runtime-model "$model" \
       --instructions-file "$RESULT_REPO/mandates/$name.md"
   done
   band list    # all four: Connected running=true
   ```

   Defaults kept: permission mode `auto` (unattended, with Claude Code's own safety checks) and
   context mode `local_config` (the only mode that can use a subscription login; `bare` needs an
   API key).
3. **Restart after any CLI change:** `band restart --as <owner>/<seat>`. A pending message is
   redelivered to the restarted seat, so work resumes where it stopped.
4. **Dispatch** from BAND Desktop: Home, Assign work, pick `coordinator`, paste the dispatch
   message (section 4). The coordinator adds the other seats to the room itself.
5. **Record the room**: room menu, Open in Band, Download full session, save as `room.json`.

TODO(measure): time the full setup on a clean machine.

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

Practice run 1 (unscored `toy` track, stage 1, 30 Sep 2026): dispatch to accepted revision in
about 10 minutes with no human input after dispatch; the implementer waited for the auditor's
gap list before building; 12 of 12 audited requirements met; reviewer passed host and isolated
checks. What we changed as a result:

- Setup failed twice before any work: the seats' CLI was signed out, then too old for
  `claude-opus-5-5`. Both are now explicit setup steps (section 3).
- Every commit carried the repository's default Git identity, so history could not show which
  seat wrote the code. The implementer mandate now commits under the seat's own identity.

TODO: add later practice runs.

## 9. Limits and known weaknesses

TODO: honest list. Include anything the factory does not catch.

## 10. Reusing this factory on a different problem

1. Copy `mandates/` and this file.
2. Rename seats and edit the `Harness:` and `Model:` lines if yours differ.
3. Write a dispatch message (section 4) carrying your own specification.
4. Run one stage; read the reject and gap reports; adjust mandates if a seat misbehaves.
