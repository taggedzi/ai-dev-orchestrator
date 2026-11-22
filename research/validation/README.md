# M-CLI1 fixture preparation

This package builds the synthetic inputs and local harness authorized in the November 20 conversation. It uses Python's standard library plus installed Node and Git for verification. It is experiment code; the product coordinator and its architecture remain unselected.

The developer-selected guard topology now has an [exact first-stage provisioning review](guard-preparation-plan.md), a plan-only native script and explicit network inputs. Read-only inspection binds the stopped source disk and identifies missing nftables packages. Creation, boot, installation and network activation remain separate approvals.

The [offline packet-filter preparation](guard-package-plan.md) has verified four archives from signed Ubuntu metadata. Package inspection identifies service behavior that must change and a separate OS-update prerequisite. No package or rule was installed.

The [coherent OS-update proposal](os-update-plan.md) now resolves both roles from the same base: executor 97 upgrades/five additions, guard 97 upgrades/nine additions, without removals or held-back packages. Exact pinned replay and authenticated metadata coverage for all 489 final versions passed. Archive retrieval and native installation remain separate from that resolver result.

The separately approved [archive retrieval](os-update-artifact-evidence.json) is complete: 106 files/about 283 MiB, each hash/size/control identity verified, with no installation or VirtualBox operation. Offline guest bootstrap/hardening and final qualification still require their concrete review and approval.

The [combined offline repository](offline-install-plan.md) now retains 114 unique archives and the original Ubuntu signatures/indexes. A private file-only APT refresh and exact simulations passed for both roles: executor 97 upgrades/16 additions, guard 97 upgrades/nine additions. This is verified installation input, with no installation authority or apply script. OS maintainer-script/maintenance review, actual guard creation and final qualification remain open.

The [maintenance review](maintenance-procedure.md) has since captured both new archive scripts and older installed handlers/helpers from a fully verified unmounted baseline view. Its proposed procedure accounts for direct systemd reexec, conditional metadata lookups, APT hooks, masks and prompt handling; no package installation, service activation or VM change ran.

The [configuration and data-media stage](maintenance-media-plan.md) now has ten native parser measurements, seven rejected unsafe cases and a 142-file byte-verified ISO. The 599,830,528-byte image remains unattached; the frozen mirror and guest-action authority are unchanged.

The [maintenance admission preview](maintenance-runner-plan.md) adds durable intent, one-use dispatch and full-result checks with thirteen synthetic tests and two unarmed role packets. Its CLI prepares artifacts only; no native transport is provided.

The [guest inspection stage](guest-maintenance-plan.md) adds a standalone read-only payload and create-only control-change planner. Sixteen checks passed on the Linux tool host, including real pipe timeout/output bounds, child reaping and APT staging ownership; both role specs remain unarmed.

The [bounded serial stage](maintenance-serial-plan.md) passed eighteen focused checks, including actual Windows pipe/job cleanup and parent-death behavior. Requests remain unarmed.

The [guest control executor stage](guest-control-plan.md) has exclusive writes, fresh-state/plan matching and retained global intent/partial-state holds. Its source pins are superseded for activation by the transfer integration; the historical snapshots remain intact.

The [transfer controller stage](transfer-plan.md) now generates identity-gated bounded lines, monitors original authority and requires the original stop ledger plus independent poweroff evidence. It fixes JSON-dependent plan ordering and adds explicit serial rejection. Four role/purpose grants remain unarmed. Windows regression passed 234 tests with 13 platform skips; 59 selected Linux checks passed. Live-state/stop adapter qualification and the same-boot inspection/approval handoff are next; no actual guest transfer or VM action ran.

The [host-adapter checkpoint](host-adapter-plan.md) adds bounded read-only Windows queries, separate original-owner PID/heartbeat binding and a stop observer that issues no VM command. Stopped-state native inventory passed; running/UART/stop qualification is still open. Regression passed 258 tests with 13 skips, including all 23 new host checks and 20 serial checks. Current role packets and revision 03 transfer grants remain unarmed. The same-boot session proposal needs approval; current inspections still stop.

