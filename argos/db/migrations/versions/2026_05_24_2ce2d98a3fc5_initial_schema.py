"""Initial schema — all tables for argos.

Revision ID: 2ce2d98a3fc5
Revises:
Create Date: 2026-05-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2ce2d98a3fc5"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(120), nullable=False),
        sa.Column("profile_name", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_leader", sa.Boolean(), nullable=False),
        sa.Column("workspace_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("current_task", sa.Text(), nullable=False),
        sa.Column("runtime_status", sa.String(40), nullable=False),
        sa.Column("interaction_state", sa.String(60), nullable=False),
        sa.Column("orchestration_state", sa.String(60), nullable=False),
        sa.Column("queue_depth", sa.Integer(), nullable=False),
        sa.Column("pending_interaction_json", sa.Text(), nullable=False),
        sa.Column("load", sa.Integer(), nullable=False),
        sa.Column("last_input", sa.Text(), nullable=False),
        sa.Column("last_output", sa.Text(), nullable=False),
        sa.Column("last_output_at", sa.String(40), nullable=False),
        sa.Column("readiness_status", sa.String(60), nullable=False),
        sa.Column("readiness_message", sa.Text(), nullable=False),
        sa.Column("last_active_at", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
        sa.UniqueConstraint("profile_name"),
    )
    op.create_index("ix_agents_agent_id", "agents", ["agent_id"], unique=True)
    op.create_index("ix_agents_profile_name", "agents", ["profile_name"], unique=True)

    op.create_table(
        "user_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_task_id", sa.String(80), nullable=False),
        sa.Column("leader_agent_id", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("delegation_ids_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("dispatch_closed", sa.Boolean(), nullable=False),
        sa.Column("summary_requested_at", sa.String(40), nullable=True),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("review_task_ids_json", sa.Text(), nullable=False),
        sa.Column("blocked_at", sa.String(40), nullable=True),
        sa.Column("block_reason", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_task_id"),
    )
    op.create_index("ix_user_tasks_leader_agent_id", "user_tasks", ["leader_agent_id"])
    op.create_index("ix_user_tasks_status", "user_tasks", ["status"])
    op.create_index("ix_user_tasks_user_task_id", "user_tasks", ["user_task_id"], unique=True)

    op.create_table(
        "delegations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("delegation_id", sa.String(80), nullable=False),
        sa.Column("user_task_id", sa.String(80), nullable=True),
        sa.Column("leader_agent_id", sa.String(120), nullable=False),
        sa.Column("summary_instruction", sa.Text(), nullable=False),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("review_task_id", sa.String(120), nullable=True),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.Column("summarized_at", sa.String(40), nullable=True),
        sa.Column("reviewed_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delegation_id"),
    )
    op.create_index("ix_delegations_delegation_id", "delegations", ["delegation_id"], unique=True)
    op.create_index("ix_delegations_leader_agent_id", "delegations", ["leader_agent_id"])
    op.create_index("ix_delegations_status", "delegations", ["status"])
    op.create_index("ix_delegations_user_task_id", "delegations", ["user_task_id"])

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.String(80), nullable=False),
        sa.Column("delegation_id", sa.String(80), nullable=False),
        sa.Column("worker_agent_id", sa.String(120), nullable=False),
        sa.Column("worker_name", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("message_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(60), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delegation_id", "assignment_id"),
    )
    op.create_index("ix_assignments_assignment_id", "assignments", ["assignment_id"])
    op.create_index("ix_assignments_delegation_id", "assignments", ["delegation_id"])
    op.create_index("ix_assignments_message_id", "assignments", ["message_id"])
    op.create_index("ix_assignments_status", "assignments", ["status"])
    op.create_index("ix_assignments_worker_agent_id", "assignments", ["worker_agent_id"])

    op.create_table(
        "kanban_task_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("local_type", sa.String(40), nullable=False),
        sa.Column("local_id", sa.String(120), nullable=False),
        sa.Column("kanban_task_id", sa.String(120), nullable=False),
        sa.Column("kanban_role", sa.String(40), nullable=False),
        sa.Column("kanban_status", sa.String(60), nullable=False),
        sa.Column("assignee_profile", sa.String(120), nullable=False),
        sa.Column("parent_local_id", sa.String(120), nullable=True),
        sa.Column("last_result", sa.Text(), nullable=False),
        sa.Column("last_summary", sa.Text(), nullable=False),
        sa.Column("summary_created", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kanban_task_id"),
        sa.UniqueConstraint("local_type", "local_id", "kanban_role"),
    )
    op.create_index("ix_kanban_task_links_assignee_profile", "kanban_task_links", ["assignee_profile"])
    op.create_index("ix_kanban_task_links_kanban_role", "kanban_task_links", ["kanban_role"])
    op.create_index("ix_kanban_task_links_kanban_status", "kanban_task_links", ["kanban_status"])
    op.create_index("ix_kanban_task_links_kanban_task_id", "kanban_task_links", ["kanban_task_id"])
    op.create_index("ix_kanban_task_links_local_id", "kanban_task_links", ["local_id"])
    op.create_index("ix_kanban_task_links_local_type", "kanban_task_links", ["local_type"])
    op.create_index("ix_kanban_task_links_parent_local_id", "kanban_task_links", ["parent_local_id"])

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_settings_key", "settings", ["key"], unique=True)

    op.create_table(
        "model_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_model_configs_name", "model_configs", ["name"], unique=True)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(80), nullable=False),
        sa.Column("from_agent_id", sa.String(120), nullable=True),
        sa.Column("from_name", sa.String(200), nullable=False),
        sa.Column("to_agent_id", sa.String(120), nullable=False),
        sa.Column("to_name", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("delegation_id", sa.String(80), nullable=True),
        sa.Column("assignment_id", sa.String(80), nullable=True),
        sa.Column("user_task_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_messages_assignment_id", "messages", ["assignment_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_delegation_id", "messages", ["delegation_id"])
    op.create_index("ix_messages_from_agent_id", "messages", ["from_agent_id"])
    op.create_index("ix_messages_message_id", "messages", ["message_id"], unique=True)
    op.create_index("ix_messages_to_agent_id", "messages", ["to_agent_id"])
    op.create_index("ix_messages_user_task_id", "messages", ["user_task_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("agent_id", sa.String(120), nullable=False),
        sa.Column("task_id", sa.String(80), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_events_agent_id", "events", ["agent_id"])
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_index("ix_events_event_id", "events", ["event_id"], unique=True)
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_task_id", "events", ["task_id"])

    op.create_table(
        "agent_skill_installs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(120), nullable=False),
        sa.Column("resolved_commit_sha", sa.String(120), nullable=False),
        sa.Column("subdir", sa.Text(), nullable=False),
        sa.Column("installed_at", sa.String(40), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_name", "slug"),
    )
    op.create_index("ix_agent_skill_installs_profile_name", "agent_skill_installs", ["profile_name"])

    op.create_table(
        "agent_mcp_servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_name", sa.String(120), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("last_test_status", sa.String(16), nullable=False),
        sa.Column("last_test_at", sa.String(40), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_name", "name"),
    )
    op.create_index("ix_agent_mcp_servers_profile_name", "agent_mcp_servers", ["profile_name"])

    # ── Self-Evolving Learning System tables ──────────────────

    op.create_table(
        "execution_traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(80), nullable=False),
        sa.Column("user_task_id", sa.String(80), nullable=False),
        sa.Column("leader_agent_id", sa.String(120), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("decomposition_json", sa.Text(), nullable=False),
        sa.Column("context_plan_json", sa.Text(), nullable=False),
        sa.Column("allocations_json", sa.Text(), nullable=False),
        sa.Column("decisions_json", sa.Text(), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.Column("quality_json", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.Column("consolidated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id"),
    )
    op.create_index("ix_execution_traces_leader_agent_id", "execution_traces", ["leader_agent_id"])
    op.create_index("ix_execution_traces_trace_id", "execution_traces", ["trace_id"], unique=True)
    op.create_index("ix_execution_traces_user_task_id", "execution_traces", ["user_task_id"])

    op.create_table(
        "memory_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.String(80), nullable=False),
        sa.Column("layer", sa.String(40), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("source_trace_ids_json", sa.Text(), nullable=False),
        sa.Column("consolidation_count", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("project_path", sa.String(500), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.String(40), nullable=True),
        sa.Column("expires_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id"),
    )
    op.create_index("ix_memory_items_layer", "memory_items", ["layer"])
    op.create_index("ix_memory_items_memory_id", "memory_items", ["memory_id"], unique=True)
    op.create_index("ix_memory_items_project_path", "memory_items", ["project_path"])
    op.create_index("ix_memory_items_scope", "memory_items", ["scope"])
    op.create_index("ix_memory_items_type", "memory_items", ["type"])
    op.create_index("ix_memory_items_weight", "memory_items", ["weight"])

    op.create_table(
        "feedback_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.String(80), nullable=False),
        sa.Column("trace_id", sa.String(80), nullable=False),
        sa.Column("assignment_id", sa.String(80), nullable=True),
        sa.Column("signal_type", sa.String(40), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id"),
    )
    op.create_index("ix_feedback_signals_assignment_id", "feedback_signals", ["assignment_id"])
    op.create_index("ix_feedback_signals_signal_id", "feedback_signals", ["signal_id"], unique=True)
    op.create_index("ix_feedback_signals_signal_type", "feedback_signals", ["signal_type"])
    op.create_index("ix_feedback_signals_trace_id", "feedback_signals", ["trace_id"])

    op.create_table(
        "learning_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suggestion_id", sa.String(80), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("applied_at", sa.String(40), nullable=True),
        sa.Column("seen_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suggestion_id"),
    )
    op.create_index("ix_learning_suggestions_suggestion_id", "learning_suggestions", ["suggestion_id"], unique=True)
    op.create_index("ix_learning_suggestions_type", "learning_suggestions", ["type"])

    op.create_table(
        "ab_experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("control_label", sa.String(100), nullable=False),
        sa.Column("treatment_label", sa.String(100), nullable=False),
        sa.Column("filter_expr", sa.String(500), nullable=True),
        sa.Column("control_json", sa.Text(), nullable=False),
        sa.Column("treatment_json", sa.Text(), nullable=False),
        sa.Column("concluded", sa.Boolean(), nullable=False),
        sa.Column("winner", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("deleted_at", sa.String(40), nullable=True),
        sa.Column("db_created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("db_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id"),
    )
    op.create_index("ix_ab_experiments_experiment_id", "ab_experiments", ["experiment_id"], unique=True)


def downgrade() -> None:
    op.drop_table("ab_experiments")
    op.drop_table("learning_suggestions")
    op.drop_table("feedback_signals")
    op.drop_table("memory_items")
    op.drop_table("execution_traces")
    op.drop_table("agent_mcp_servers")
    op.drop_table("agent_skill_installs")
    op.drop_table("events")
    op.drop_table("messages")
    op.drop_table("model_configs")
    op.drop_table("settings")
    op.drop_table("kanban_task_links")
    op.drop_table("assignments")
    op.drop_table("delegations")
    op.drop_table("user_tasks")
    op.drop_table("agents")
