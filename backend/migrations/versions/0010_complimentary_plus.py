"""`accounts.complimentary_plus`: the paid plan without Stripe.

Owner decision 2026-11-14 (docs/backend/billing.md, "Complimentary Plus"):
an account with the flag set is on the paid plan ("Plus") everywhere the
code asks (paid media limits, `PAID_RUNS_PER_DAY` included runs, saved
history), whether or not Stripe is configured, and is never billed: no
Stripe customer, no extra runs past the included ones, no ledger row, no
meter event. A live paying subscription on the same account wins for
billing. The flag is set and cleared only by hand in SQL by the owner;
there is no API that writes it.

`BOOLEAN NOT NULL DEFAULT false` (server default), so every existing and
new account reads false without the code writing it. On Postgres 11+ an
`ADD COLUMN` with a constant default changes the catalog only (no table
rewrite). The RLS and the backend role's policy and grants already on
`accounts` cover the new column; nothing new is granted. Runs on SQLite too
(tests): the adapters read the column, so a migrated SQLite database must
have it.

Apply BEFORE deploying the code that reads it: every `select(accounts)`
names the column, so without it every signed-in request fails on Postgres
(column does not exist).

Downgrade drops the column: every complimentary account goes back to the
free plan (its saved runs stay, readable and deletable).

Revision ID: 0010_complimentary_plus
Revises: 0009_default_workspace_fk
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_complimentary_plus"
down_revision = "0009_default_workspace_fk"
branch_labels = None
depends_on = None

COLUMN = "complimentary_plus"


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # Batch mode: a plain ALTER on Postgres, the copy-and-move SQLite needs.
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column(COLUMN)
