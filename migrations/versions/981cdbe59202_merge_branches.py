"""merge_branches

Revision ID: 981cdbe59202
Revises: 004_source_sort_order, fd3a4370ed78
Create Date: 2026-01-29 12:54:09.451163

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '981cdbe59202'
down_revision: Union[str, None] = ('004_source_sort_order', 'fd3a4370ed78')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
