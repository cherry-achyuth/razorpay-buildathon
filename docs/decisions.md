# Architecture Decision Records (ADRs)

This document records the architectural and engineering decisions made for **DecisionVault**.

---

## ADR-001: Why FastAPI?

### Context
We required a modern, performant, and type-safe Python web framework to build DecisionVault's REST API, OpenAPI specifications, and integration hooks.

### Decision
We selected **FastAPI** paired with **Uvicorn** and **Pydantic v2**.

### Rationale
- **Asynchronous Native**: Built-in `asyncio` support allows high-throughput non-blocking I/O when interacting with databases and payment gateways.
- **Strict Data Validation**: Pydantic v2 ensures strict schema validation and serialization at runtime with minimal overhead.
- **Automated OpenAPI Standards**: Automatic, interactive OpenAPI (`/docs`) and ReDoc (`/redoc`) documentation simplifies agent and client integration.
- **Minimal Footprint**: Unlike monolithic web frameworks, FastAPI provides only the necessary HTTP routing, dependency injection, and validation layers.

---

## ADR-002: Why PostgreSQL?

### Context
DecisionVault requires a reliable database engine capable of storing financial ledgers, audit events, structured policies, and future relational entities with strict ACID guarantees.

### Decision
We selected **PostgreSQL 17/18** as our primary database engine.

### Rationale
- **Enterprise ACID Compliance**: Strict transaction guarantees prevent race conditions and duplicate authorization attempts.
- **Rich Ecosystem**: Native support for JSONB, UUIDs, full-text search, and future vector extensions (`pgvector`) without introducing disparate database technologies prematurely.
- **Operational Reliability**: Mature tooling, backup mechanisms, connection pooling, and wide hosting support.

---

## ADR-003: Why PostgreSQL is the Single Source of Truth?

### Context
In AI-assisted financial systems, intermediate summaries, semantic memories, and cached representations are prone to hallucinations or sync drift.

### Decision
**PostgreSQL is the sole authoritative source of truth for all financial state, mandate limits, transaction ledgers, and audit events.**

### Rationale
- **Financial Safety**: Semantic indices and vector memory are derived representations; they must never be relied upon to determine financial correctness or budget availability.
- **Provenance Verification**: Every decision and memory record must retain foreign keys and cryptographic references back to raw relational PostgreSQL records.
- **Non-Repudiation**: Regulatory and audit compliance requires verifiable relational logs.

---

## ADR-004: Why We Are NOT Introducing Redis Today?

### Context
Distributed caching and pub/sub message brokers like Redis are common in large-scale architectures.

### Decision
**Redis is not introduced on Day 1.**

### Rationale
- **Minimalism & Single Responsibility**: Focus solely on establishing the core application and relational database foundation. Adding Redis at this stage introduces operational complexity without providing immediate functional value.
- **Scope Discipline**: Distributed caching and session locking will be evaluated in later phases when high-concurrency mandate locking or distributed task queues become necessary.

---

## ADR-005: Why We Are NOT Introducing a Vector Database Today?

### Context
Vector databases (e.g., Chroma, Pinecone, pgvector) are frequently used for similarity searches in AI memory systems.

### Decision
**Vector databases and embeddings are not introduced on Day 1.**

### Rationale
- **Foundation First**: Establish the deterministic backend and relational persistence layer.
- **Avoid Premature Complexity**: Semantic similarity search is meaningless without a solid raw transaction history and structured schema.
- **Future Pathway**: When memory compression and semantic retrieval are implemented in later phases, `pgvector` can be introduced directly within the existing PostgreSQL engine without spawning additional infrastructure.

---

## ADR-006: Why We Are NOT Introducing LangGraph Today?

### Context
Agentic workflow orchestrators such as LangGraph provide graph-based state management for multi-agent loops.

### Decision
**LangGraph and agent workflow frameworks are not introduced on Day 1.**

### Rationale
- **Architectural Layering**: DecisionVault is primarily a security and memory middleware API that evaluates financial requests. The agent orchestration framework is an external consumer of DecisionVault, not its internal engine.
- **Dependency Hygiene**: Adding LLM/orchestration SDKs today would violate the principle of no unnecessary dependencies before core API stability is proven.
- **Future Integration**: Orchestration adapters will be introduced cleanly in future phases once the core decision engine is built.

---

## ADR-007: Why Deterministic Financial Controls Will NOT Be Delegated to an LLM?

