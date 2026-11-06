"""absensi kiosk dan pin

Revision ID: 65bbf9b7c689
Revises: a7c1d9e04b52
Create Date: 2026-10-31 16:57:41.510310

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "65bbf9b7c689"
down_revision: Union[str, Sequence[str], None] = "a7c1d9e04b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attendance", sa.Column("in_kiosk_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "attendance", sa.Column("out_kiosk_id", sa.String(length=36), nullable=True)
    )
    op.create_foreign_key(
        "fk_att_in_kiosk", "attendance", "users", ["in_kiosk_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_att_out_kiosk", "attendance", "users", ["out_kiosk_id"], ["id"]
    )
    op.add_column(
        "users", sa.Column("attendance_pin_hash", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "attendance_pin_failed", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "users",
        sa.Column("attendance_pin_locked_until", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "attendance_pin_locked_until")
    op.drop_column("users", "attendance_pin_failed")
    op.drop_column("users", "attendance_pin_hash")
    op.drop_constraint("fk_att_out_kiosk", "attendance", type_="foreignkey")
    op.drop_constraint("fk_att_in_kiosk", "attendance", type_="foreignkey")
    op.drop_column("attendance", "out_kiosk_id")
    op.drop_column("attendance", "in_kiosk_id")
