"""Use PostgreSQL UUID for resource identities while preserving API strings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

IDENTITIES = {
    "principals": ["id", "claimed_by"], "users": ["id"], "auth_sessions": ["principal_id"],
    "quizzes": ["id", "owner_id"], "answers": ["id", "quiz_id"], "reports": ["quiz_id"],
    "jobs": ["id", "owner_id", "retry_of", "result_id"], "documents": ["id", "owner_id"],
    "chunks": ["id", "document_id"], "assets": ["id", "owner_id", "quiz_id"],
}


def convert(to_uuid: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    keys = [(table, key) for table in IDENTITIES for key in inspector.get_foreign_keys(table)]
    for table, key in keys:
        op.drop_constraint(key["name"], table, type_="foreignkey")
    for table, columns in IDENTITIES.items():
        for column in columns:
            op.alter_column(table, column, type_=UUID(as_uuid=False) if to_uuid else sa.String(36),
                            postgresql_using=f'"{column}"::{"uuid" if to_uuid else "varchar(36)"}')
    for table, key in keys:
        op.create_foreign_key(key["name"], table, key["referred_table"],
                              key["constrained_columns"], key["referred_columns"], **key["options"])


def upgrade() -> None:
    convert(True)


def downgrade() -> None:
    convert(False)
