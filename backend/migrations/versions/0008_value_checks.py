"""Check constraints on the fixed-value text columns.

Each allowed list is what the code writes today:

- `workspace_members.role`: `WorkspaceRole` (domain/entities.py), "owner" |
  "member". Only `SqlAccountDirectory._create_default_workspace` writes it
  ("owner"); 0001's server default is "member".
- `billing_extra_runs.state`: `billing_store.HELD, DUE, REPORTED, VOID`,
  "held" | "due" | "reported" | "void".
- `saved_runs.completeness`: `AnalysisCompleteness` (domain/entities.py),
  "full" | "captions_only", written from `run.completeness.value`.
- `period`, format only:
  - `account_free_runs`, `account_free_run_holds`: "YYYY-MM-DD" (the daily
    counter every writer uses since 2026-11-14, `policies.period_key` with
    `FreeRunPeriod.DAY`) or "YYYY-MM" (`FreeRunPeriod.MONTH`, still a valid
    key, and the monthly rows written before 0005, which are kept).
  - `billing_extra_runs`: "YYYY-MM" only (`BillingPlans.extra_runs_period`,
    the UTC month, whatever the included runs' period is).

Deliberately NOT constrained: `billing_accounts.status` and
`billing_accounts.interval`. Both are copied verbatim from the Stripe
subscription by the webhook (`StripeBillingGateway._snapshot`: `status` is
`str(sub.status or "")`, so it can even be ""; `interval` is the base price's
`recurring.interval`, which Stripe also allows as "day" or "week" if a price
is changed in the dashboard). A status or interval Stripe adds or the code
does not list would make the database reject the webhook's write, the
account would stay on its old state, and Stripe would retry for days. The
readers already treat unknown values safely (`subscription_is_live`, and the
API's `interval` filter to "month" | "year").

Postgres only. `ADD CONSTRAINT ... CHECK` scans the table to validate the
existing rows under an ACCESS EXCLUSIVE lock; the tables are small. A row
that violates a constraint fails the migration (and, applied in its
transaction, nothing changes): check first (the queries are in
docs/backend/auth.md, "Storage"). The `~` regular expressions are
Postgres-only, which is also why SQLite (tests only) is skipped: its test
schema comes from `schema.py`, which declares the same constraints (the
`period` ones for Postgres only). RLS, policies and grants are untouched; no
grants are needed for a constraint.

Downgrade drops the six constraints.

Revision ID: 0008_value_checks
Revises: 0007_identity_cascades
Create Date: 2026-11-14
"""

from alembic import op

revision = "0008_value_checks"
down_revision = "0007_identity_cascades"
branch_labels = None
depends_on = None

WORKSPACE_ROLES = ("owner", "member")
EXTRA_RUN_STATES = ("held", "due", "reported", "void")
COMPLETENESS = ("full", "captions_only")

DAY_OR_MONTH = "^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$"
MONTH = "^[0-9]{4}-[0-9]{2}$"


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


# (constraint name, table, condition)
CHECKS = (
    ("ck_workspace_members_role", "workspace_members", _one_of("role", WORKSPACE_ROLES)),
    ("ck_billing_extra_runs_state", "billing_extra_runs", _one_of("state", EXTRA_RUN_STATES)),
    ("ck_saved_runs_completeness", "saved_runs", _one_of("completeness", COMPLETENESS)),
    ("ck_account_free_runs_period", "account_free_runs", f"period ~ '{DAY_OR_MONTH}'"),
    ("ck_account_free_run_holds_period", "account_free_run_holds", f"period ~ '{DAY_OR_MONTH}'"),
    ("ck_billing_extra_runs_period", "billing_extra_runs", f"period ~ '{MONTH}'"),
)


def _postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _postgres():
        return
    for name, table, condition in CHECKS:
        op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    if not _postgres():
        return
    for name, table, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
