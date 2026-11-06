"""jadwal buka tutup outlet

Revision ID: ddbf430bd4df
Revises: 65bbf9b7c689
Create Date: 2026-11-03 12:36:50.383749

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ddbf430bd4df"
down_revision: Union[str, Sequence[str], None] = "65bbf9b7c689"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outlet_hours",
        sa.Column("outlet_id", sa.String(length=36), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("open_min", sa.Integer(), nullable=True),
        sa.Column("close_min", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["outlet_id"], ["outlets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("outlet_id", "weekday"),
    )
    op.add_column(
        "attendance", sa.Column("sched_in_at", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "attendance", sa.Column("sched_out_at", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "attendance", sa.Column("sched_grace_min", sa.Integer(), nullable=True)
    )
    op.add_column(
        "outlets",
        sa.Column(
            "timezone",
            sa.String(length=40),
            server_default="Asia/Jakarta",
            nullable=False,
        ),
    )
    op.add_column(
        "outlets",
        sa.Column("staff_lead_min", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "outlets",
        sa.Column("staff_tail_min", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "outlets",
        sa.Column("grace_min", sa.Integer(), server_default="5", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("outlets", "grace_min")
    op.drop_column("outlets", "staff_tail_min")
    op.drop_column("outlets", "staff_lead_min")
    op.drop_column("outlets", "timezone")
    op.drop_column("attendance", "sched_grace_min")
    op.drop_column("attendance", "sched_out_at")
    op.drop_column("attendance", "sched_in_at")
    op.drop_table("outlet_hours")
