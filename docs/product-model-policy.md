# Model policy and cost

Status: scripted foundation. Schema 7 stores one developer-approved model policy
per milestone, one eligibility assignment per attempt role, and one broker permit
per physical submission. The ledger records reservations and usage quality. It
does not open a socket, call a provider, select a live route, or make
`live_eligible` true.

A policy is `scripted_development` only. Its limits are integer cost units:
`max_reserved_units`, `max_submissions`, and `protected_review_units`. Routes are
`local`, `gateway`, or `direct`, each with a requested model name and an
explicit `available` flag. An unavailable route is denied. Requested
configuration is the model name, max output tokens, and reasoning effort. No
prompt, credential, or endpoint is stored.

## Eligibility

`ModelPolicy.assign` records an eligible assignment for `implementation` or
`review` on an unsettled attempt. The assignment freezes the requested
configuration and the route. Observed identity starts missing `provider`,
`resolved_model`, and `response_id`. A later known usage can fill those fields.
Until then the report keeps them in `missing_observed`.

An unavailable route raises `route unavailable` and stores no assignment. A
permit whose route differs from the assignment raises `fallback route denied`
and stores no reservation.

## Permits and identities

`begin_permit` is developer-only. It commits `possible_send` before any later
usage observation. Each permit has its own `submission_id`. Repeating the same
command id returns the original permit and does not reserve twice. A new command
that reuses a submission id raises `submission replay denied`. An authorized
retry is a new submission id.

The implementation ceiling is `max_reserved_units - protected_review_units`.
Implementation permits cannot spend the protected review allowance. A review
permit can still reserve that allowance after the implementation ceiling is
exhausted, up to the cumulative total. A permit past either bound raises
`cumulative limit exhausted` and stores nothing.

## Usage quality

Usage is `known`, `estimated`, `pending`, or `unknown`.

- `possible_send` with no usage is pending. The full reservation stays charged.
- `lose_response` moves a sent or held permit to `reserved` with quality
  `unknown`. The reservation stays charged. Repeating that observation is a
  duplicate. Reopening the store shows the same unknown units.
- An estimate stays `reserved`. The report shows the estimate separately, and
  the cap still counts the full reservation.
- A known amount at or below the reservation reconciles the permit. Only the
  settled amount stays charged, so the unused remainder can fund a new
  submission.
- A different usage digest fences the project, marks the permit `conflicting`,
  and keeps the full reservation as unknown exposure.

Pause holds `prepared` and `possible_send` permits. It does not release a
`reserved` or `reconciled` row. Held permits count as unknown exposure and as
interventions. Status `capabilities.task_acceptance` stays false.

`report` and status `model_reports` separate `known_units`, `estimated_units`,
`pending_units`, and `unknown_units` from the amount still reserved against the
cap. The same report is `cost-report` on the CLI and
`GET /api/projects/{id}/milestones/{key}/cost` on the loopback API. Status
`cost` sums those four fields across the project's policies. The report keeps
`task_accepted` and `live_eligible` false. Status `scripted_task_accepted` is a
separate promotion fact and does not change either flag or
`capabilities.task_acceptance`. The dashboard renders the status fields. Real
provider behavior, wire identity, and paid-route qualification remain a separate
deployment result.