### Context
Generative AI and LLMs are non-deterministic, susceptible to prompt injection, hallucinations, and probabilistic reasoning errors.

### Decision
**All financial safety checks, spending caps, mandate bounds, and guardrails must remain 100% deterministic and rule-based. LLMs will never possess autonomous authorization power over payment execution.**

### Rationale
- **Zero-Tolerance for Financial Hallucinations**: An LLM must never decide whether a transaction is within budget; deterministic arithmetic and relational constraints must make that decision.
- **Adversarial Robustness**: Prompt injection attacks cannot bypass strict code-level guardrails.
- **Auditability & Explainability**: Every `ALLOW`, `ASK_USER`, or `BLOCK` decision must produce an unambiguous, deterministic rationale trace for compliance and auditing.

---

## ADR-008: Why PostgreSQL Relational Financial Domain Modeling?

### Context
Financial entities (users, merchants, mandates, policies, transactions, decisions) have strict relational constraints, cardinality, and referential dependencies.

### Decision
**We implement a strongly typed, fully relational schema in PostgreSQL with explicit foreign keys, check constraints, and indexes.**

### Rationale
- **Integrity Enforcement**: Database-level constraints guarantee that transactions cannot exist without valid users and merchants, and monetary values remain strictly positive.
- **Maintainability**: Clear relational models prevent schema chaos compared to unconstrained document stores or generic JSON blobs.
- **Auditability**: Strongly typed relational tables provide deterministic query paths and query optimization for financial reconciliation.

---

## ADR-009: Why Exact Monetary Representation (Decimal/Numeric) Instead of Float?

### Context
Binary floating-point arithmetic (IEEE 754 `float` / `double`) introduces binary rounding artifacts (e.g. `10.10` becomes `10.099999999999999`), which is unacceptable for financial authorization.

### Decision
**All monetary values (amounts, limits, budget caps) must strictly use `Numeric(18, 4)` in PostgreSQL / SQLAlchemy and Python `Decimal` in Pydantic models. Floats are prohibited.**

### Rationale
- **Precision Guarantee**: Base-10 exact decimal representation eliminates rounding errors and fractional penny loss during arithmetic operations.
- **Multi-Currency Precision**: 4 decimal places provide sufficient precision across global currencies and micro-transactions while maintaining consistency.

---

## ADR-010: Why Raw Transaction History Remains Authoritative?

### Context
Autonomous agent workflows create intermediate context, vector embeddings, and compressed decision summaries.

### Decision
**The `transactions` table contains the immutable, raw financial source of truth. Memory records and summaries are derived downstream representations.**

### Rationale
- **Provenance Integrity**: Any derived AI memory or summary must be traceable back to exact relational rows in `transactions`.
- **Replayability**: If an agent's memory compression model or guardrail algorithm changes, raw transactions can be replayed to rebuild derived memory without data loss.

---

## ADR-011: Why Transaction and Decision Are Separate Concepts?

### Context
A decision and a transaction both relate to financial authorization, tempting developers to merge them into a single entity.

### Decision
**`Decision` (the evaluation and justification outcome: `ALLOW`, `ASK_USER`, `BLOCK`) and `Transaction` (the recorded monetary transfer event) are modeled as distinct, decoupled tables.**

### Rationale
- **Multiple Decisions per Transaction/Attempt**: A transaction may be blocked before any monetary movement occurs (yielding a Decision without a completed Transaction), or asked for user clarification.
- **Separation of Concerns**: Decisions represent security/policy evaluation traces; Transactions represent accounting/ledger state.

---

## ADR-012: Why We Avoid Cascading Deletion for Financial History?

### Context
Cascading foreign key deletes (`ON DELETE CASCADE`) automatically remove dependent records when a parent record is removed.

### Decision
**All financial foreign key constraints enforce `ondelete="RESTRICT"`. Cascading deletes on transactions, mandates, policies, and decisions are prohibited.**

### Rationale
- **Non-Repudiation**: Financial records, payment attempts, and decision logs must never be silently purged due to user deactivation or merchant updates.
- **Regulatory Compliance**: Financial records require immutable audit trails. Entities should be deactivated via status flags (`SUSPENDED`, `INACTIVE`, `REVOKED`) rather than hard deleted.

---

## ADR-013: Why Deterministic Financial Controls Are Separate from AI Reasoning?

