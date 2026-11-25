# Local planning workspace

The development preview provides project requirements/context, stored discovery
turns, plan import and exact approval, task states, pause/revise/recovery, the
scripted promotion commands, and the schema-7 cost report. It uses the same application commands as
[the CLI](product-cli.md). It does not call a provider or execute a candidate
command. `capabilities.task_acceptance` and `live_eligible` stay false. Browser
proof of the dashboard is still M6: Computer Use could not confidently determine
the browser URL.

## Run locally

Use the approved `.local/product-web-venv/Scripts/python.exe` environment
(Python 3.15.2 / SQLite 3.53.4). Do not use the older bare `python` for writes.
Initialize a new store with the CLI if you do not already have a primary store:

```powershell
.local/product-web-venv/Scripts/python.exe -m coordinator --db .local/orchestrator/state.sqlite init
.local/product-web-venv/Scripts/python.exe -m coordinator.web --init-token
```

Then start the local service:

```powershell
.local/product-web-venv/Scripts/python.exe -m coordinator.web
```

Open `http://127.0.0.1:8765` and enter the token from
`.local/orchestrator/web-token`. Keep that file private. Token contents are not
printed by initialization or placed in a URL. `--db`, `--token-file` and `--port`
choose local paths/port; initialization refuses to overwrite an existing token.
The database must already exist. Stop the service when finished; do not assume
Windows terminal Ctrl-C was delivered without observing process termination.

The server binds only 127.0.0.1 and requires its exact Host/Origin. `localhost`,
remote hosts, proxies and multiple workers are not qualified deployments.
HTTP loopback cookies are HttpOnly and SameSite Strict; the cookie deliberately
does not use Secure because this preview has no TLS. Sessions expire after one
hour and are lost on service restart. Same-origin mutations require CSRF tokens.
Local authentication trusts the host account and filesystem permissions; it is
not a boundary against another process with the same user's access.

## Project and plan workflow

Create a project with a repository reference, goal and requirements, one per
line such as `R1: Reject blank input`. This captures intent; it does not fetch or
execute a repository. Import a plan JSON file using the shape in
`examples/p1-plan.json`; inspect all instructions, paths, checks, dependencies,
attempt limits and its digest before exact approval. The example's baseline and
repository are fictional, for development exercises only.

Pause fences outstanding authority. Revision changes pause the project and
invalidate the applicability of earlier plan approvals. Recovery records a lost
sender and holds uncertain delivery; it does not retry or declare a task done.
Refresh state before resolving a stale version. A scripted candidate remains
awaiting verification, so dependent tasks cannot start.

`POST /api/projects/{id}/discovery` records one stored turn. The body is
`command_id`, `expected_version`, `question`, `answer`, and optional
`requirements`. It calls `discovery-record` and uses the same session, CSRF,
Host, and Origin checks as the other developer commands. A service principal
cannot call it. The project panel lists
`project.spec.context.discovery.turns` from `GET /api/projects/{id}`. This is
stored discovery. It does not call a model or approve a plan, and R8 remains
open. Browser proof of that panel remains M6.

`POST /api/projects/{id}/plan-import-gsd` calls `plan-import-gsd`. The strict
body is `command_id`, `milestone_key`, `snapshot`, `digest`, `plans`,
`expected_project_version`, `baseline_revision`, `max_attempts`, and
`check_timeout_seconds`. `snapshot` and `plans` are local paths. The route
uses the same session, CSRF, Host, and Origin checks as the other developer
commands. A service principal cannot call it. The result is the unapproved
`submit_plan` result. The existing plan panel renders that plan from
`GET /api/projects/{id}`. GSD stays a read-only import. The coordinator owns
approval, and R1 remains open. Browser proof of that panel remains M6.

`GET /api/projects/{id}` is the status command. Its `cost` object has
`known_units`, `estimated_units`, `pending_units`, and `unknown_units`.
`pending_decisions` lists exact plan approvals, a stale requirements revision,
a missing scripted model policy, and a promotion that is still `possible_send`
or `held`. `scripted_task_accepted` is true only when one stored promotion
receipt recorded `task_accepted`. The project panel renders those fields from
this response, including `capabilities.task_acceptance` and `live_eligible`.

`GET /api/projects/{id}/milestones/{key}/cost` is the read-only milestone
report. Model policy, assignment, permit, response-loss, and usage use
`POST /api/projects/{id}/model-policy`,
`POST /api/attempts/{id}/model-assignment`,
`POST /api/model-assignments/{id}/permit`,
`POST /api/model-permits/{id}/lose-response`, and
`POST /api/model-permits/{id}/usage`.

Scripted promotion uses the same bodies as the CLI. Each of these requires
`repository` and `artifacts`:

- `POST /api/attempts/{id}/diverged-head`
- `POST /api/integration-proposals/{id}/regressions`
- `POST /api/integration-proposals/{id}/evidence`
- `POST /api/integration-proposals/{id}/promotion`
- `POST /api/integration-proposals/{id}/promote`
- `POST /api/integration-proposals/{id}/promotion-reconcile`

`promote` does not use `command_id` as an acknowledgement key. A lost response
uses promotion reconcile. The dashboard does not send these mutations; it only
renders the status fields. Browser exercise of that panel is M6.

Request command IDs provide local ACK-loss deduplication. The browser preserves
an uncertain command ID in session storage for retrying the same intent; inspect
current state first. These IDs do not prove exactly-once remote delivery.

## Verification and limits

The product modules passed **132 tests, 0 skips**, including the M2 HTTP
acceptance tests, the M3 stored-discovery tests, the M4 frozen-import tests,
and the M5 disabled-execution boundary tests, on `.local/product-web-venv`
(Python 3.15.2 / SQLite 3.53.4).
The count is also in [agent milestones](agent-milestones.md). Those HTTP tests
use ASGI in-process requests, not browser interaction. Starlette warns that its working HTTPX adapter
is deprecated; the approved lock remains unchanged and HTTPX2 is not installed.
The temporary browser fixture server was terminated and no service was left
running. A retained source/test cohort and real desktop/mobile browser checks
are separate evidence from dependency installation.

The exact approved Windows wheels and their license metadata are in
`requirements/web-wheel-manifest.json`; measured installation evidence is in
`docs/implementation/web-install-evidence.json`. The Manrope font is self-hosted
with its OFL and pinned source provenance under `coordinator/web_assets/`.
Existing v1 through v6 primary stores need the explicit [offline migration](product-intake.md#schema-migration)
before service startup. Explicit archive restore is specified in
[product intake](product-intake.md#archive-restore). Linux installation, remote
authentication, and production deployment remain unqualified.
