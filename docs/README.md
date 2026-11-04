# SmartBudgetSite Documentation

This directory follows the approved documentation architecture. Active topics
have one authoritative location; chronological implementation notes are kept
separately as history.

## Start here

- `product_positioning.md` — product vision, positioning, philosophy, and
  strategic feature fit.
- `current_state.md` — current implementation state, constraints, and next
  priorities.
- `release_uiux_requirements.md` — detailed approved public release UI/UX
  requirements, stable R01–R55 identifiers and full RU/EN copy.
- `release_readiness.md` — first public commercial release criteria, accepted
  release backlog, expected release gaps, and completion definition.
- `architecture/backend.md` — backend layers, boundaries, and implementation
  rules.
- `architecture/commerce_and_delivery.md` — catalog, sales, payments, releases,
  download entitlements, and protected delivery.
- `architecture/consultations.md` — consultation offers, entitlements, booking,
  Calendly integration, and lifecycle rules.
- `architecture/feedback.md` — feedback, reviews, Q&A, admin workflow, and
  publication rules.
- `operations.md` — development commands, configuration, deployment, and
  operational validation.

## Active source boundaries

- `release_uiux_requirements.md` defines **what** the approved public release
  experience requires: R01–R55, approved and explicitly conditional RU/EN copy,
  image/material requirements, acceptance criteria, required customer-flow
  validation and superseded UX decisions retained to prevent regression.
- `current_state.md` defines what is actually implemented and externally
  validated now; approval of a requirement does not establish completion.
- `release_readiness.md` defines which gates must close before the first public
  commercial release and retains ownership of the Official Release Backlog and
  Expected Release Gaps. The detailed requirements are not a second backlog.
- Architecture documents own domain and lifecycle rules. Requirements that
  conflict with those rules require an explicit decision before implementation.
- Supporting review/research artifacts preserve evidence and reasoning. They do
  not authorize implementation by themselves, replace architecture, establish
  current implementation state or create a competing backlog.

Implementation progress and the next bounded sprint belong in
[current state](current_state.md#release-uiux-implementation-mapping), alongside
the accepted mapping, decision dependencies, groups and separate validation work.

## External sprint working memory

The external Google Doc `SmartBudgetSite — Working Queue` is temporary
operational memory for significant side tasks discovered during the current
sprint. It is not part of this repository's documentation hierarchy, does not
expand a bounded task, and must not be duplicated as a local
`working_queue.md`.

During Sprint Closeout, any unresolved item that must survive the sprint is
classified into the existing authoritative document that owns its durable
obligation, accepted decision, constraint, or deferred work. The queue is not a
parallel Official Release Backlog, Expected Release Gaps list, or permanent
task tracker. See `../AGENTS.md` for ChatGPT and Codex responsibilities and
`operations.md` for the closing review.

## History

- `history/sprint_checkpoints.md` — preserved chronological sprint record.

Historical checkpoints explain how the implementation evolved. They are not a
source of truth for active architecture or current priorities. If a historical
statement differs from an active document, the active document governs.

## Supporting research

- `history/SmartBudget_Refund_Consent_Checkout_Advisory_2026-10-29.md` — preserved
  refund-consent legal/UX research, kept in the existing non-authoritative history
  directory to avoid a new documentation branch. It is not legal advice, final
  wording, proof of compliance, implementation authority, current state,
  architecture or a competing backlog. Accepted planning implications live in
  R49–R54 and the release gates; legal applicability remains unresolved.
