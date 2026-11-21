# M-CLI1 fixture preparation

This package builds the synthetic inputs and local harness authorized in the November 20 conversation. It uses Python's standard library plus installed Node and Git for verification. It is experiment code; the product coordinator and its architecture remain unselected.

## Build and check

From the repository root, choose a new output directory and run:

```powershell
python -m research.validation build .local/validation/review-bundle
python -m research.validation check .local/validation/review-bundle
```

Build refuses to overwrite an existing directory. The output is ignored by Git. `check` executes only the bundle's trusted synthetic gold programs on the workstation; it provides no containment for arbitrary candidate code. A Node or Git version different from the [experiment pins](../two-task-validation-fixture.md#fixture-manifest-and-retention) produces preparation evidence only.

The build prints an external SHA-256 for `manifest.json`. Preserve it outside the bundle. `verify BUNDLE --manifest-sha256 DIGEST` compares that freeze digest and checks every indexed file, mode and byte hash. Without the external digest, verification detects inconsistency with the included manifest but does not authenticate that manifest. Exact deployment approval must bind the external digest.

## Contents and ownership

| Component | What is prepared |
| --- | --- |
| `fixture.py`, `bundle.py` | Exact three-file seed; C1/C2 gold; B1 rejection; stateful integration regression and correction; deterministic loose Git objects, refs and patches; raw planning inputs and explicit normalized expectations; task prompts; proposed policy; eight reviewer cases. |
| `checks.py` | Scope comparison, Node unit checks, trusted isolated-input graders, repeated-tab regression, mixed/Unicode whitespace, CLI subprocess checks and validator substitution in a separate copy. These are protected check definitions for later isolated runners. |
| `store.py` | SQLite WAL with `synchronous=FULL`; intent-before-I/O records; no automatic mutation replay; persisted authority fence; hash-chained audit records; integer simulated reservations, protected review allocation, settlement deduplication and conflict holds. |
| `http_tools.py` | Loopback-only scripted Chat endpoint and HTTP fault proxy. The broker has no outbound forwarding implementation. The proxy forwards only experiment executor routes to one configured literal loopback endpoint. |
| `driver.py` | Mutation client, bounded paginated history collection, deployment-profile gate, prepared VM stop command and report from durable observations. Native status never becomes task acceptance. |
| `observe.py` | Exact marker parsing, bounded barrier wait, atomic release-file publication and source collection that requires an independent stop-receipt reference. Host placement and the truth of that receipt need separate qualification. |
| `supervisor.py` | Durable VM lease, original wall and monotonic deadlines across process restart, stop on expiry/fencing/clock rollback, and a prepared target-specific poweroff command. Command return is distinct from independently confirmed stop/reap. |

The synthetic Git directory is inside the generated bundle. Building does not commit, stage, switch, or update refs in this project's repository. Source snapshots handed to an executor contain no Git metadata. Existing project changes are preserved.

## Local transport experiments

The broker accepts only `POST /v1/chat/completions` with `Bearer fixture-dummy`, model `fixture/model-v1`, the next frozen raw request hash, and a one-use reservation. Extra routing/fallback fields, changed request bytes, duplicate calls and stale/fenced permits are denied. SQLite stores make reservations and transcript position survive a service restart.

`broker DATABASE TRANSCRIPT --port PORT` serves a JSON list with these fields per turn:

```json
{
  "request_sha256": "<SHA-256 of exact raw Chat request bytes>",
  "generation_id": "gen-<run>-01",
  "settled": 120000,
  "mode": "json",
  "response": {"id": "gen-<run>-01", "model": "fixture/model-v1", "choices": []}
}
```

This example describes the envelope, not a runnable OpenHands transcript. Freeze actual messages, tools, response/chunk objects and token ceilings after the deployed schemas are qualified. `mode` can be `json`, `sse`, or `interrupt`. SSE emits the caller's frozen chunk followed by `[DONE]`; it does not establish SDK interoperability. Interruption leaves the reservation unresolved. All charges are simulated micro-USD.

