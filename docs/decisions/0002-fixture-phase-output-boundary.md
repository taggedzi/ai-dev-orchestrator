# Proposed fixture phase output boundary

Status: **Proposed — developer decision pending.** Preparation only. The current strict broker still rejects oversized finish requests; this proposal does not activate normalization, amend a frozen profile, or authorize native tasks. The scope is the M-CLI1 local scripted fixture, not adoption of a product routing stack.

## Decision requested

Prepare a trusted broker output ceiling for each frozen phase. The unmodified Agent can continue its two-call run using its existing 6,000-token SDK maximum. The broker selects the phase from its trusted transcript and one-use permit, verifies the exact incoming body, and derives an effective request whose `max_completion_tokens` is the smaller of the incoming limit and the phase cap. For finish this changes 6,000 to 1,000. Keep all proposed token and money caps unchanged.

The explicit decision changes how the broker interprets the executor's requested maximum: it becomes an upper bound that trusted policy may reduce. This differs from the current strict-rejection contract and therefore needs review under [AGENTS.md](../../AGENTS.md). Approval selects a preparation approach only; deployment, network activation and fixture runs remain separately reviewed.

| Option | Consequence | Recommendation |
| --- | --- | --- |
| Trusted broker phase ceiling | Preserve the existing Agent run and SDK profile. Bind incoming and effective bodies to the same trusted phase/permit; enforce the effective request before selecting the local scripted response. | Recommended for this fixture. Keeps phase authority outside the executor without a custom SDK hook or normal same-conversation rerun. |
| One-step Agent runs with LLM switch | Create with one iteration; observe the completed step/limit barrier; use a narrowly granted `/switch_llm` and issue a fresh run for finish. | More control operations, a new iteration-limit event in the baseline, and qualification of normal same-conversation continuation. Native crash recovery would still remain separate. |
| Custom Agent/LLM adapter | Inject an explicit phase option inside the executor before generation. | Requires additional image/bootstrap code, exact configuration and measurement; broker enforcement is still required. |

## Concrete proposed contract

1. Freeze the raw incoming request SHA-256, effective request SHA-256, trusted task/attempt/role, native input and scripted-response count receipts, and full role reservation. The executor cannot choose the phase, mode, target or reservation.
2. Reject a changed raw hash, unknown field/route/role, absent/noninteger/nonpositive limit, conflicting output field or a request above the frozen SDK maximum of 6,000. Derive only `max_completion_tokens = min(requested, phase_cap)`. Preserve messages, tool definitions, ordering and all content strings. If already within the cap, preserve the original bytes. If changed, serialize compact UTF-8 with native insertion order; do not sort keys. Require the exact frozen effective hash.
3. Apply the existing strict phase checks to the effective request, including measured input/response counts and response count within the effective output bound. Compare the permit's task, attempt, role and unchanged full reservation. Atomically journal raw/effective hashes, requested/effective limits, evidence references and possible-send before selecting a response. Changed policy or either body hash after restart holds. Alias bodies, retries and alternate routes do not gain another permit.
4. Return only the frozen local scripted response under its qualified effective count. Do not truncate a returned JSON/SSE response or tool arguments. This fixture broker has no provider-forwarding path. Treat fictional billing usage separately from the native counter measurements.

The preparation-only [review helper](../../research/validation/phase_handoff_review.py) reproduces a separately frozen target body and returns bytes only. It has no broker import/call site, permit consumption, transport or model action. It does not replace the strict admission checks or attest a count receipt.

## Evidence available for review

Pinned OpenHands SDK/Agent Server 1.62.0 commit `504a88cab0fb48ee5226238ad7b8f1d865fa84a8`, LiteLLM 1.105.1. The [first native capture](../../research/validation/wire-input-evidence.json) has the default 6,000 output field; the [explicit-option capture](../../research/validation/phase-policy-evidence.json) has 1,000 for finish. Both used the same retained synthetic messages/tools and a rejecting mock HTTP transport; neither ran Agent.step, a tool or a model.

Preparation comparison of all four retained bodies found that changing the output field and retaining native compact serialization reproduces the independently captured bounded body byte for byte. Initial requests are already identical. For T-01 finish, raw SHA-256 `32c7b70c56cf04fd27bd17e59211254454a8ed227a9dfeb7ae7731ff15105019` maps to `713c3e2074e82433d3bda87e713025963810494a26cb3a2dffeb94ab9e9e5094`; T-02 finish `0f6d1f4a29e441721459959e454d911c8b41992b7ea3c8d584ac108e13653f1a` maps to `8f9efb77bbd071172219b266d0a7e3d8df2de9d85309e0143b161ed96c338c64`. These are prepared projections, not actual Agent histories or a deployed Chat transcript. The [review evidence](../../research/validation/phase-handoff-review-evidence.json) retains comparisons and source/hash boundaries.

Source review found a native [LLM switch route](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-agent-server/openhands/agent_server/conversation_router.py#L624-L667). The [sync run loop](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py#L2159-L2332) resets its local iteration count on each run and emits `MaxIterationsReached`/ERROR when unfinished at its limit. The current narrow gate grants neither LLM switching nor a phase barrier; acknowledgements alone cannot establish a safe switch point. Agent Server may select the async run path, which would need its own qualification for the one-step alternative.

## Remaining gates after a decision

If the broker option is selected, prepare an explicit mode bound into the policy/transcript digest; strict rejection remains the default for old transcripts. Test both raw/effective bindings, no limit increases, phase/permit mismatches, restart and journal-failure behavior. Verify complete input/response counts and actual Agent Server traffic on the final frozen target before dispatch. This review does not qualify finish/correction/review inputs, inference semantics, route metering, containment or recovery. The separate guard-creation approval remains pending.
