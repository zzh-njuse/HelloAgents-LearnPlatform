"""expand practice item types for integrated learning tools

Revision ID: 0022
Revises: 0021
"""

from alembic import op


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_practice_items_item_type", "practice_items", type_="check")
    op.create_check_constraint(
        "ck_practice_items_item_type",
        "practice_items",
        "item_type IN ('single_choice', 'short_answer', 'coding', 'scientific')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_practice_items_item_type", "practice_items", type_="check")
    op.create_check_constraint(
        "ck_practice_items_item_type",
        "practice_items",
        "item_type IN ('single_choice', 'short_answer')",
    )