The trusted operator issues a reservation with `reserve DATABASE BODY --permit ID --task T-01 --attempt A1 --role edit --bound 240000`. BODY contains the exact raw request. Ordinary reservation policy implements B0/B1 limits. V6, V9 residual authority and the alternate V10 race budget still need explicit scenario-specific grants and tests; the default path denies them.

`proxy DATABASE FAULTS --upstream http://127.0.0.1:PORT --port PORT` loads an operation-ID-to-fault map. `before-forward` records non-delivery and closes the client connection. `after-response` records the upstream response, then suppresses its acknowledgement. Each mutating client call supplies `X-Fixture-Operation`. The driver and proxy must use **separate databases**, so client intent and independent proxy receipt are distinct observations. A repeated mutation or an unresolved earlier mutation is held. The harness does not automatically retry even a proved unsent mutation.

Requests and responses are limited to 1 MiB; socket operations have a two-second timeout; transcripts have at most 32 turns; history has at most 128 pages. These local preparation limits are distinct from the proposed target's 30-second model deadline. Check subprocess capture is bounded after completion and by a 30-second timeout; target OS output/resource controls remain required. The local services are serial and intended only for bounded synthetic traffic.

## Review packet preparation

`blind BUNDLE DESTINATION --seed INTEGER` creates shuffled opaque reviewer directories under `DESTINATION/packets`, with the exact subject OID and rubric. Freeze the seed before review. Give a reviewer only those directories and the separately approved context/check evidence. Keep `trusted-index.json`, the original corpus and adjudication labels outside their environment. The generated candidate commit metadata does not include the original packet label.

The eight prewritten labels are proposed fixture oracles. Local graders reproducing them do not qualify an independent reviewer. Human adjudication and the blinded pilot remain outstanding.

## Deployment review

`profile BUNDLE` prints an unapproved deployment template bound to the manifest digest. Missing values stay null. The template requires actual GSD export, image, toolchain, network, tool schema and Chat transcript digests; a named VM UUID; isolation, stop/reap and route/metering evidence; explicit run approval; and an unexpired lease. The `supervise BUNDLE PROFILE DATABASE` command refuses that unapproved template.

The lease watcher is prepared code, not a qualified host service. It must run outside the executor and independently of the coordinator. A crash between stop intent and command receipt leaves a durable uncertainty hold and requires external supervisor reconciliation; its stop/restart behavior must be qualified before a run relies on the ten-second stop guarantee. Native WebSocket recording, syscall/process observation, canary scanning, network counters, immutable host evidence storage and hypervisor reap confirmation remain deployment work.

Raw GSD plans are provided, but `planning/expected-plan.json` is explicitly a coordinator-authored expectation. It is **not** a `gsd-tools query planning inspect` export. Generate the actual schema-1 export with pinned GSD in the separate planning checkout, freeze its bytes, and test import/normalization before depending on that integration. No dependency was installed to simulate an upstream export.

See [deployment preparation](deployment-plan.md) for the target review and the [M1-10 prerequisite order](../two-task-validation-fixture.md#execution-order-and-prerequisite-gates) for later experiments.

Offline OS construction is documented in the [installation plan and result](os-install-plan.md). Its separate `os_install` command targets only the newly created VM, requires an approval reference, and keeps every NIC disabled. Its default invocation prints a plan without native calls. The installed image must not be reformatted by rerunning this stage. OS construction does not qualify executor recovery or containment.

## Verification

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
ruff check research/validation tests
```

Tests use temporary synthetic files and loopback fake services. They never start OpenHands, use a provider, provision a VM, or alter an existing VM. The subprocess crash test intentionally exits a small local journal writer after its fsynced synthetic effect. A skipped Windows symlink test is an outstanding platform observation, not a successful denial test.
