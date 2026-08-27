"""financial domain models

Revision ID: 0002_financial_domain_models
Revises: 0001_initial_baseline
Create Date: 2026-08-23 18:00:00.000000 UTC

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_financial_domain_models"
down_revision: str | None = "0001_initial_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_reference", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        op.f("ix_users_external_reference"),
        "users",
        ["external_reference"],
        unique=True,
    )
    op.create_index(
        op.f("ix_users_status"),
        "users",
        ["status"],
        unique=False,
    )

    # 2. Merchants table
    op.create_table(
        "merchants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("external_reference", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merchants")),
    )
    op.create_index(
        op.f("ix_merchants_name"),
        "merchants",
        ["name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_merchants_external_reference"),
        "merchants",
        ["external_reference"],
        unique=True,
    )
    op.create_index(
        op.f("ix_merchants_status"),
        "merchants",
        ["status"],
        unique=False,
    )

    # 3. Mandates table
    op.create_table(
        "mandates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "max_transaction_amount",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "max_transaction_amount > 0",
            name=op.f("ck_mandates_positive_max_amount"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name=op.f("ck_mandates_valid_date_range"),
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name=op.f("ck_mandates_currency_format"),
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_mandates_merchant_id_merchants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_mandates_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mandates")),
    )
    op.create_index(
        op.f("ix_mandates_merchant_id"),
        "mandates",
        ["merchant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mandates_status"),
        "mandates",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mandates_user_id"),
        "mandates",
        ["user_id"],
        unique=False,
    )

    # 4. Policies table
    op.create_table(
        "policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("policy_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "limit_amount",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rules", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "limit_amount IS NULL OR limit_amount >= 0",
            name=op.f("ck_policies_positive_limit_amount"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name=op.f("ck_policies_valid_date_range"),
        ),
        sa.CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name=op.f("ck_policies_currency_format"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_policies_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policies")),
    )
    op.create_index(
        op.f("ix_policies_policy_type"),
        "policies",
        ["policy_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_policies_status"),
        "policies",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_policies_user_id"),
        "policies",
        ["user_id"],
        unique=False,
    )

    # 5. Transactions table
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("mandate_id", sa.Uuid(), nullable=True),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_reference", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount > 0",
            name=op.f("ck_transactions_positive_amount"),
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name=op.f("ck_transactions_currency_format"),
        ),
        sa.ForeignKeyConstraint(
            ["mandate_id"],
            ["mandates.id"],
            name=op.f("fk_transactions_mandate_id_mandates"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_transactions_merchant_id_merchants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transactions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(
        op.f("ix_transactions_external_reference"),
        "transactions",
        ["external_reference"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_idempotency_key"),
        "transactions",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_transactions_mandate_id"),
        "transactions",
        ["mandate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_merchant_id"),
        "transactions",
        ["merchant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_occurred_at"),
        "transactions",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_status"),
        "transactions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_transaction_type"),
        "transactions",
        ["transaction_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_user_id"),
        "transactions",
        ["user_id"],
        unique=False,
    )

    # 6. Decisions table
    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("request_reference", sa.String(length=128), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("evidence_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_decisions_transaction_id_transactions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_decisions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
    )
    op.create_index(
        op.f("ix_decisions_decision"),
        "decisions",
        ["decision"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decisions_request_reference"),
        "decisions",
        ["request_reference"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decisions_transaction_id"),
        "decisions",
        ["transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decisions_user_id"),
        "decisions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop tables in reverse topological order
    op.drop_index(op.f("ix_decisions_user_id"), table_name="decisions")
    op.drop_index(op.f("ix_decisions_transaction_id"), table_name="decisions")
    op.drop_index(op.f("ix_decisions_request_reference"), table_name="decisions")
    op.drop_index(op.f("ix_decisions_decision"), table_name="decisions")
    op.drop_table("decisions")

    op.drop_index(op.f("ix_transactions_user_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_transaction_type"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_status"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_occurred_at"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_merchant_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_mandate_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_idempotency_key"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_external_reference"), table_name="transactions")
    op.drop_table("transactions")

    op.drop_index(op.f("ix_policies_user_id"), table_name="policies")
    op.drop_index(op.f("ix_policies_status"), table_name="policies")
    op.drop_index(op.f("ix_policies_policy_type"), table_name="policies")
    op.drop_table("policies")

    op.drop_index(op.f("ix_mandates_user_id"), table_name="mandates")
    op.drop_index(op.f("ix_mandates_status"), table_name="mandates")
    op.drop_index(op.f("ix_mandates_merchant_id"), table_name="mandates")
    op.drop_table("mandates")

    op.drop_index(op.f("ix_merchants_status"), table_name="merchants")
    op.drop_index(op.f("ix_merchants_external_reference"), table_name="merchants")
    op.drop_index(op.f("ix_merchants_name"), table_name="merchants")
    op.drop_table("merchants")

    op.drop_index(op.f("ix_users_status"), table_name="users")
    op.drop_index(op.f("ix_users_external_reference"), table_name="users")
    op.drop_table("users")
