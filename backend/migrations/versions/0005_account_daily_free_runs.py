"""Daily account free runs: widen `period` to varchar(10).

Owner decision 2026-11-14: a signed-in account on the free plan gets
`FREE_RUNS_PER_ACCOUNT_DAILY` runs per UTC day (it was 10 per calendar
month). Its counter rows in `account_free_runs` and its holds in
`account_free_run_holds` are now keyed by the UTC day, "YYYY-MM-DD" (10
characters), which does not fit 0003's varchar(7). The paid plan's included
runs keep their monthly "YYYY-MM" key on the same table. The two key
formats never compare equal, so the free and the paid counter of one
account are always different rows.

Existing monthly rows written by free accounts before this change are left
alone: the free plan simply stops reading them (the paid plan still reads
the current month's row, so a free account that upgrades in the month of
this deploy sees the runs it used that month under the old rule; from the
next month on that cannot happen).

Postgres: `ALTER COLUMN ... TYPE varchar(10)` on a varchar column is a
binary-coercible widening, so it changes the catalog only (no table rewrite,
no index rebuild) under a brief ACCESS EXCLUSIVE lock. Row level security,
the `videolens_api_all` policies (`USING (true)`, they name no column) and
the grants are properties of the table and survive the ALTER unchanged.
No role check is needed: nothing new is created.

Downgrade first DELETES every daily row (and daily hold) on both tables,
because a 10-character key does not fit varchar(7); the monthly rows stay.

Apply BEFORE deploying the code that writes daily keys: without it every
signed-in free run fails at admission on Postgres (value too long).

Revision ID: 0005_account_daily_free_runs
Revises: 0004_billing
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_account_daily_free_runs"
down_revision = "0004_billing"
branch_labels = None
depends_on = None

TABLES = ("account_free_runs", "account_free_run_holds")


def _alter(width_from: int, width_to: int) -> None:
    for table in TABLES:
        # Batch mode is a plain ALTER on Postgres and the copy-and-move
        # SQLite needs (it cannot ALTER a column's type).
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "period", existing_type=sa.String(width_from), type_=sa.String(width_to), existing_nullable=False
            )


def upgrade() -> None:
    _alter(7, 10)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DELETE FROM {table} WHERE length(period) > 7")
    _alter(10, 7)
