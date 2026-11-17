# GSD Core research plan

**Question.** Can the coordinator reuse GSD Core planning and durable context while retaining control of execution, verification, and approvals?

1. Pin a release or commit of [Open GSD's GSD Core](https://github.com/open-gsd/gsd-core). Read the upstream [workflow documentation](https://github.com/open-gsd/docs/tree/main/docs/core) and trace discovery, planning, execution, verification, and resumption. Inventory the `.planning/` artifacts, their consumers, and which workflows write them.
2. Look for supported ways to hand an approved plan to an external executor and report the outcome. Record host-agent dependencies, schema stability, automatic commits, approval behavior, and versioning or migration support.

**Exit evidence.** Map sample planning artifacts to the draft requirements. Recommend one of workflow integration, artifact-format reuse, or an independent planning model with reasons and open questions. Identify the authoritative writer for each shared record.

**Later experiment.** Use a fixture plan with two dependent tasks. Test external execution, result recording, and resumption. Check for unexpected Git writes, duplicate state, and dependence on a specific host agent.
