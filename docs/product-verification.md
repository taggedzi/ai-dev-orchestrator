# Candidate check and review records

`coordinator/verification.py` adds durable, exact-revision check/review operations
and a candidate evidence gate. It records **scripted development evidence only**.
It executes no candidate commands or model calls, and cannot accept a task,
promote an integration or release a dependent task. Qualified controllers and
actual reviewer quality remain separate work.

## Frozen policy and identities

After [candidate intake](product-intake.md), the developer approves an exact
policy digest and intake version. Policy references immutable definitions for
every approved task check, observable cases, environment profiles, reviewer
profile, a seven-dimension rubric and a fresh review context. A check definition
cannot change the approved command or timeout. Omitting a check, a required
rubric dimension or expected case cannot establish a pass.

The implementation actor and context are now recorded at scripted dispatch and
included in candidate contract v2. Check producers must differ from the
implementer; the reviewer must also differ from the checker and Git intake
producer. Each review session can bind only one approved policy, including on a
correction attempt. Older candidate contracts without implementation identity
remain historical; migration does not invent that identity or qualify their
review independence.

Principals are supplied by trusted local composition. A receipt body cannot
choose its actor. The service submitting a result must match the operation's
assigned producer; developer approval and scheduler dispatch are separate roles.
This is tested local role enforcement, **not deployed remote authentication**.
No new service mutation endpoint, credential or listening server was activated.

## Operations and applicability

The scheduler admits checks against the exact approved candidate and policy,
then commits possible-send before dispatch. Repeating dispatch refuses after
process loss; an authenticated producer can later supply the corresponding
observation. Neither an expired connection nor a missing acknowledgement creates
permission to run a check again.

Each binding includes operation/attempt, authority generation, repository, exact
input and candidate OIDs, source manifest, intake receipt, plan/task/criteria,
policy, profile and packet digests. Check results must name that binding, source
and environment and cover every expected case, with retained observation/log
artifacts. Missing/mismatched evidence is held even when its submitted verdict
says pass. A failing or inconclusive result never qualifies.

Review admission waits for all required check passes. It creates a new immutable
review input joining the candidate packet to those exact check receipt digests,
rubric, profile and fresh session. A review pass requires complete criterion and
rubric coverage, the matching context and check set, and no findings. Findings
carry criterion/location, expected/actual behavior, impact and retained
reproduction. This first gate has no finding-adjudication or exception bypass.

Identical observations deduplicate. A conflicting second receipt is retained,
fences project authority and holds the operation. Pause/revision fences prepared,
in-flight and returned verification. Late observations remain historical, and
resume cannot revive their old generation. Artifact corruption, changed private
refs or obsolete evidence prevents the fresh gate from passing.

`gate()` revalidates candidate objects, artifacts, policy, check and review joins
and current authority. A complete scripted chain can return
`development_ready_for_integration=true`; `live_eligible` and `task_accepted`
remain **false**. An acknowledgement describes its committed observation, not a
new grant to promote. Future promotion must perform its own current-authority,
exact-integration and expected-old-ref checks.

## Persistence, evidence and next work

New stores use schema **5**. Explicit offline migration supports v1 through v4, creates
a verified archive before transactional DDL, preserves holds and refuses drift.
Ordinary startup does not migrate. Follow [the migration procedure](product-intake.md#schema-migration).
Explicit archive restore is specified in [product intake](product-intake.md#archive-restore).
Host-power-loss qualification remains open.

[The candidate verification evidence](implementation/product-verification-evidence.json) retains
**70 passing product tests**, zero skips, and an actual DB/Git/artifact smoke
with separate local scheduler, check and review identities. Sixteen verification
tests include reviewer rejection after green checks, wrong producers/contexts,
missing coverage, duplicate/conflicting receipts, stale authority, changed
artifacts/refs, fresh-session enforcement and a real process exit after dispatch.
A new v2 migration case preserves a held intake and unknown implementation
identity. No model quality, isolated check execution or live acceptance is inferred.

[Integration staging and regression records](product-integration.md) now extend
this gate; [87 product tests pass](implementation/product-integration-evidence.json).
P2 has measured authorized diverged-head mapping, fresh checks and review on a
distinct integrated commit, and one serialized promotion. A rejected candidate
cannot promote. Task 2 starts only from the accepted task-1 integration.
`live_eligible` stays false. Qualified
runner/reviewer authentication and real isolated execution remain required before
live eligibility. Scripted P3 policy and cost records are measured separately in
[model policy](product-model-policy.md); live routes, P4–P6, native gates,
browser usability and full R1–R9 acceptance remain open under
[the complete delivery plan](product-delivery-plan.md).