### Context
AI agents reason probabalistically over natural language, but financial authorizations govern real monetary funds where false positives or hallucinations cause irreparable loss.

### Decision
**Deterministic financial guardrails (`MandateConstraintRule`, `PolicyLimitRule`) are executed as an independent hard security layer. The AI/LLM layer has zero execution control over guardrail rules.**

### Rationale
- **Security Boundary**: The AI agent is the caller/proposer, never the validator.
- **Explainability**: Every outcome produces deterministic reason codes and exact arithmetic evidence (`requested_amount <= mandate_cap`).
- **Prompt Injection Defense**: An agent cannot bypass spending limits by manipulating prompt text or passing override flags.

---

## ADR-014: Why Hard Rule Failures Have Absolute Precedence over ALLOW?

### Context
Multi-rule policy engines must combine results from multiple checks (mandate validity, velocity limits, spending caps, merchant allowlists).

### Decision
**`BLOCK` has absolute precedence. If any mandatory rule evaluates to `BLOCK`, the aggregate decision is irrevocably `BLOCK`.**

### Rationale
- **Fail-Safe Default**: In high-stakes financial operations, a single security violation must immediately halt the transaction.
- **No Override via downstream rules**: No positive recommendation from another rule or memory module can convert a `BLOCK` into an `ALLOW`.

---

## ADR-015: Why Decision Evaluation Is Separated from Payment Execution?

### Context
In automated agent workflows, evaluating whether an action is safe must frequently happen before preparing payment payloads or initiating tokenized debit flows.

### Decision
**The evaluation endpoint (`POST /api/v1/decisions/evaluate`) purely evaluates safety and records audit provenance without debiting accounts or invoking payment gateway APIs.**

### Rationale
- **Two-Phase Authorization**: Agents can pre-flight check proposals without committing real-world monetary effects.
- **Idempotency & Replay**: Evaluation can safely be simulated and audited without triggering double-charge risks.
- **Payment Gateway Isolation**: Payment integration (such as Razorpay test mode in subsequent phases) remains an isolated downstream step executed only upon verified `ALLOW`.

---

## ADR-016: Why Duplicate Detection Is Architecturally Distinct from Idempotency?

### Context
Developers often conflate request idempotency with duplicate payment detection because both address repeated financial requests.

### Decision
**DecisionVault strictly models and enforces Idempotency Protection and Duplicate Payment Detection as two distinct guardrails with separate persistence mechanisms and semantics:**
- **Idempotency Protection (`IdempotencyRule`)**: Answers "Is this the exact same client request being retried?" Uses canonical SHA-256 request hashing against stored `IdempotencyRecord` keys. If payload matches, it safely returns the cached decision; if payload was modified, it rejects as a conflict (`BLOCK`).
- **Duplicate Payment Detection (`DuplicatePaymentRule`)**: Answers "Is this an accidental repeated purchase of the same product/amount within a short sliding window?" Uses historical transactions within `DUPLICATE_DETECTION_WINDOW_SECONDS` (default 300s) to block rapid repeated fund debits.

### Rationale
- **Legitimate Periodic Purchases**: A user purchasing ₹500 groceries weekly from the same merchant is legitimate, not a duplicate.
- **Tampering Resistance**: An idempotency key must never allow modifying transaction parameters (e.g. changing amount from ₹100 to ₹5000 under the same key).

---

## ADR-017: Why Contextual Safety Signals Produce ASK_USER Instead of Hard BLOCK?

### Context
Not all anomalies in autonomous agent behavior represent malicious fraud or policy violations. Some represent genuine consumer price changes or new merchant relationships.

### Decision
**Contextual safety signals (such as `PriceDriftRule` and `MerchantChangeRule`) produce `ASK_USER` rather than automatically `BLOCK`ing transactions, unless an explicit hard policy or mandate restriction also fails.**

### Rationale
- **Proportional Response**: A price increase of 30% on a cloud compute subscription or changing to a new merchant is not inherently fraudulent, but it warrants user confirmation before funds are debited.
- **Avoiding False Positives**: Overly aggressive blocking creates severe user friction and breaks agent autonomy for routine commercial adjustments.
- **Rule Precedence Preservation**: Hard `BLOCK`s (mandate/policy caps, duplicate payments, idempotency conflicts) strictly override `ASK_USER`. All rule results are preserved for audit visibility.

---

## ADR-018: Why Historical Transaction Evidence Is Deterministically Filtered?

