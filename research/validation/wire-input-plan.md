# Prepared native request serialization

This check follows the [prefix count](token-fit-plan.md). The frozen fixture still carries tool-neutral reply expectations. It has no approved complete native transcript. Prepare concrete task messages and observe SDK/LiteLLM HTTP request serialization before deciding what a complete run needs.

## Exact scope

[wire_input_probe.py](wire_input_probe.py) binds the T-01/T-02 templates and task hashes to control review bundle 07, external manifest SHA-256 `c63bc4edafcbd226dc209c938f94b4506c5034bcabab575070a8be78b1d0a32d`. The task bases are frozen S0 and gold C1, with deterministic preparation UUIDs. Gold C1 is not a durable accepted dependency release; none of these messages is a dispatch grant. Retained request, system/dynamic text and native function JSON must match the previous exact hashes.

Construct metadata-only native TerminalTool/FileEditorTool instances from their native action types and retained descriptions, with no executors and no `.create()` calls. Require their risk-enabled native function conversion to equal the retained initialized conversion byte for byte. Construct native system/user Messages and call `LLM.completion` using the unchanged request profile. Intercept `httpx.Client.send` after HTTP serialization, record the exact body and return a fixed HTTP 403 error. Reject asynchronous/unexpected HTTP and every socket connect/connect_ex call. There is no listening service, broker delivery, network exchange or model response. Require exactly one denied serialized request per case and no returned SDK completion. Native SDK error type is an observation; a denial is never relabeled as successful inference.

For each task, count the complete prepared initial system/user/tools input. Also construct a clearly synthetic finish projection containing the planned terminal command and the literal result `Preparation-only placeholder: payload not executed.` plus LF. This is a sizing projection, not actual tool output, Agent event history, or complete finish qualification. It must not contain a fake test pass. No Agent, ConversationState, executor or task is started. Review/correction requests remain open because their full packets and final transport profile are not yet bound.

Count both native SDK inputs with the reconstructed native definitions and captured wire messages/tools through LiteLLM. Require positive integer counts and agreement. Assess each observed output limit against the unchanged proposed role cap: initial edit 12,000/6,000; finish 6,000/1,000. A cap mismatch is retained evidence and a dispatch hold, not grounds to alter limits or claim the probe malfunctioned. The current SDK profile sets output 6,000 for all calls; the check will establish what reaches serialization. Provider-authoritative usage and scripted settlement tokens remain separate.

Use the already cached preparation image, no pull/build/install, in one new network-none/read-only UID-10001 container with the same resource, tmpfs, capability and no-new-privileges limits as the previous count probe. No host mounts or published ports. The one-use local driver defaults to preview; native apply needs separate command approval. It may briefly start installed Desktop only after checking the literal Linux pipe and absence of Desktop/backend processes, then restore its stopped state after matching-image/unique-label container cleanup and absence of other running containers. All VirtualBox work remains excluded; guard creation approval is still pending separately.

Retain source/input/actual-body hashes and raw failure/cleanup receipts. Keep deployment tool-schema and Chat transcript qualification unset. This is HTTP serialization at a mock transport on Desktop, not the deployed Agent Server/guard/broker path. Next, use the result to prepare bounded role-aware admission and actual transcript inputs before final-target qualification.

## Measured result and affected gate

Four native HTTP requests were captured and each received the fixed 403 denial. The SDK surfaced `APIError` for each, with no returned completion and no retry. Unexpected HTTP, socket-connect and executor counts were all zero. The reconstructed metadata-only definitions converted byte for byte to the previously initialized native definitions. Captured wire tool JSON also matched their 8,051-byte serialization and SHA-256 `f970210f7d91edd8f3df5435ba14f3309ccbd70542394e655892728ff31dc5cc`.

| Prepared case | Input estimate | Input cap | Observed output field | Output cap |
| --- | ---: | ---: | ---: | ---: |
| T-01 initial | 5,209 | 12,000 | 6,000 | 6,000 |
| T-01 finish projection | 5,250 | 6,000 | **6,000** | **1,000** |
| T-02 initial | 5,228 | 12,000 | 6,000 | 6,000 |
| T-02 finish projection | 5,269 | 6,000 | **6,000** | **1,000** |

All four SDK counts agreed with counting the captured messages/tools through LiteLLM. Counts are local estimates, not returned provider usage. Each wire body contains `messages`, `model`, `max_completion_tokens` and `tools`. The wire model is `fixture/model-v1`; the SDK's `openai/` routing prefix is removed. Actual body hashes and byte lengths are in [wire-input-evidence.json](wire-input-evidence.json).

**Hold finish dispatch under this prepared profile.** The measured output request exceeds the proposed finish limit. With the proposed synthetic prices, the declared 6,000-input/6,000-output envelope could require $0.18, exceeding the finish reservation bound of $0.08. These are calculated bounds, not charges. Preserve the numeric caps, historical profile and earlier packets. Prepare a trusted per-phase output limit and verify it at native serialization and broker admission before a run; do not silently change billing, raise a cap, or count rejection as executor success. Correction/review limits need their own complete inputs and observations.

Initial rows bind complete prepared first-call system/user/tools inputs, but do not prove Agent.step would produce identical messages. Finish rows have 750/731 estimated tokens left for additional context; replacing the placeholder with real tool output and any Agent additions remains mandatory. No task code or payload ran, no model supplied a response, and no tool event or actual check result was produced.

The container exited and was absent afterward. No running containers remained; Desktop stopped and the Linux engine became unavailable again. One bounded engine-readiness observation timed out before the next succeeded; the container was started once. The suite passed 115 tests with one existing Windows symlink skip. Previous control bundle 07 and the pending guard-creation plan remain unchanged. Final Agent Server/guard/network, reviewer, transcript and M1 qualification remain open.
