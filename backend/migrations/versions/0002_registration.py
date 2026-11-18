"""Durable private ledger operations; no approval or ownership workflow."""
from alembic import op
import sqlalchemy as sa
revision='0002_registration'
down_revision='0001_m2'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('ledger_operations',
        sa.Column('operation_id',sa.String(36),primary_key=True),
        sa.Column('property_id',sa.String(36),nullable=False,unique=True),
        sa.Column('request_digest',sa.String(64),nullable=False),
        sa.Column('command_json',sa.Text(),nullable=False),
        sa.Column('state',sa.String(32),nullable=False),
        sa.Column('artifact_json',sa.Text()),sa.Column('transaction_id',sa.String(128)),sa.Column('signer',sa.String(128)),
        sa.Column('channel',sa.String(32),nullable=False),sa.Column('chaincode',sa.String(32),nullable=False),
        sa.Column('validation_code',sa.String(32)),sa.Column('block_number',sa.String(32)),
        sa.CheckConstraint("state IN ('CREATED','PREPARED','SUBMISSION_PENDING','SUBMITTED','COMMITTED_VALID','COMMITTED_INVALID','UNKNOWN')",name='ck_ledger_operation_state'))

def downgrade():
    op.drop_table('ledger_operations')
