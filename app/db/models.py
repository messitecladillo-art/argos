from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .session import Base


class TimestampMixin:
    created_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    db_created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    db_updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentRecord(TimestampMixin, Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    profile_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False)
    workspace_path: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="idle")
    current_task: Mapped[str] = mapped_column(Text, default="空闲")
    runtime_status: Mapped[str] = mapped_column(String(40), default="stopped")
    interaction_state: Mapped[str] = mapped_column(String(60), default="idle")
    orchestration_state: Mapped[str] = mapped_column(String(60), default="none")
    queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    pending_interaction_json: Mapped[str] = mapped_column(Text, default="")
    load: Mapped[int] = mapped_column(Integer, default=0)
    last_input: Mapped[str] = mapped_column(Text, default="")
    last_output: Mapped[str] = mapped_column(Text, default="")
    last_output_at: Mapped[str] = mapped_column(String(40), default="")
    readiness_status: Mapped[str] = mapped_column(String(60), default="ready")
    readiness_message: Mapped[str] = mapped_column(Text, default="")
    last_active_at: Mapped[str] = mapped_column(String(40), default="")


class UserTaskRecord(TimestampMixin, Base):
    __tablename__ = "user_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_task_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    leader_agent_id: Mapped[str] = mapped_column(String(120), index=True)
    content: Mapped[str] = mapped_column(Text)
    delegation_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(60), index=True)
    dispatch_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_requested_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class DelegationRecord(TimestampMixin, Base):
    __tablename__ = "delegations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delegation_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    leader_agent_id: Mapped[str] = mapped_column(String(120), index=True)
    summary_instruction: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(60), index=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summarized_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AssignmentRecord(TimestampMixin, Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("delegation_id", "assignment_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(80), index=True)
    delegation_id: Mapped[str] = mapped_column(String(80), index=True)
    worker_agent_id: Mapped[str] = mapped_column(String(120), index=True)
    worker_name: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(60), index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    from_agent_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    from_name: Mapped[str] = mapped_column(String(200), default="")
    to_agent_id: Mapped[str] = mapped_column(String(120), index=True)
    to_name: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text)
    delegation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    assignment_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    user_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    agent_id: Mapped[str] = mapped_column(String(120), index=True)
    task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40), index=True)


class AgentSkillInstallRecord(TimestampMixin, Base):
    __tablename__ = "agent_skill_installs"
    __table_args__ = (UniqueConstraint("profile_name", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(120), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(20), default="git")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str] = mapped_column(String(120), default="")
    resolved_commit_sha: Mapped[str] = mapped_column(String(120), default="")
    subdir: Mapped[str] = mapped_column(Text, default="")
    installed_at: Mapped[str] = mapped_column(String(40), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
