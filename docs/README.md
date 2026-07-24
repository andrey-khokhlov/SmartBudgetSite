# SmartBudgetSite Documentation

This directory follows the approved documentation architecture. Active topics
have one authoritative location; chronological implementation notes are kept
separately as history.

## Start here

- `product_positioning.md` — product vision, positioning, philosophy, and
  strategic feature fit.
- `current_state.md` — current implementation state, constraints, and next
  priorities.
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
