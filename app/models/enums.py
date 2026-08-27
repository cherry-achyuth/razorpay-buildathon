"""Controlled domain enumerations for DecisionVault."""

from enum import StrEnum


class UserStatus(StrEnum):
    """User account lifecycle status."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class MerchantStatus(StrEnum):
    """Merchant status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MandateStatus(StrEnum):
    """Financial authorization mandate status."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PolicyType(StrEnum):
    """Policy categorization."""

    BUDGET = "BUDGET"
    TRANSACTION_LIMIT = "TRANSACTION_LIMIT"
    MERCHANT_RESTRICTION = "MERCHANT_RESTRICTION"
    CATEGORY_RESTRICTION = "CATEGORY_RESTRICTION"


class PolicyStatus(StrEnum):
    """Policy lifecycle status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TransactionType(StrEnum):
    """Financial transaction classification."""

    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    PAYMENT_ATTEMPT = "PAYMENT_ATTEMPT"


class TransactionStatus(StrEnum):
    """Transaction lifecycle status."""

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class DecisionOutcome(StrEnum):
    """Deterministic decision authorization outcome."""

    ALLOW = "ALLOW"
    ASK_USER = "ASK_USER"
    BLOCK = "BLOCK"


class RuleStatus(StrEnum):
    """Execution status of a single rule check."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RuleDecisionEffect(StrEnum):
    """The decision consequence if a rule fails or triggers."""

    NONE = "NONE"
    BLOCK = "BLOCK"
    ASK_USER = "ASK_USER"


class RuleSeverity(StrEnum):
    """Severity classification of the rule evaluation."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class MemoryType(StrEnum):
    """Classification of financial decision memory."""

    ROUTINE_PATTERN = "ROUTINE_PATTERN"
    PRICE_PATTERN = "PRICE_PATTERN"
    MERCHANT_PATTERN = "MERCHANT_PATTERN"
    POLICY_EVENT = "POLICY_EVENT"
    MANDATE_EVENT = "MANDATE_EVENT"
    ANOMALY_EVENT = "ANOMALY_EVENT"
    DECISION_CONTEXT = "DECISION_CONTEXT"


class MemoryRelevance(StrEnum):
    """Deterministic relevance priority for decision memories."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class MemoryStatus(StrEnum):
    """Lifecycle status of a decision memory."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class MemorySourceType(StrEnum):
    """Source entity type providing provenance for a memory record."""

    TRANSACTION = "TRANSACTION"
    DECISION = "DECISION"
    MANDATE = "MANDATE"
    POLICY = "POLICY"


class RetrievalMode(StrEnum):
    """Memory search retrieval strategy."""

    SEMANTIC = "SEMANTIC"
    HYBRID = "HYBRID"
    DETERMINISTIC = "DETERMINISTIC"


class AuditEventType(StrEnum):
    """Event classification for tamper-evident audit log."""

    MEMORY_CREATED = "MEMORY_CREATED"
    MEMORY_COMPRESSED = "MEMORY_COMPRESSED"
    MEMORY_REUSED = "MEMORY_REUSED"
    MEMORY_RETIRED = "MEMORY_RETIRED"
    DECISION_EVALUATED = "DECISION_EVALUATED"
    DECISION_PRESERVATION_EVALUATED = "DECISION_PRESERVATION_EVALUATED"
    AGENT_REQUEST_RECEIVED = "AGENT_REQUEST_RECEIVED"
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
    PAYMENT_ATTEMPTED = "PAYMENT_ATTEMPTED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    BASELINE_UPDATED = "BASELINE_UPDATED"


class DecisionMismatchType(StrEnum):
    """Categorical classification of decision mismatch severity between full history and compressed memory."""

    MATCH = "MATCH"
    FALSE_ALLOW = "FALSE_ALLOW"
    FALSE_BLOCK = "FALSE_BLOCK"
    FALSE_ASK_USER = "FALSE_ASK_USER"
    MISSED_BLOCK = "MISSED_BLOCK"
    MISSED_ASK_USER = "MISSED_ASK_USER"


class ScenarioSuite(StrEnum):
    """Evaluation benchmark scenario suites."""

    STANDARD = "STANDARD"
    ADVERSARIAL = "ADVERSARIAL"
    CUSTOM = "CUSTOM"
