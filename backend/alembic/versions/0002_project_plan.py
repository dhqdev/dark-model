"""plano de produção do projeto (teto por vídeo)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01 15:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.add_column(sa.Column('plan', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch:
        batch.drop_column('plan')
