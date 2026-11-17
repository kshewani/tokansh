# DRUNIX Platform Contribution Proposal

**Project:** TokANSH  
**Status:** Proposed contribution — technical feasibility and maintainer alignment required  
**Candidate:** Durable, checkpoint-based chaincode event replay and recovery  
**Target upstream:** https://github.com/npci/drunix  
**Related upstream work inspected:** https://github.com/npci/drunix/pull/22

> This is a contribution proposal, not an implemented feature or an accepted DRUNIX roadmap item. Recheck the current upstream source and PR state against the exact commit before coding. Do not describe the feature as delivered until implementation, tests and an upstream PR exist.

## 1. Strategic objective

TokANSH has two related but independent deliverables:

1. A real-estate tokenisation lifecycle prototype using DRUNIX for authoritative ANSH issuance, ownership, transfers and collateral restrictions.
2. A reusable contribution to DRUNIX that improves the platform beyond TokANSH-specific functionality.

The contribution should improve DRUNIX as a general-purpose enterprise ledger platform. It should not be limited to TokANSH chaincode, real-estate terminology or application code.

## 2. Recommended contribution: durable event replay

**Proposed PR title:** `feat(event): add durable checkpoint-based chaincode event replay`

DRUNIX already has chaincode event infrastructure, a Gateway `ChaincodeEvents` API, ledger event iteration and configurable event publishers. The proposal is not to add basic event support. It is to make event publication recoverable across peer restarts and temporary publisher/broker outages.

### Problem statement

Downstream applications may consume chaincode events to build indexes, update read models, drive analytics or trigger business workflows. If events are not delivered during an outage and the publisher does not resume from a durable last-confirmed position, downstream systems can become incomplete or stale.

