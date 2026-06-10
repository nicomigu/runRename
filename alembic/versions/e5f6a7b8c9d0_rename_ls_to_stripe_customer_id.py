"""rename lemon_squeezy_customer_id to stripe_customer_id

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'lemon_squeezy_customer_id', new_column_name='stripe_customer_id')


def downgrade() -> None:
    op.alter_column('users', 'stripe_customer_id', new_column_name='lemon_squeezy_customer_id')
