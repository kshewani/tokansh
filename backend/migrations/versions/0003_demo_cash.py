"""Add demo cash only; never backfill credits for existing financing records."""
from alembic import op
import sqlalchemy as sa

revision = '0003_demo_cash'
down_revision = '0002_registration'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('demo_cash_accounts',
        sa.Column('investor_id', sa.String(36), primary_key=True),
        sa.Column('balance_minor', sa.BigInteger(), nullable=False),
        sa.CheckConstraint('balance_minor >= 0 AND balance_minor <= 9007199254740991', name='ck_demo_cash_balance'))
    op.create_table('demo_cash_entries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('investor_id', sa.String(36), sa.ForeignKey('demo_cash_accounts.investor_id'), nullable=False),
        sa.Column('loan_id', sa.String(36), sa.ForeignKey('application_operations.id'), nullable=True),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('balance_after_minor', sa.BigInteger(), nullable=False),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.UniqueConstraint('investor_id', 'idempotency_key', name='uq_demo_cash_key'),
        sa.UniqueConstraint('loan_id', 'kind', name='uq_demo_cash_loan_kind'),
        sa.CheckConstraint('amount_minor > 0 AND amount_minor <= 9007199254740991', name='ck_demo_cash_amount'),
        sa.CheckConstraint('balance_after_minor >= 0 AND balance_after_minor <= 9007199254740991', name='ck_demo_cash_after'),
        sa.CheckConstraint("kind IN ('DEMO_FUNDS','WITHDRAWAL','DISBURSEMENT','REPAYMENT')", name='ck_demo_cash_kind'))
    op.create_index('ix_demo_cash_entries_investor_id', 'demo_cash_entries', ['investor_id'])


def downgrade():
    op.drop_table('demo_cash_entries')
    op.drop_table('demo_cash_accounts')
