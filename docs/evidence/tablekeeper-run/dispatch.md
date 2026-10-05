@coordinator Build all four stages of this job end to end with the band, without asking me anything. Work the stages in order, pipelined as your instructions describe: the next stage starts once the reviewer and the customer have accepted the current one, and every stage must still close with all four verifiers' accepts.

Kickoff package (specs and shipped checks): /Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs
Track: tablekeeper
Specifications: /Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs/tablekeeper/spec/stage-1.md through stage-4.md (read each in full; paste the full text of the current stage into every handoff; every earlier stage's requirements continue to apply).
Shipped checks (partial, read-only; never build to them; run them only through the check command): /Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs/tablekeeper/test/stage_1/ through stage_4/
Result repository (absolute path, commit here, every file the band produces goes inside it): /Users/kosesena/Desktop/dark-factory/band-work/tablekeeper-run
Stage folders: /Users/kosesena/Desktop/dark-factory/band-work/tablekeeper-run/stage-1/ through stage-4/. Each is a complete service with its own Dockerfile and RUN.md; stage N+1 starts as a copy of the accepted stage N, carried forward and extended. Stage folders contain no .git.

Run contract (from spec sections 2-3; it applies to every stage):
- Deliver a Dockerfile and a RUN.md per stage folder. The harness builds the image, runs it with -e PORT=<port> and a port mapping, and tests only HTTP behaviour. Single container, no compose.
- Listen on 0.0.0.0:$PORT (default 8080). GET /health returns 200 {"status":"ok"} within 60 s of container start.
- POST /_test/reset replaces all state with the fixture in the body and returns 204; it stays enabled and unauthenticated in the delivered image.
- No outbound network at run time (only during docker build). Limits: 2 vCPU, 2 GiB, up to 50 requests in flight, 5 s per request (10 s for reset).

Check command (run from the kickoff package directory; use a new --out name every time; replace N with the stage):
cd /Users/kosesena/Desktop/dark-factory/dark-factory-wearedevs && . .venv/bin/activate && python -m harness run --track tablekeeper --repo /Users/kosesena/Desktop/dark-factory/band-work/tablekeeper-run --stage N --out /Users/kosesena/Desktop/dark-factory/band-work/checks/tk-<new-unique-name>
The final check of each stage must also pass with --mode isolated added.

Tools: Docker is at /usr/local/bin/docker. A headless browser (Playwright with Chromium) is installed in the kickoff package's .venv: activate it as in the check command and drive it from Python.

Done means, for each stage: the isolated check prints "claimed stage: N"; the spec-auditor has no open gaps that cite a specification sentence and has reported its fault-seeding results; the reviewer has accepted the committed revision; the customer has accepted it (from stage 2: screens at desktop and phone widths, screenshots committed in the result repository); the cross-auditor has accepted it. A stage is closed only with all four accepts on the same revision. Then report back here once, covering all four stages, with the measurement table your instructions ask for.