### Context
Evaluating historical patterns (price drift, duplicate detection, merchant history) requires querying prior transactions from PostgreSQL. Unfiltered or unbounded queries cause N+1 performance bottlenecks and noisy baselines.

### Decision
**Historical transaction queries are bounded, targeted, and strictly filtered by user ID, currency, matching transaction type, and valid completed statuses (`CAPTURED`, `AUTHORIZED`). Failed, cancelled, and refunded transactions are excluded from purchase price baselines.**

### Rationale
- **Zero Cross-Tenant Leakage**: All queries are strictly scoped to the authenticated `user_id`.
- **Baseline Accuracy**: Failed payment attempts and refunds do not represent true purchase costs and must not skew median price drift calculations.
- **Performance & Bounded Memory**: Queries use explicit `LIMIT`s (e.g. 20 rows for price history, 50 rows for merchant history) and sliding time windows rather than loading unbounded historical datasets into application memory.

---

## ADR-019: Why Raw Financial History Remains the Authoritative Source of Truth?

### Context
When introducing a memory layer, systems risk replacing the underlying transaction ledger with condensed memory blobs, making independent verification difficult or impossible.

### Decision
**PostgreSQL `transactions` table remains the immutable and authoritative financial source of truth. The memory layer never modifies, overwrites, or deletes source transactions during memory construction or lifecycle retirement.**

### Rationale
- **Financial Auditability**: Any derived financial memory must be traceable back to exact relational rows in `transactions`.
- **Zero Data Loss**: Corrupted or outdated derived memories can be safely retired or deleted without affecting ledger integrity.

---

## ADR-020: Why Decision Memory Is Derived Rebuildable State?

### Context
Memory compression and consolidation will evolve across project iterations. Storing memory as an irreplaceable primary record would create technical debt and migration risks.

### Decision
**`DecisionMemory` is modeled as a derived, secondary representation. The memory builder service guarantees deterministic rebuildability: deleting or recalculating derived memory from raw transactions produces equivalent decision-relevant fields (`memory_type`, `relevance`, `summary`, `structured_data`, and `sources`).**

### Rationale
- **Algorithm Evolution**: As compression, clustering, or summarization algorithms improve, historical memories can be re-derived from raw transaction data.
- **Experimental Repeatability**: The core hypothesis of DecisionVault ("maximum memory compression while preserving decisions") can be rigorously benchmarked by rebuilding memory variants against the same source dataset.

---

## ADR-021: Why Source Provenance Is Required for Financial Memory?

### Context
Autonomous agents need to know *why* a particular constraint or pattern exists in their memory context before making authorization choices.

### Decision
**Every `DecisionMemory` record must link to its underlying source entity via `DecisionMemorySource` (`source_type`, `source_id`). Unlinked or unattributed memories are prohibited.**

### Rationale
- **Explainability**: Financial decisions require clear justifications (e.g. "Price drift warning triggered by Transactions T1, T2, T3").
- **Integrity Validation**: Cross-user memory creation or unauthorized provenance association is blocked at the database and service layers.

---

## ADR-022: Why Deterministic Relevance Precedes Semantic/LLM Memory?

### Context
A common temptation in AI projects is using LLMs or vector search for all classification and memory creation from Day 1.

### Decision
**Decision relevance (`CRITICAL`, `HIGH`, `NORMAL`, `LOW`) is initially implemented via explicit, deterministic rules (`DecisionRelevanceClassifier`) before introducing LLMs or embeddings. Safety-critical events (mandate revocations, hard blocks) are never downgraded merely because of elapsed time.**

### Rationale
- **Safety Override Invariant**: An old mandate revocation remains CRITICAL regardless of time passed. Probabilistic vector search or LLM decay functions could dangerously drop old critical security constraints.
- **Reproducibility**: Deterministic relevance establishes a reliable baseline against which future AI and semantic compression techniques can be evaluated.

---

## ADR-023: Decision Memory Is Context, Not Authorization

### Context
When integrating memory into the decision evaluation service, there is a temptation to let positive memory patterns (e.g. "frequent routine buyer") relax or bypass hard safety guardrails (policy caps, mandate restrictions).

### Decision
**`DecisionMemory` provides structured historical context to the evaluation engine, but possesses zero independent financial authorization authority. Hard deterministic guardrails (`MandateConstraintRule`, `PolicyLimitRule`, `DuplicatePaymentRule`, `IdempotencyRule`) remain authoritative. Memory can never turn `BLOCK` into `ALLOW` or independently authorize transactions.**

