"""master role dinamis

Revision ID: a7c1d9e04b52
Revises: 2efbf16d30b2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1d9e04b52"
down_revision: Union[str, Sequence[str], None] = "2efbf16d30b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("key", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_staff", sa.Boolean, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_key",
            sa.String(20),
            sa.ForeignKey("roles.key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", sa.String(60), primary_key=True),
    )
    # Peran bawaan di-seed otomatis saat API start (seed_system_roles, idempoten).


def downgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_table("roles")
