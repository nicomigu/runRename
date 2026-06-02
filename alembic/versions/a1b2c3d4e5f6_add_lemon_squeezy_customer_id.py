"""add lemon_squeezy_customer_id to users

Revision ID: a1b2c3d4e5f6
Revises: 602accf8adde
Create Date: 2026-06-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '602accf8adde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('lemon_squeezy_customer_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'lemon_squeezy_customer_id')
