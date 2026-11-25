# Pinned GSD planning export

This closes a missing input in the M1-10 validation freeze: the existing normalized plan is explicitly synthetic, not an upstream GSD export. Scope is a read-only GSD query over the frozen synthetic planning files. It does not implement the product coordinator or authorize executor experiments.

## Pins and roles

Use published `@opengsd/gsd-core` 1.21.0, whose npm metadata reports Git head `357508df233ccca0dcf4332b385d6bee9b113da9`. Its fixed archive integrity is `sha512-qccKXCfMny+UMYO7rDZWz83oy6JWd1D3QR/2WUbcjd7N0WZBhr9/+hsXQ5nVaf423W/GSspMjSqT+ZsQNeCLUQ==`; the registry reports 1,282 files and 20,945,147 unpacked bytes. Download only from the exact public npm URLs in `gsd_export.py`; reject redirects and changed identity/integrity. Record the downloaded bytes and hashes. Registry signatures and SLSA provenance are not verified by this checksum check.

The [pinned package](https://github.com/open-gsd/gsd-core/blob/357508df233ccca0dcf4332b385d6bee9b113da9/package.json) requires Node >=24. The workstation's installed Node 26.13.1 and Git 2.56.1 are planning-preparation tools, recorded separately from the proposed executor's Node 22.16.0 and Git 2.51.0. Do not silently change executor pins to satisfy the planner. Source checkouts omit compiled modules; the [bootstrap](https://github.com/open-gsd/gsd-core/blob/357508df233ccca0dcf4332b385d6bee9b113da9/gsd-core/bin/ensure-runtime-build.cjs) can invoke a compiler when missing. Require the published compiled runtime instead; run no npm installer, lifecycle hook, compiler or model workflow.

## Concrete preparation and query scope

The default command is plan-only:

```powershell
python -m research.validation.gsd_export
```

After preparation approval, `prepare` downloads and verifies the public metadata/archive into a new ignored directory, rejecting traversal, aliases, duplicates, links, special files and size overruns. It writes regular files only; it never runs a package entry point or installer. An `export` invocation independently checks the extracted execution tree against the fixed-integrity archive before running anything.

```powershell
python -m research.validation.gsd_export prepare --approval "<approval reference>"
python -m research.validation.gsd_export export --approval "<approval reference>"
```

Export copies only `.planning/` files from the original 220-file bundle after verifying its external manifest digest. It creates a separate synthetic planning Git commit using the existing deterministic object writer, initializes that checkout's index and requires clean Git status. It never stages or commits this project's repository. Source/planning files, HEAD, refs and index are hash-inventoried before and after.

Invoke the published CLI directly with installed Node and an allowlisted environment, isolated home/temp directories, no provider credentials, disabled Node compile caching, and disabled optional Git locks/global configuration. Run only `runtime-identity --raw`, `query project-context`, `query planning inspect`, `query phase-plan-index 1`, and a repeated `query planning inspect`. Use 30-second subprocess deadlines and a 2 MiB output bound; retain stdout, stderr and exit codes. Require schema 1, byte-identical repeated snapshots and unchanged planning/Git/package inventories. A query failure or write footprint remains a hold with evidence; do not relabel it as a successful export.

These are trusted upstream read queries, not a sandbox for arbitrary candidate code. No real project content, model call, VM change or hosted inference is part of this stage. [AGENTS.md](../../AGENTS.md) says, “Ask before installing tools or dependencies”; the isolated CLI preparation/query action will be explicitly approved before execution even though it uses no global install.

## Next acceptance check

Inspect the actual exported shape before implementing its schema-1 importer. Compare both task actions, file lists, acceptance checks, done conditions and the T-01 → T-02 dependency against the frozen raw plans. Unknown evidence must remain unknown. Then exercise missing dependencies, cycles, malformed plans and unsupported schemas, recording refusals to schedule. Keep the original review bundle unchanged; actual exports and any subsequent bundle revision have separate digests.

Separately, the [pinned OpenHands Dockerfile](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-agent-server/openhands/agent_server/docker/Dockerfile) defaults to a different Python/Node toolchain and preinstalled ACP providers/capabilities. A matching minimal executor image still needs a concrete build/dependency plan; pulling the default image would not satisfy the existing fixture freeze. No image was built or dependency installed during source review.

## Measured export and import results

The explicitly approved package preparation downloaded 5,950,757 archive bytes, SHA-256 `e1bfe32b2da10861cc8829bcce62b323ca87248707fb5547fd396b19ff49893a`, and matched the fixed SHA-512 integrity. The 1,282 extracted files total 20,945,147 bytes. Git blob IDs for the package manifest, CLI entry point and bootstrap match the pinned source. No global install, npm lifecycle hook or dependency installation was used. The published compiled tree was used, without a compiler rebuild or registry-signature/SLSA verification.

All five queries succeeded on the original bundle and returned schema 1 twice with identical bytes. Its generated planning format nevertheless lost information: requirement mappings were absent, inline objectives retained a closing tag, and inline comma-separated criteria became one criterion. The phase-goal export intentionally reads prose before metadata, rather than the bold Goal annotation. These are actual parser observations, not inferred completion. The original 220-file bundle remains unchanged.

The fixture generator now follows the pinned roadmap/requirements/plan templates: add requirement traceability, multiline objective delimiters, bullet criteria and explicit phase-goal prose. Task semantics, seed/gold Git objects, executor pins and dependency direction are unchanged. Intermediate revisions and exports are retained. The selected corrected export is `.local/validation/gsd-export-03/inspect.stdout`, SHA-256 `5fc3b148578fc357606e7744e12e692d914eb0b9354f99b60e21264bc8685df3`, with planning commit `10474b5cdbc5bdbee2b7af5c71153c0432fc3c6a`. Its repeated snapshot bytes match; planning/Git/package byte inventories and clean Git status match before and after. These checks do not constitute syscall-level tracing of transient writes. Generated paths make snapshots host/path-specific; byte identity is measured within each frozen input root.

`gsd_import.py` is a fixture-only conformance probe. It checks schema, phase goal, mappings, task/plan identity, file scope, dependency graph, criteria and done conditions. Action and automated verification bodies are absent from the native snapshot, so it retains them verbatim from hash-bound raw PLAN files. GSD's markup is XML-like and permits literal `<name>` placeholders in prose; it is not parsed as general XML. Native `runnable` includes both plans, while `ready_plans` contains only 01-01. Neither field, a checkbox nor native finished status authorizes coordinator acceptance. The probe's synthetic acceptance control permits T-01 initially and T-02 only after T-01 is supplied as accepted; this does not qualify a real acceptance ledger or scheduler.

Four one-PLAN negative variants were queried through the pinned CLI. Missing dependency target, dropped dependency and malformed task markup still yielded native snapshots, which the importer refused. The cycle snapshot was also refused by the importer, and native `phase-plan-index` exited 1 with an explicit cycle diagnostic. The first conservative case run left that producer error inconclusive; a revised classifier binds its diagnostic and unchanged-input proof, with the first result retained. A fifth, consumer-only mutation to schema 2 was rejected; it is not a test of a future GSD release. All five case controls now block eligibility. Unknown progress percentages remain unknown. Nine conformance tests plus five package/execution-boundary tests supplement the existing suite.

See [gsd-export-evidence.json](gsd-export-evidence.json) for raw-artifact hashes, source versions and the precise boundaries of these results. The checked-in conformance sample replaces only the machine-specific generated paths semantically and normalizes JSON serialization; the raw producer artifact is retained separately.

## Attaching the measured planning input

The bundle builder accepts an explicit source root and external snapshot digest:

```powershell
python -m research.validation build .local/validation/gsd-review-bundle-04 --gsd-export .local/validation/gsd-export-03 --gsd-snapshot-sha256 5fc3b148578fc357606e7744e12e692d914eb0b9354f99b60e21264bc8685df3
```

It rechecks query receipts, repeated bytes, unchanged planning/Git inventories and exact equality to the new bundle's raw plans, then includes the native snapshot, original export receipt and normalized probe in the manifest. The resulting profile carries the real `gsd_export_sha256` while leaving approval and runtime/isolation/network evidence unset. The freeze is a preparation artifact, not permission to run executor code. Its external manifest digest is recorded separately in [gsd-freeze-evidence.json](gsd-freeze-evidence.json), which is deliberately outside that bundle's source allowlist to avoid a self-referential digest.
