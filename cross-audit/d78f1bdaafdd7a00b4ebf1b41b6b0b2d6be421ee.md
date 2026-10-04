# ACCEPT — stage 2 revision d78f1bdaafdd7a00b4ebf1b41b6b0b2d6be421ee

Independent cross-auditor verification. No blocking findings observed. Turns for this revision: **1**.

## Method and scope

Verified clean detached worktree `/tmp/cross-audit-stage2-d78f1bd` at exactly the named revision. The stage-1/stage-2 diff against independently accepted 94e856c contains only `stage-2/static/app.css` (9 insertions, 6 deletions). The earlier complete requirement walk remains applicable to unchanged code; nevertheless all independent HTTP and browser regression suites were freshly rerun here. No other verifier's files or shipped-check source were read, and no stage implementation was edited.

Built the RUN.md Dockerfile as `pocketful-cross-s2-d78f1bd`. Source and destination ran with 2 CPU/2 GiB on an internal-only Docker network, at default PORT=8080 and overridden PORT=8097. A real accepted stage-1 image (999fda2) supplied upgrade exports. HTTP probes ran from a separate container; Playwright/Chromium used host TCP proxy sidecars while the service containers retained internal-only networking. The browser asset test blocked external URLs and observed none.

## Fresh evidence

| Suite | Assertions | Passed | Other |
|---|---:|---:|---|
| Stage-1 regression, five scripts | 777 | 775 | Two previously documented orphan-operator expectations; explicitly tolerated, nonblocking |
| Stage-2 API | 166 | 166 | None |
| Browser flows, races, upgrade, presentation, three widths | 119 | 119 | None |
| Targeted Refresh and odd-card layout | 26 | 26 | None |
| Total | **1088** | **1086** | **No blocking failures** |

Evidence files are `evidence-d78f1bd-*.json` alongside this report and `d78f1bd/evidence-d78f1bd-{stage2-browser,layout}.json`. Screenshots are in `d78f1bd/`. Probe scripts are committed in this folder. The layout probe initially assumed incoming request cards also formed a two-column grid; actual requests correctly use two columns for incoming/outgoing groups with stacked cards within each. That unsupported probe assumption was corrected and the layout suite rerun. No application failure was waived.

Both supplied harness modes passed stage 1 and stage 2 and printed **claimed stage: 2**:

- `/Users/kosesena/Desktop/dark-factory/band-work/checks/cross-auditor-d78f1bd-standard-s2`
- `/Users/kosesena/Desktop/dark-factory/band-work/checks/cross-auditor-d78f1bd-isolated-s2`

Both used the exact worktree as `--repo`; the final run added `--mode isolated`. Stage-3 failure is outside this stage-2 judgment.

## Changed behavior and visual judgment

At 375, 900 and 1280 CSS pixels, Refresh has equal left/right and top/bottom computed padding. Actual screenshots show a balanced pill without the previous selector leak. At 900/1280, activity and authorization lists place the first two cards side by side and the third spans the list width. At 375 they stack. Request cards occupy the full width of their respective incoming/outgoing column. No tested route has horizontal page overflow.

The cream/brown/green interface retains clear monetary hierarchy, visible labels, focus indication, legible navigation and explicit status/privacy/direction words. Available remains the headline amount and held/total remain secondary. Reviewed wallet screenshots at all three widths and targeted activity/request/hold layouts; browser regression also captures split and feedback states. No blocking visual regression observed.

## Requirement disposition

All S001–S083 are **met in exercised cases**, using the atomic quotes in `stage-2-requirements.md` and the complete mapping in the preceding independent 94e856c report. Every mapped suite was rerun; 900px and targeted layout checks broaden the visual coverage. In particular:

| Requirements | Current evidence |
|---|---|
| S001–S032, S075–S082: routes, forms, rendering and own-action refresh | 119 browser checks: authentication/identity, all routes, exact currency/notes, local decimal validation, pay retry/edit behavior, request controls, split preview, hold capture/void, empty/error/loading/success states, seeded holds, labels/focus/contrast |
| S033–S042: competing clients, uncertainty and upgrade | Delayed earlier balance/feed reads ignored; stale funds/request refusal refresh; committed-response loss uses identical retry key/body and transfers once; actual stage-1 export/import preserves signed-in browser, form/retry identity and payable request without reload |
| S043–S074, S083: hold API and concurrency | 166 API checks: conservation/available, funds reserved against every spending path, final/nonfinal/full/partial capture, void/idle expiry, permissions, validation, filtering, import/replays and 50-flight concurrency |
| S003–S011: presentation and responsive behavior | Three-width screenshots/labels/focus/contrast, feedback/asset checks and 26 targeted layout assertions |
| Inherited R001–R101 | Fresh 777-check stage-1 regression, including exact numeric identity/huge numbers, zero-share import, original pending receipts, corrupted state/receipt rejection, request/payment consistency and settlement membership/timestamps |

## Blocking or unverifiable findings

No requirement was observed to be not met. These unchanged proof boundaries remain **unverifiable as universal claims**, not observed defects:

| Requirement | Limitation |
|---|---|
| R002: no negative balance, including transiently | Observed concurrent reads are nonnegative; HTTP cannot expose every invisible internal transient. |
| R042: tokens do not expire | Sessions and imported tokens work; finite tests cannot prove unbounded lifetime. |
| R101: prohibited source reuse | Runtime behavior cannot establish development provenance. |

Conservation and serializability are established for exercised schedules, not all possible schedules. The two orphan-operator expectations retain the explicitly permitted nonblocking treatment.

**ACCEPT — d78f1bdaafdd7a00b4ebf1b41b6b0b2d6be421ee. Turns: 1.**
