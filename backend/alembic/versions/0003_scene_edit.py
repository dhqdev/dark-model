"""edição das cenas: transição, efeito sonoro e texto na tela

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('scenes') as batch:
        batch.add_column(sa.Column('transition', sa.String(length=16), server_default='dissolve', nullable=False))
        batch.add_column(sa.Column('sfx', sa.String(length=16), server_default='none', nullable=False))
        batch.add_column(sa.Column('overlay_text', sa.String(length=120), server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('scenes') as batch:
        batch.drop_column('overlay_text')
        batch.drop_column('sfx')
        batch.drop_column('transition')