### Rationale
- **Zero Bypass Guarantee**: Malicious or corrupted memories cannot circumvent mandate limits or user budget policies.
- **Safe Degradation**: If memory retrieval fails or is empty, deterministic guardrails continue protecting financial movements normally without failing open.
- **Explainable Auditing**: Decisions record the active memory context alongside rule results in `evidence_metadata`, enabling full retrospective auditability.

---

## ADR-024: Semantic Retrieval Is a Candidate Retrieval Mechanism, Not a Financial Decision Mechanism

### Context
With the introduction of vector embeddings and semantic similarity searches, there is a risk of conflating semantic similarity with financial authorization or decision authority.

### Decision
**Semantic similarity via pgvector is strictly a candidate-retrieval mechanism. Similarity score is retrieval metadata, not a financial risk score or authorization token. High semantic similarity with past transactions can NEVER independently authorize a transaction (`ALLOW`) or override a deterministic guardrail (`BLOCK`).**

### Rationale
- **Similarity ≠ Authorization**: An action can be 99% semantically similar to a past approved purchase but still violate an active policy limit, mandate constraint, or duplicate detection window.
- **Single Source of Truth**: Vector embeddings are derived representations stored in PostgreSQL alongside structured metadata. PostgreSQL remains the single source of truth; no external vector database (ChromaDB, Pinecone, FAISS) is introduced.
- **Strict Tenant Isolation**: Vector searches enforce SQL-level `user_id` filtering prior to similarity score computation, eliminating cross-tenant candidate leakage.

---

## ADR-025: Hybrid Memory Retrieval Preserves Deterministic Financial Authority

### Context
Pure deterministic retrieval relies only on exact structured filters, potentially missing contextually relevant historical memories. Pure semantic retrieval ranks solely by vector cosine similarity, creating the danger that a routine purchase memory with 99% similarity displaces an older safety-critical mandate revocation or policy event.

### Decision
**Implement a two-stage Hybrid Memory Retrieval Layer (`HybridMemoryRetrievalService`). Stage 1 performs strict deterministic candidate filtering in SQL (user isolation, active status, temporal bounds, lookback limit). Stage 2 computes semantic vector similarity and applies a deterministic tiered lexicographic ranking (`CRITICAL > HIGH > NORMAL > LOW`, then similarity score descending, then recency descending).**

### Rationale
- **Relevance Precedence Guarantee**: Safety-critical memories (`CRITICAL`, `HIGH`) are guaranteed first-class ranking and can never be displaced by a `NORMAL` memory solely due to high semantic similarity.
- **Explainability & Reproducibility**: Ranking is 100% deterministic and explainable without opaque ML rankers or probabilistic LLMs.
- **Safe Degradation**: If vector embedding or similarity operations fail, the service gracefully falls back to deterministic retrieval, ensuring no authorization bypass.
- **Context, Not Authority**: Hybrid memory candidates serve solely as structured context for deterministic guardrails. Hard financial safety rules retain absolute decision authority.

---

## ADR-026: Decision-Preserving Deterministic Memory Compression

### Context
Autonomous buying agents generate extensive raw financial transaction logs over time. Retaining only raw transactions in context windows risks token exhaustion and latency degradation, while naively using LLMs or lossy semantic clustering risks hallucinating metrics, erasing chargeback histories, or deleting authoritative records.

### Decision
**Implement a deterministic, decision-preserving financial memory compression mechanism (`MemoryCompressionService`). Compression consolidates redundant routine transactions into aggregated `DecisionMemory` entities with exact `Decimal` precision while preserving 1:N provenance to all underlying source transaction IDs via `DecisionMemorySource`. Raw `Transaction` records remain permanently in PostgreSQL and are NEVER deleted or mutated. Safety-critical events (`CRITICAL`/`HIGH` relevance, failed payments, chargebacks, anomalies) MUST NOT be merged into routine aggregates.**

### Rationale
- **Raw History Permanence**: Authoritative financial source records in PostgreSQL remain untouched, ensuring zero data loss and full audit compliance.
- **Zero Hallucination / Exact Precision**: All aggregate metrics (count, total, min, max, avg) are computed with exact Python `Decimal` arithmetic.
- **Safety Over Compression**: If events have conflicting safety characteristics, they are preserved separately. A critical event is never hidden inside a generic routine pattern.
- **Full Traceability**: 1:N `DecisionMemorySource` links maintain bi-directional auditability between derived memories and source transactions.
- **Idempotency**: Repeated compression executions against unchanged history reuse existing active memories without creating redundant duplicate rows.

