"""Preserve request namespaces when guest job ownership is transferred."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("request_scope_id", UUID(as_uuid=False)))
    op.execute("UPDATE jobs SET request_scope_id = owner_id")
    op.alter_column("jobs", "request_scope_id", nullable=False)
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("jobs"):
        if constraint["column_names"] == ["owner_id", "request_key"]:
            op.drop_constraint(constraint["name"], "jobs", type_="unique")
    op.create_unique_constraint("jobs_request_scope_key", "jobs", ["request_scope_id", "request_key"])


def downgrade() -> None:
    duplicates = op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM jobs GROUP BY owner_id, request_key HAVING count(*) > 1)"))
    if duplicates:
        raise RuntimeError("Cannot restore owner-key uniqueness after colliding guest transfers")
    op.drop_constraint("jobs_request_scope_key", "jobs", type_="unique")
    op.create_unique_constraint("jobs_owner_id_request_key_key", "jobs", ["owner_id", "request_key"])
    op.drop_column("jobs", "request_scope_id")
