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
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    max_rounds: Mapped[int] = mapped_column(Integer, default=10)
    review_task_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    blocked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    block_reason: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class DelegationRecord(TimestampMixin, Base):
    __tablename__ = "delegations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delegation_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    leader_agent_id: Mapped[str] = mapped_column(String(120), index=True)
    summary_instruction: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(60), index=True)
    round_number: Mapped[int] = mapped_column("round", Integer, default=1)
    review_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summarized_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


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


class KanbanTaskLinkRecord(TimestampMixin, Base):
    __tablename__ = "kanban_task_links"
    __table_args__ = (
        UniqueConstraint("local_type", "local_id", "kanban_role"),
        UniqueConstraint("kanban_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    local_type: Mapped[str] = mapped_column(String(40), index=True)
    local_id: Mapped[str] = mapped_column(String(120), index=True)
    kanban_task_id: Mapped[str] = mapped_column(String(120), index=True)
    kanban_role: Mapped[str] = mapped_column(String(40), index=True)
    kanban_status: Mapped[str] = mapped_column(String(60), default="", index=True)
    assignee_profile: Mapped[str] = mapped_column(String(120), default="", index=True)
    parent_local_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    last_result: Mapped[str] = mapped_column(Text, default="")
    last_summary: Mapped[str] = mapped_column(Text, default="")
    summary_created: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class SettingRecord(TimestampMixin, Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ModelConfigRecord(TimestampMixin, Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500))
    api_key: Mapped[str] = mapped_column(Text, default="")


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


class AgentMcpServerRecord(TimestampMixin, Base):
    __tablename__ = "agent_mcp_servers"
    __table_args__ = (UniqueConstraint("profile_name", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(80))
    transport: Mapped[str] = mapped_column(String(16))
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    description: Mapped[str] = mapped_column(Text, default="")
    managed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str] = mapped_column(String(16), default="")
    last_test_at: Mapped[str] = mapped_column(String(40), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