---

## ADR-027: Tamper-Evident Hash-Chained Audit Log

### Status
Accepted (Day 10)

### Context
DecisionVault records raw financial transactions, builds derived decision memories, and executes deterministic authorization decisions. To ensure operational integrity, compliance, and post-hoc forensic auditability, the system requires a verifiable operational history showing what events occurred, when, for which user, and whether records have been modified or deleted.

### Decision
**Implement a tamper-evident hash-chained audit log (`AuditLog` model and `AuditLogService`). Each audit record contains a monotonic sequence number, canonical serialized event data, timestamp, SHA-256 record hash, and a cryptographic link to the immediately preceding record hash (`previous_hash`). An unbroken chain verification endpoint (`GET /api/v1/audit/verify`) detects any payload alteration, sequence gap, link tampering, or deletion.**

### Rationale
- **Tamper Evidence vs Blockchain**: Standard SHA-256 cryptographic hash-chaining within PostgreSQL provides robust, deterministic tamper detection without the latency, complexity, or token economics of blockchain networks.
- **Evidence vs Immutability**: Hash chaining makes unauthorized modification detectable. It does not claim legal immutability or prevent DBA access; rather, any tampering breaks mathematical verification immediately.
- **Observational Isolation**: Audit records are purely observational evidence. They possess zero payment authorization power and cannot override deterministic financial guardrails (`MandateConstraintRule`, `PolicyLimitRule`, `DuplicatePaymentRule`, etc.).
- **Deterministic Canonicalization**: Canonical JSON serialization (sorted keys, compact separators, normalized UUIDs/timestamps/Decimals) guarantees 100% hash reproducibility across environments.

---

## ADR-028: Decision-Preservation Evaluation Against Authoritative History

### Status
Accepted (Day 11)

### Context
DecisionVault consolidates redundant transactions into compressed `DecisionMemory` entities to provide contextual evidence to deterministic financial guardrails. To establish research integrity and empirical verification, the system must objectively evaluate whether compressed memory preserves the exact same financial decisions ($A == B$) produced from complete raw PostgreSQL history across diverse scenarios.

### Decision
**Implement a dual-path comparative evaluation framework (`FullHistoryBaselineEvaluator`, `CompressedMemoryEvaluator`, and `DecisionPreservationService`). For identical financial scenarios, the framework evaluates the decision using full raw history (Path A) and compressed memory context (Path B) through the same deterministic rule engine, detecting and categorizing any decision mismatch into explicit severity classes (`FALSE_ALLOW`, `FALSE_BLOCK`, `FALSE_ASK_USER`, `MISSED_BLOCK`, `MISSED_ASK_USER`).**

### Rationale
- **Full History as Authoritative Baseline**: PostgreSQL raw transactions remain the uncompromised source of truth. The full-history path does not use memory or AI.
- **Identical Guardrail Execution**: Both evaluation paths execute through the same `DeterministicRuleEngine` and precedence logic, ensuring observed differences arise solely from memory context quality.
- **Explicit Safety Classification**: Mismatches where safety is compromised (such as `FALSE_ALLOW` or `MISSED_BLOCK`) are distinguished from usability/availability penalties (`FALSE_BLOCK`).
- **No Fabricated Benchmarks**: All metrics (preservation rate, safety-critical rate, compression ratio) are derived strictly from live test/experiment execution.

---

## ADR-029: Adversarial and Boundary Decision-Preservation Evaluation Suite

### Status
Accepted (Day 12)

### Context
A standard 5-scenario evaluation suite is sufficient to prove functional correctness but insufficient to demonstrate decision preservation across edge conditions, monetary boundaries, and adversarial counterparty shifts. The evaluation subsystem must provide deterministic stress-testing covering exact policy boundaries ($limit \pm 0.01$), exact price drift thresholds ($threshold \pm 1.0\%$), counterparty identity shifts, critical exception preservation in redundant histories, and critical memory recall.

