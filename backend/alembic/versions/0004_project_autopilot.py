"""piloto automático do projeto

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02 16:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('autopilot', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('autopilot')