In the public source inspected on 17 November 2026, `core/peer/channel.go` initializes its event iterator using the current blockchain height. This appears to leave a missed-event risk for blocks committed while the publisher/peer was unavailable. The description of upstream [PR #22 — AMQP 1.0 chaincode event publisher](https://github.com/npci/drunix/pull/22) also explicitly identifies that events committed while the peer is down are not replayed. Revalidate this against the pinned DRUNIX version and current PR state; upstream may have changed.

### Intended capability

1. Track a publishing position per channel, using the exact block/event cursor semantics supported by DRUNIX.
2. Persist the last confirmed publishing checkpoint durably.
3. Resume from that checkpoint after restart, not blindly from the current ledger height.
4. Advance the checkpoint only after the configured publisher confirms success according to its actual delivery contract.
5. Retry transient failures with bounded backoff and a clear shutdown/cancellation path.
6. Use stable event identifiers so consumers can deduplicate redeliveries.
7. Expose logs/metrics for replay position, lag, retries, failures and recovery.
8. Document retention, cleanup, delivery guarantees and operational recovery.

## 3. Delivery guarantee and correctness

Target **at-least-once delivery**, not exactly-once delivery.

A crash can occur after the broker accepts an event but before the checkpoint is persisted. On restart, that event may be published again. This is expected and must be handled through stable event identity and consumer-side deduplication.

Checkpoint advancement must never move past events that have not met the publisher's defined success condition. Define what success means for each publisher; do not assume all publishers provide identical acknowledgement semantics.

The design must consider:
- Multiple channels and independent checkpoints.
- Multiple committing peers publishing the same logical ledger events.
- Concurrent workers and checkpoint ordering.
- Partial failure within a block containing multiple events.
- Process termination during publish/checkpoint update.
- Publisher reconnect and retry behaviour.
- Duplicate delivery.
- Ledger pruning, snapshots and retention constraints.
- Channel removal and checkpoint cleanup ownership.
- Backward compatibility with existing configurations and publishers.

Do not claim exactly-once delivery or imply that broker acknowledgement means a downstream business transaction has been processed.

## 4. Proposed architecture

```text
DRUNIX committed ledger
        |
        v
Ledger event iterator
        |
        v
Replay coordinator <---- durable per-channel checkpoint
        |
        v
Configured event publisher (Kafka / AMQP / other supported publisher)
        |
        v
Downstream event consumer
```

Reuse existing DRUNIX ledger iterators and publisher abstractions wherever practical. Checkpoint persistence should use an existing supported storage abstraction if appropriate and safe. Do not add a new database dependency or couple DRUNIX to TokANSH's application database without a strong upstream architectural reason.

The precise location and ownership of checkpoint state remains unresolved until code inspection. Evaluate peer-local durable metadata or another existing platform abstraction. Ensure the design handles peer identity, channel lifecycle and multiple committing peers correctly.

## 5. Initial upstream PR scope

### In scope
- Durable per-channel publishing checkpoint.
- Resume/replay from the last confirmed position.
- Safe checkpoint advancement after publisher success.
- Retry and recovery for transient failures.
- Stable event identity or documented reuse of existing identifiers.
- Unit tests for checkpoint progression and replay.
- Integration tests for broker outage, restart, replay and duplicate delivery.
- Metrics/logging for replay progress and failures.
- Configuration and operational documentation.

### Out of scope unless maintainers request it
- TokANSH-specific chaincode or real-estate logic.
- New event broker implementations (PR #22 already proposes AMQP 1.0 support).
- New external indexing service or dashboard.
- Exactly-once end-to-end business processing.
- Changes to consensus, ordering, endorsement or validation.
- Direct application access to DRUNIX internal YugabyteDB.
- Broad event API redesign unrelated to replay.

Keep the first PR narrowly reviewable. If maintainers prefer staged work, agree a design issue/PR before the implementation.

## 6. Relationship to TokANSH

TokANSH can consume ledger events to maintain read models and audit projections for ANSH issuance, ownership transfers, pledges, collateral releases and asset lifecycle history.

The ledger remains authoritative. Event consumption is a read-model/reconciliation mechanism, not a replacement for transaction commit confirmation or authoritative ledger queries.

TokANSH must tolerate duplicate events, maintain consumer checkpoints independently where needed, and periodically reconcile important balances/positions against DRUNIX. Event replay does not itself prove that TokANSH processed an event correctly.

## 7. Demonstration scenario

1. Start a local DRUNIX test network and configured event broker.
2. Deploy a small test chaincode that emits events for successful transactions.
3. Start the publisher/consumer and record the last confirmed checkpoint.
4. Stop the broker or make the publisher unavailable.
5. Continue committing transactions on DRUNIX.
6. Restore the broker/publisher.
7. Show replay from the last confirmed position.
8. Demonstrate stable event identifiers and safe duplicate handling.
9. Verify the consumer reconstructs expected event-derived state.
10. Repeat with a process restart at a controlled failure point.

For TokANSH, demonstrate that the event-derived portfolio/audit projection catches up after an outage and reconciles against authoritative DRUNIX state.

Keep these stages distinct in evidence: ledger transaction committed, event published, downstream event processed.

## 8. Acceptance criteria

- [ ] Publisher restart resumes from a durable checkpoint.
- [ ] Events committed during a publisher/broker outage are replayed.
- [ ] Checkpoint never advances beyond the last event confirmed by the configured publisher.
- [ ] Crash between broker acknowledgement and checkpoint persistence produces a safe duplicate rather than a lost event.
- [ ] Event identity is stable across replay and supports deduplication.
- [ ] Multiple channels do not corrupt each other's checkpoints.
- [ ] Existing publisher configurations continue to work unless explicitly documented.
- [ ] Retry/backoff and shutdown behaviour are tested.
- [ ] Unit tests and race tests pass for changed packages.
- [ ] Integration tests cover outage, restart, replay and duplicate delivery.
- [ ] Metrics/logs make replay progress and failures observable.
- [ ] Documentation explains at-least-once semantics and limitations.
- [ ] Formatting, linting and upstream contribution checks pass.
- [ ] Current upstream issues/PRs are checked to avoid duplication.

## 9. Alternatives and supporting contributions

If maintainers consider replay too broad or already planned, investigate:

1. **Event delivery observability:** metrics for publishing lag, checkpoint age, retry count, failed events and replay progress.
2. **Event publisher lifecycle hardening:** bounded retry/backoff, clean shutdown/cancellation and deterministic recovery where gaps remain.
3. **Developer diagnostics/quick-start tooling:** a supported workflow to verify gateway connectivity, identity/TLS configuration, chaincode deployment and commit-status observation.

Do not implement an alternative until source inspection establishes that the capability is genuinely missing and maintainers agree it is useful. Avoid a cosmetic dashboard as the sole platform contribution.

## 10. Feasibility and maintainer alignment gate

Before implementation:

1. Pin the exact DRUNIX commit used by the team.
2. Re-read `core/peer/channel.go`, event iterator and publisher interfaces, all publisher implementations, ledger block iterator behaviour and relevant tests.
3. Review PR #22 and newer event-related PRs/issues.
4. Confirm how event publishing is enabled on committing peers and how multiple peers publish.
5. Determine event ordering and event-position semantics within a block.
6. Identify an existing durable metadata/checkpoint storage abstraction and its lifecycle guarantees.
7. Confirm publisher success/acknowledgement semantics for Kafka, AMQP and other supported publishers.
8. Ask the DRUNIX developer on the TokANSH team to review the proposal and identify implementation constraints.
9. Seek maintainer feedback before investing in a broad implementation.

If replay already exists in the pinned version or is actively being implemented upstream, do not duplicate it. Reassess the gap and choose an alternative based on source evidence.

## 11. Risks and design cautions

| Risk | Why it matters | Required response |
|---|---|---|
| Incorrect checkpoint position | Can skip or duplicate events | Define exact block/event cursor semantics and test boundaries |
| Multiple committing peers | Duplicate publication may be normal | Define peer ownership/topology and stable event identity |
| Weak publisher acknowledgement | Checkpoint may advance before durable broker acceptance | Define publisher-specific success contract |
| Crash during publish | Redelivery may occur | At-least-once semantics and deduplication |
| Checkpoint store lifecycle | Channel removal/restart may lose or leak metadata | Define ownership, cleanup and backup behaviour |
| Ledger retention/pruning | Replay range may no longer be available | Define retention assumptions and explicit failure mode |
| Concurrent workers | Checkpoint may advance out of order | Serialize or prove safe ordered advancement |
| Existing upstream work | Duplicate PR may be rejected | Review current branches, PRs and maintainer roadmap |

## 12. Contribution strategy and judging narrative

Keep the story evidence-led:

- **Problem:** enterprise applications need reliable recovery when consuming ledger events.
- **Platform gap:** inspected source and related upstream discussion indicate a replay/recovery limitation that must be verified against the pinned version.
- **Contribution:** reusable DRUNIX event replay with durable checkpoints, recovery and explicit at-least-once semantics.
- **Proof:** automated failure/recovery tests and a live outage/replay demonstration.
- **Use case:** TokANSH uses the capability to recover event-derived portfolio and audit projections after downtime.

A submitted PR is not an accepted or merged contribution. Report status accurately: proposed, implemented locally, submitted, under review, accepted or merged. This is a potential differentiator, not a guarantee of winning; value depends on correctness, maintainability, demonstrable results and judging criteria.

## 13. Upstream references

- DRUNIX repository: https://github.com/npci/drunix
- Channel event publisher (recheck against pinned commit): https://github.com/npci/drunix/blob/main/core/peer/channel.go
- Gateway chaincode event API: https://github.com/npci/drunix/blob/main/internal/pkg/gateway/chaincodeevents.go
- Event iterator: https://github.com/npci/drunix/blob/main/internal/pkg/gateway/event/chaincodeiterator.go
- Related AMQP event publisher PR #22: https://github.com/npci/drunix/pull/22

**Research limitation:** this proposal reflects public source and PR descriptions inspected on 17 November 2026. Upstream code and PR status are mutable. Revalidate against the pinned source commit before treating any gap as current.