### Decision
**Extend `ScenarioFactory` and `DecisionPreservationService` with the `ADVERSARIAL` scenario suite and `critical_memory_recall` metric. The suite deterministically generates boundary scenarios (policy limits, price drift thresholds, similar counterparty names with distinct UUIDs, redundancy stress, and critical event preservation). The framework calculates $\text{critical\_memory\_recall} = \frac{\text{critical\_events\_preserved}}{\text{critical\_events\_required}}$ by validating active memory provenance links against raw safety-critical transactions.**

### Rationale
- **Boundary Stress Testing**: Monetary policies and price drift tolerances must be evaluated at exact mathematical thresholds to prevent subtle regression.
- **Critical Event Recall**: Measuring the preservation of critical/high relevance events (e.g. failed payments, chargebacks) guarantees that routine compression does not absorb or destroy safety-critical anomalies.
- **Full Backward Compatibility**: The existing standard suite (`ScenarioSuite.STANDARD`) and custom scenario inputs remain fully functional.

---

## ADR-030: Synthetic Financial Dataset Infrastructure for Decision Preservation Experiments

### Status
Accepted (Day 13)

### Context
To scientifically evaluate DecisionVault's core claim ("Maximum memory compression while preserving financially important decisions"), the system requires controlled financial datasets where routine history and decision-critical events (price spikes, counterparty transitions, failures, duplicate payments, policy breaches) are explicitly and deterministically labeled. Using uncontrolled production data would risk PII leakage and lack reproducible ground-truth labels.

### Decision
**Implement a dedicated, deterministic synthetic dataset generation and fixture framework located in `experiments/synthetic/`. The module provides `SyntheticDatasetGenerator`, controlled scenario strategies (`ScenarioGenerator`), JSON serialization (`save_dataset_to_json` / `load_dataset_from_json`), and database seeding (`seed_synthetic_dataset_to_db`). Ground truth explicitly labels routine compression candidates versus decision-critical events without modifying production database schemas or runtime decision logic.**

### Rationale
- **Strict Seed Reproducibility**: Enables bitwise reproducible experiment fixtures across arbitrary scales (`SMALL`, `MEDIUM`, `LARGE`, `CUSTOM`).
- **Complete Decoupling**: Dataset generation is strictly isolated under `experiments/synthetic/`, ensuring zero impact or pollution of production FastAPI routes, database models, or payment logic.
- **Explicit Ground-Truth Labeling**: Clarifies experiment intent without requiring the production engine to guess what scenario was generated.
- **Direct Subsystem Integration**: Generated datasets seamlessly seed into PostgreSQL test instances and drive memory compression and evaluation pipelines.

---

## ADR-031: Razorpay Test Mode Payment Gate & Autonomous Agent Execution

### Status
Accepted (Buildathon Complete)

### Context
Autonomous AI buying agents require a secure, deterministic middleware execution gate before funds can be debited via payment gateways like Razorpay. The system must prevent unauthorized money movement when deterministic guardrails trigger `BLOCK` or when an anomaly triggers `ASK_USER`. Furthermore, payment execution must be idempotent and fully auditable with tamper-evident SHA-256 hash chaining.

### Decision
**Implement a code-controlled payment execution gate (`PaymentExecutionService`) integrated with official Razorpay Test Mode / Sandbox APIs (`POST https://api.razorpay.com/v1/orders`). The payment gate guarantees that:**
1. **Zero funds can be debited if the deterministic guardrails evaluate to `BLOCK`**.
2. **Payment is halted if the decision is `ASK_USER` until explicit user confirmation is received via `POST /api/v1/payments/decisions/{id}/confirm`**.
3. **Payments that evaluate to `ALLOW` create an official Razorpay Test Mode order, persist the authoritative `Transaction` record, and append tamper-evident audit events (`PAYMENT_REQUESTED`, `PAYMENT_ATTEMPTED`, `PAYMENT_SUCCEEDED`)**.
4. **When test credentials are not configured in environment variables, the system executes in observable sandbox simulation mode without breaking or failing closed**.

### Rationale
- **Code-Controlled Financial Boundary**: LLMs and AI agents have zero direct payment authorization authority. Deterministic guardrails and user confirmations remain the sole arbiters of payment execution.
- **Idempotency & Replay Protection**: Protects against double charges and network retry races.
- **Full Traceability**: All payment lifecycle events are permanently linked into the linear cryptographic audit log.

---

## ADR-032: Two-Tier Policy Limits (Hard Absolute Ceiling vs History-Grounded Soft Threshold)

### Status
Accepted

