# Prepared prompt/tool token count

This check counts the exact static system prompt, dynamic context and native function definitions retained by the [two-tool initialization](resolved-tool-plan.md). It measures the minimum prepared prefix, without user messages, history or review packets. It does not approve a task, qualify complete role fitting, or change the proposed 12,000-token edit and 6,000-token finish/review input caps.

Run [token_fit_probe.py](token_fit_probe.py) in the already cached image `sha256:f242d7a2b69742fde04385231647c54c57396b251ddfd7a5f34095073970e868`. The probe accepts only the four retained input hashes. It constructs a native SDK system Message from the two recorded text fields, uses native message formatting, and compares the SDK message-only count with the underlying LiteLLM count. It then counts those formatted messages with the retained native function JSON supplied directly to LiteLLM. This last count is not a new ToolDefinition resolution or an SDK tool-object counter call. Native tool calling must remain enabled and prompt mocking disabled. Zero counts, counter errors, a disabled counter or differing message-only counts hold the measurement. A valid measurement may still exceed a role cap.

Model completion entry points are raising tripwires. No ConversationState, tool executor, Agent Server, user message or inference is started. The one-use driver is `.local/validation/token-fit-01/run.py`, default preview only. Its native apply requires command approval. It reuses the successful previous lifecycle controls: literal Linux pipe, isolated empty-auth Docker config with the installed Desktop plugin directory, host-only Windows directory variables, bounded synchronous startup only when Desktop/backend are absent, exact cached image, no pull/build/install, network none, no host mounts/ports, read-only root, UID 10001, all capabilities dropped, no-new-privileges, one CPU, 2 GiB/no additional swap, 128 PIDs and bounded tmpfs. Only the named container with matching image and unique operation label may be reconciled. Restore Desktop to stopped when this driver started it and no unrelated running container remains. No VirtualBox operation is permitted; guard creation approval remains separate.

Source review, separate from a run: the pinned SDK's `LLM.get_token_count` catches counting errors and returns zero. LiteLLM 1.105.1's Python counter selects `cl100k_base` for an unknown OpenAI model name; the result is a local estimate for the synthetic model, not provider billing. Its wheel bundles the 1,681,126-byte cl100k data with SHA-256 `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`, matching tiktoken 0.12.0's expected digest. No tokenizer download or installation is needed. Source was extracted from hash-verified retained wheels, not executed on the host. The text size is below the counter's default 4,000,000-character extrapolation threshold.

Retain exact source/input hashes, raw stdout/stderr, count results and cleanup receipts. Compare final captured request bodies and complete role-specific histories against the unchanged caps before dispatch. Keep deployment schema/wire qualifications unset until that evidence exists.

## Measured prefix result

The offline native check passed with zero inference attempts. SDK and LiteLLM message-only counts both returned 3,258; adding the retained two function definitions through LiteLLM produced 4,985. The selected encoding was `cl100k_base`, without a custom tokenizer or disabled counter. Native tool calling was enabled and tool-prompt mocking disabled. The formatted system message was 15,610 serialized UTF-8 bytes, SHA-256 `286fc3edb2037c4b23c611b87d4a5387c1ee00e4415cdfa5b53ed4b473b46af7`. This serialization is a probe artifact, not a captured Chat request.

| Proposed role | Input cap | Remaining after prepared system/tools |
| --- | ---: | ---: |
| Initial edit | 12,000 | 7,015 |
| Correction edit | 12,000 | 7,015 |
| Finish | 6,000 | 1,015 |
| Review | 6,000 | 1,015 |

The prefix alone fits these caps; complete requests are unmeasured. In particular, finish/review have only 1,015 estimated tokens left for user context, history and other request inputs. Do not dispatch or enlarge a cap based on this result. SDK context capacity 32,768 and configured output 6,000 remain separate from the fixture's per-role input/output bounds and require later admission/wire binding.

The container exited successfully and native inventory found it absent, with no remaining running containers. Desktop was stopped again and the Linux engine became unavailable. Two bounded engine readiness queries timed out before the next query succeeded; they were observations, not repeated container starts. No VirtualBox operation, package install, image pull/build, task or provider call occurred. See [token-fit-evidence.json](token-fit-evidence.json) for retained hashes and cleanup receipts.

Next: prepare and count complete role-specific request inputs, then compare them with captured final-target wire requests. This prefix check does not qualify runtime metering, final-target isolation or M1-12/M1-13.
