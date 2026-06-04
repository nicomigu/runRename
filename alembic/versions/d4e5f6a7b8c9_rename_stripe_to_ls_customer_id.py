"""rename stripe_customer_id back to lemon_squeezy_customer_id

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'stripe_customer_id', new_column_name='lemon_squeezy_customer_id')


def downgrade() -> None:
    op.alter_column('users', 'lemon_squeezy_customer_id', new_column_name='stripe_customer_id')