### Context
Single flat policy spend caps (e.g., a blanket ₹100 or ₹500 limit across all merchants) fail to scale across real-world merchant portfolios where legitimate price points differ substantially (e.g., a ₹149–649/month Netflix subscription vs a ₹15 grocery item). Under strict deterministic rule precedence where `BLOCK` $\succ$ `ASK_USER`, a single flat cap immediately hard-blocks legitimate subscription renewals even when the price matches the user's established historical spending pattern, conflating legitimate routine costs with fraudulent anomalies.

### Decision
**Split the `Policy` spend boundaries into two distinct enforcement tiers:**
1. **Hard Ceiling (`hard_limit_amount`)**: An absolute, non-negotiable monetary cap. Any transaction exceeding this limit results in an unconditional, immediate `BLOCK` (`POLICY_HARD_LIMIT_EXCEEDED`) regardless of merchant history or historical memory.
2. **Soft Limit (`limit_amount`)**: A routine spend threshold. When a transaction exceeds the soft limit:
   - If the merchant has an **established price history** (via `merchant_historical_transactions` or compressed memory context) and the requested amount is **consistent with that merchant's historical median**, the decision effect is downgraded to `ASK_USER` (`POLICY_SOFT_LIMIT_EXCEEDED`), allowing human authorization instead of a hard block.
   - If the merchant has **no established history** (or the price wildly deviates from historical baselines), the system fails closed with a hard `BLOCK` (`POLICY_LIMIT_EXCEEDED`).

### Rationale
- **Context-Aware Safety Without Sacrificing Invariants**: Preserves the non-negotiable hard ceiling against runaway agent spend while preventing false-positive blocks on verified recurring subscriptions.
- **Fail-Closed Default**: New or unverified merchants exceeding the soft limit remain strictly blocked unless explicitly approved.
- **Interpretable Reasoning**: Clear separation of `POLICY_HARD_LIMIT_EXCEEDED` (unconditional cap) vs `POLICY_SOFT_LIMIT_EXCEEDED` (routine threshold surpassed but historical baseline matches).

---

## ADR-033: Human-Authorized Baseline Updates & Anti-Ratcheting Cooldown Safeguards

### Status
Accepted

### Context
When a merchant legitimately increases subscription pricing (e.g. Netflix upgrading a tier from ₹499 to ₹649 or general inflation), `PriceDriftRule` correctly flags the first transaction as `ASK_USER`. However, if the user approves the payment as a permanent plan change, evaluating future monthly renewals would continue to trigger `ASK_USER` every single billing cycle unless the underlying financial baseline memory is updated. Conversely, allowing an AI agent or automated process to self-update price baselines would create a catastrophic vulnerability: an attacker or runaway LLM could incrementally increase prices ("boiling frog" or ratcheting attack) without human oversight.

### Decision
**Implement a strict, human-authorized Baseline Update Workflow:**
1. **Explicit Human Confirmation**: A baseline update can ONLY be triggered via `POST /api/v1/payments/decisions/{id}/confirm` when the human user explicitly supplies `accept_as_new_baseline: true`. The AI Buying Agent (`/api/v1/agent/evaluate`) has zero capability to alter baselines autonomously.
2. **Permanent Memory Derivation**: When confirmed, prior routine memories for that merchant are marked `SUPERSEDED`, and a new active `DecisionMemory` is generated with `confirmed_by_user: True` and the new baseline amount. `PriceDriftRule` prioritizes this confirmed memory baseline over older raw transaction history.
3. **Anti-Ratcheting Cooldown Safeguard**: To prevent gradual manipulation via rapid successive confirmations, a minimum 7-day cooldown window is enforced between baseline updates per merchant. Any subsequent attempt to shift a baseline within the window is rejected with `BASELINE_UPDATE_COOLDOWN_ACTIVE`.
4. **Cryptographic Audit Trail**: Every baseline shift produces an append-only, SHA-256 hash-chained `BASELINE_UPDATED` event in `audit_logs`, immutably recording `old_baseline`, `new_baseline`, `merchant_id`, and `confirmed_by: "USER"`.

### Rationale
- **User Agency**: Humans maintain sole authority over what constitutes an acceptable recurring baseline.
- **Security Boundary**: The AI Buying Agent remains untrusted and strictly bounded.
- **Ratcheting Protection**: Mathematical cooldown prevents incremental budget dilation attacks.