The [original-stop checkpoint](original-stop-plan.md) now gates the same owner's bounded command with durable one-shot intent, process/source binding and required deployment-profile admission. Regression passed 279 tests with 13 skips; 19 stop checks and two added profile checks passed. Every new native command was an isolated Python surrogate; no VBox poweroff ran. Current stop/host packets remain unarmed. Independent owner startup and actual target shutdown still need qualification.

The [native two-tool input check](resolved-tool-plan.md) also passed in the pinned image: real backend initialization, rendered system prompt and risk-enabled function schemas, zero actions/inference, clean executor/container shutdown. It is preparation data; final wire/token and isolation qualifications remain open.

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
| `maintenance_runner.py` | Unarmed role packets; target/media/control/lease admission; separate one-use marker and SQLite intent before an injected handoff; complete reported package and independent-stop checks. No native transport or apply CLI. |
| `maintenance_guest.py`, `guest_maintenance_probe.py` | Unarmed standalone inspection specs; fixed read-only Linux queries and raw unit/dpkg facts; control-change descriptions with conflict refusal. No control-change executor, complete admission observation or native VM transport. |
| `maintenance_serial.py`, `maintenance_serial_worker.py` | Gated Windows serial I/O worker in an exact kill-on-close Job Object; bounded framing/output/deadlines; durable intent and fencing on uncertainty. No guest command generation, VM admission or stop implementation. |
| `maintenance_control.py`, `guest_maintenance_control.py` | Unarmed control packets; pinned fresh inspection and exact plan matching; exclusive guest control operations with permanent intent/partial-state journal and reported postconditions. Separate activation required; no package installation or VM stop. |
| `maintenance_transfer.py`, `transfer_commands.py`, `guest_transfer_entry.py` | Unarmed role/purpose grants; exact identity/staging/invocation compiler; original lease monitoring; retained uncertainty and original stop-ledger/observer requirements. Native state/stop collectors remain injected and unqualified. |
| `maintenance_host.py`, `windows_readonly.py` | Prepared fixed read-only query/observation adapters, original-owner registration/PID binding and independent stop observation. No native owner activation CLI; actual running/UART/stop and receipt issuers remain unqualified. |
| `maintenance_stop.py` | Unarmed role stop plans; original-owner-only fixed poweroff command, private bounded process wrapper, durable no-replay intent and command receipt. Independent launch and actual poweroff remain unqualified. |

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

`planning/expected-plan.json` remains a coordinator-authored expectation. The separately approved [GSD export stage](gsd-export-plan.md) now supplies an actual pinned schema-1 export and fixture import controls. It uses a checksum-verified local CLI copy with installed planning-host Node >=24; the executor's Node 22 pin remains separate. Raw actions and check bodies stay hash-bound because the native snapshot omits them. The export and five negative controls do not qualify a product scheduler or acceptance ledger.

For a new bundle, attach the measured export with `build DESTINATION --gsd-export EXPORT_ROOT --gsd-snapshot-sha256 DIGEST`. The builder checks the external snapshot digest, raw planning equality, query receipts and read-only footprint before indexing the native snapshot, receipt and import probe. A generated `profile` carries that actual GSD digest while retaining `not-approved` and unset runtime evidence. The [external freeze receipt](gsd-freeze-evidence.json) records the selected packet; the original 220-file bundle is preserved.

