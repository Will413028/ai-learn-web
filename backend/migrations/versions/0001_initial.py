"""Initial relational and vector schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("principals", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("kind", sa.String(16), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True)),
                    sa.Column("claimed_by", sa.String(36), sa.ForeignKey("principals.id")))
    op.create_table("users", sa.Column("id", sa.String(36), sa.ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("email", sa.String(320), nullable=False, unique=True),
                    sa.Column("password_hash", sa.String(256), nullable=False),
                    sa.Column("nickname", sa.String(80), nullable=False),
                    sa.Column("avatar_url", sa.String(2000), nullable=False),
                    sa.Column("experience", sa.Integer, nullable=False))
    op.create_table("auth_sessions", sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("principal_id", sa.String(36), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("rate_buckets", sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("hits", sa.Integer, nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("quizzes", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("owner_id", sa.String(36), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("topic", sa.String(12000), nullable=False),
                    sa.Column("questions", postgresql.JSONB, nullable=False),
                    sa.Column("source", postgresql.JSONB, nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("experience_awarded", sa.Integer, nullable=False))
    op.create_table("answers", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("quiz_id", sa.String(36), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("question_id", sa.String(36), nullable=False),
                    sa.Column("data", postgresql.JSONB, nullable=False),
                    sa.UniqueConstraint("quiz_id", "question_id"))
    op.create_table("reports", sa.Column("quiz_id", sa.String(36), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("narrative", postgresql.JSONB, nullable=False))
    op.create_table("jobs", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("owner_id", sa.String(36), sa.ForeignKey("principals.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("request_key", sa.String(100), nullable=False),
                    sa.Column("payload_hash", sa.String(64), nullable=False),
                    sa.Column("payload", postgresql.JSONB, nullable=False),
                    sa.Column("kind", sa.String(16), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("version", sa.Integer, nullable=False),
                    sa.Column("lease_until", sa.DateTime(timezone=True)),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("result_id", sa.String(36)), sa.Column("error", sa.String(500)),
                    sa.Column("retry_of", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
                    sa.UniqueConstraint("owner_id", "request_key"))
    op.create_table("documents", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("filename", sa.String(255), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("size", sa.Integer, nullable=False),
                    sa.Column("chunk_count", sa.Integer, nullable=False),
                    sa.Column("embedding_model", sa.String(100), nullable=False),
                    sa.Column("error", sa.String(500)),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("chunks", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("position", sa.Integer, nullable=False),
                    sa.Column("text", sa.String(12000), nullable=False),
                    sa.Column("embedding", Vector(), nullable=False),
                    sa.Column("model", sa.String(100), nullable=False),
                    sa.Column("dimension", sa.Integer, nullable=False),
                    sa.UniqueConstraint("document_id", "position"),
                    sa.CheckConstraint("vector_dims(embedding) = dimension", name="chunk_vector_dimension"))
    op.create_table("assets", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("quiz_id", sa.String(36), sa.ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("request_key", sa.String(100), nullable=False),
                    sa.Column("prompt", sa.String(4000), nullable=False),
                    sa.Column("status", sa.String(16), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("error", sa.String(500)), sa.Column("charged", sa.Boolean, nullable=False),
                    sa.UniqueConstraint("owner_id", "request_key"))
    for table, columns in {
        "auth_sessions": ["principal_id", "expires_at"], "rate_buckets": ["expires_at"],
        "quizzes": ["owner_id", "created_at"], "answers": ["quiz_id"],
        "jobs": ["owner_id", "status", "lease_until"], "documents": ["owner_id"],
        "chunks": ["document_id"], "assets": ["owner_id", "quiz_id", "created_at"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in ["assets", "chunks", "documents", "jobs", "reports", "answers", "quizzes", "rate_buckets", "auth_sessions", "users", "principals"]:
        op.drop_table(table)
