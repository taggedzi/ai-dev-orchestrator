# Trusted phase limits in the fixture broker

The subsequent [broker ceiling checkpoint](broker-ceiling-plan.md) implements
the separately approved optional mode. Strict enforcement described below stays
the default; historical native captures/count estimates are unchanged. Complete
count and final-target traffic qualification remain open.

This is research harness preparation under the existing [fixture caps](../two-task-validation-fixture.md#simulated-spending-profile), following the [native output mismatch](wire-input-plan.md). It does not adopt a product architecture or authorize a task. Historical request profiles, packets and native results remain unchanged.

## Prepared enforcement

[phase_policy.py](phase_policy.py) fixes edit at 12,000/6,000 input/output, correction at 12,000/2,000, finish at 6,000/1,000, and review at 6,000/3,000. At synthetic prices of 10/20 integer micro-USD per token, these retain the full reservation bounds of 240,000/160,000/80,000/120,000 micro-USD. Lower requested output does not shrink the fixture's reservation envelope.

Every trusted transcript row must now include `admission`: `task`, `attempt`, `role`, positive integer `input_tokens`, positive integer `response_tokens`, and `counter_evidence_sha256`. These are declarations from frozen trusted preparation inputs, never client-supplied role/usage fields. The raw request hash binds the input count; the transcript binds the exact scripted response and its count. Zero, over-cap and malformed declarations prevent listener construction. A referenced digest is an integrity link, not proof that counting ran: the external review packet must contain and verify the native input/response counting evidence before deployment. Tests use explicitly synthetic declarations and do not qualify those measurements. The broker does not install/import a tokenizer or accept unmeasured dynamic requests.

For an exact frozen request, validate the explicit `max_completion_tokens` against the trusted phase before consuming a permit. Reject unbounded/alternate output fields, role/route overrides and unapproved Chat fields. Verify the frozen response count fits the requested output. The broker still never forwards to a provider. Input and scripted response counts are separate from fictional settlement tokens and amounts.

The SQLite transaction compares the permit's task, attempt, role and full bound with the admitted turn, then records phase admission and possible-send together. A mismatch leaves the permit reserved; a journal failure rolls back both records and the state change. Copy transcript data before validation so callers cannot mutate served rows. Persist the transcript, token caps, prices and money-limit digest; a different policy/transcript after restart holds. Old submissions without a broker binding cannot be silently adopted. The ledger-only `Store.consume` path remains available for isolated journal tests; the HTTP broker always requires phase admission.

## Native per-call serialization check

Pinned SDK 1.62.0 at `504a88cab0fb48ee5226238ad7b8f1d865fa84a8` accepts explicit per-call `max_completion_tokens`: `select_chat_options` fills this field only when absent. Source review also shows `Agent._step` calls `llm.generate` without a phase-specific output option; `LLMCallContext` carries conversation/cache identity, not phase limits. A direct SDK override is therefore a compatibility check, not an implemented Agent handoff.

The new one-use `.local/validation/wire-input-02/run.py` will reuse the four metadata-only initial/finish-projection requests with `apply_phase_limits=true`. Pass 6,000 for initial calls and 1,000 for finish projections explicitly, and require those exact values in native HTTP serialization. Keep all previous input bindings and the original LLM profile unchanged. The probe reconstructs tool definitions without executors; mock HTTP returns four 403 denials, all socket connections are raising tripwires, and no Agent, task, model response or broker delivery occurs. Preserve the first unbounded capture as separate evidence.

Default driver mode previews only. Native apply requires command approval and uses the same cached image, offline/read-only/non-root/resource limits, literal engine checks, one named uniquely labeled container and Desktop restoration as the earlier probe. No pull, build, package installation, provider upload or VirtualBox operation is permitted. Guard creation approval remains separate.

Next, verify both local broker denials/positive controls and native per-call serialization. The actual Agent Server path still needs a trusted phase handoff, complete final-target request capture and qualified input/response measurement receipts. Keep finish dispatch and deployment qualification held until those agree; do not treat a direct SDK call or local fake service as an integrated fix.

## Measured preparation result

The native explicit-option check passed: all four HTTP requests were captured once and received the fixed mock 403 denial, with SDK `APIError` and no returned completion. Initial outputs serialize as 6,000; both finish projections serialize as 1,000. Input estimates are unchanged at 5,209/5,250 for T-01 and 5,228/5,269 for T-02. SDK and captured-message/tool counts agree. Unexpected HTTP, socket connects and executor instances remain zero. The probe container was removed, no running containers remained, Desktop stopped and the Linux engine became unavailable. See [phase-policy-evidence.json](phase-policy-evidence.json) for exact source/input/body hashes and cleanup.

Local conformance observes an oversized finish returning 409 with its permit still reserved, an allowed finish settling once with replay denied, task/attempt/role/bound mismatches retaining their permits, malformed/over-cap declarations rejected, transcript changes held across a new Store connection, caller mutation detached, and admission/possible-send rollback together after an injected journal failure. These are loopback and SQLite preparation observations using declared synthetic token counts and a fake response, separate from the native denied serialization. They do not prove a deployed broker meter or independent response counting.

The unmodified Agent path still requests 6,000 by default. This stage supplies a failing-closed broker contract and verifies direct per-call compatibility; it does not install a phase adapter, amend a frozen profile, validate real finish tool output, qualify correction/review packets, or clear the finish dispatch hold. Select and bind the trusted Agent phase handoff before an integrated request is eligible.

The later [phase-boundary proposal](../../docs/decisions/0002-fixture-phase-output-boundary.md) compares broker ceilings with one-step runs/LLM switching. A preparation-only helper reproduces all four independently captured capped request bodies exactly. Developer selection is pending; the current strict broker remains unchanged. This is a candidate boundary contract, not an activated Agent integration.