See [deployment preparation](deployment-plan.md) for the target review and the [M1-10 prerequisite order](../two-task-validation-fixture.md#execution-order-and-prerequisite-gates) for later experiments.

The [minimal runtime preparation](runtime-image-plan.md) adds a reviewed 186-archive catalog and plan-only collector. The [subsequent offline image stage](image-build-plan.md) now pins base images/build backends, prepares an exact context, builds a local image and measures non-root/read-only startup under network none. Its CLI preparation also defaults to plan-only. Desktop was stopped again after cleanup. The image, broad server tool catalog and final-target gaps are recorded separately from M1-12 qualification. Previous review bundles remain unchanged.

The [two-tool control preparation](control-policy-plan.md) adds a distinct strict admission gate and read-only SDK schema probe. Exact requests, methods, conversation IDs, credentials and operation hashes are checked before forwarding; uncertainty persists across restarts without automatic mutation replay. A separately granted stop stays available after fencing. Local tests include independent fault-proxy receipts. The native model probe created no Conversation or tool executor. The developer selected the guard topology for preparation; final guard placement, packet controls, resolved tools and wire observations remain unqualified.

Offline OS construction is documented in the [installation plan and result](os-install-plan.md). Its separate `os_install` command targets only the newly created VM, requires an approval reference, and keeps every NIC disabled. Its default invocation prints a plan without native calls. The installed image must not be reformatted by rerunning this stage. OS construction does not qualify executor recovery or containment.

The [first-boot plan](first-boot-plan.md) adds a bounded, non-root serial probe of the installed OS and ACPI shutdown. It records stalled boots and profile changes separately. Its default invocation is also plan-only. A failed attempt requires a stopped-image reconciliation; subsequent attempts never silently accept a changed disk. This is preparation code, not a qualified runtime supervisor.

The [stopped-image inspection](offline-inspection.md) resolves the installer's intentional cloud-init disable marker and confirms that Linux handled the earlier ACPI event. `offline_disk.py` exports only a supported VDI 1.1 base image's GPT partition to a new sparse file, verifies copied ranges, and checks the original disk hash before and after. It opens the source read-only. Use it only after native poweroff is confirmed; inspection of an unreplayed filesystem does not qualify a clean shutdown. The retained copy may contain disposable guest credentials and stays in ignored local evidence storage.

## Verification

All [engine archives and package-text observations](engine-input-plan.md#measured-retrieval-and-text-review-result) are retained separately from installation. The explicit engine downloader mode binds the native resolver and Main/Universe sources; default OS mode remains Main only. Stock service/socket behavior and unsettled source/backport findings carry forward to offline install/hardening review.

The [engine resolver](engine-input-plan.md#measured-resolution-result) now binds 11 additions with an unchanged hypothetical 485-row OS baseline and identical exact-version replay. The catalog is not an installed inventory or security approval. Archive retrieval, script/backport review and installation/runtime qualification remain separate.

The [engine metadata collector](engine-input-plan.md) defaults to preview. It retrieves only indexes pinned by the existing signed OS cohort, with compressed/expanded hash checks and retained failed attempts. Docker's archive candidate is now identified; the engine transaction, security review, package retrieval and installation remain open.

The [phase-boundary proposal](../../docs/decisions/0002-fixture-phase-output-boundary.md) awaits developer selection. Its review helper compares a candidate output ceiling with independently captured native bodies; all four match. It returns preparation bytes only and is not wired into the broker. Existing strict rejection and dispatch holds remain active.

The [trusted phase contract](phase-policy-plan.md) now requires frozen task/attempt/role and input/response count declarations with a counting-evidence digest for every broker transcript row. Exact requests must carry an output limit within that role's cap, and the permit must match the role and full money envelope. The broker refuses old count-free transcripts and policy/transcript changes across restart. Qualified count receipts and the actual Agent phase handoff remain deployment prerequisites. Direct SDK preparation now verifies a 1,000-token finish override while preserving the 6,000-token edit limit.

The [native serialization check](wire-input-plan.md) captures prepared requests only at a rejecting mock transport, without sockets, executors or model responses. It found finish projections requesting 6,000 output tokens against the proposed 1,000 cap. Finish dispatch remains held pending trusted per-phase enforcement and final request qualification.

The [prepared token-count check](token-fit-plan.md) measures the retained system/tools prefix without inference. Its 4,985-token local estimate leaves only 1,015 under the finish/review input cap before other context. Complete request fitting and final wire binding remain required.

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
ruff check research/validation tests
```

Tests use temporary synthetic files and loopback fake services. They never start OpenHands, use a provider, provision a VM, or alter an existing VM. The subprocess crash test intentionally exits a small local journal writer after its fsynced synthetic effect. A skipped Windows symlink test is an outstanding platform observation, not a successful denial test.
