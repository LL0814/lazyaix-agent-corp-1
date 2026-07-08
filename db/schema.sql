
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id VARCHAR(128) PRIMARY KEY,
    trace_id VARCHAR(128) NOT NULL,
    parent_workflow_id VARCHAR(128) NULL,
    user_input TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    final_result TEXT NULL,
    error_info JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id VARCHAR(128) PRIMARY KEY,
    workflow_id VARCHAR(128) NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    parent_task_id VARCHAR(128) NULL,
    task_type VARCHAR(64) NOT NULL,
    target_capability VARCHAR(64) NOT NULL,
    target_agent VARCHAR(128) NULL,
    instructions TEXT NOT NULL,
    input JSONB NULL,
    input_refs JSONB NULL,
    required_for_completion BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    result JSONB NULL,
    error_info JSONB NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 2,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    workflow_id VARCHAR(128) NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    task_id VARCHAR(128) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id VARCHAR(128) NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    dependency_type VARCHAR(32) NOT NULL DEFAULT 'finish_to_start',
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS event_store (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL UNIQUE,
    trace_id VARCHAR(128) NOT NULL,
    parent_event_id VARCHAR(128) NULL,
    aggregate_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(128) NOT NULL,
    target_agent VARCHAR(128) NULL,
    target_capability VARCHAR(64) NULL,
    workflow_id VARCHAR(128) NULL,
    task_id VARCHAR(128) NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL UNIQUE,
    aggregate_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    topic VARCHAR(256) NOT NULL,
    message_key VARCHAR(256) NULL,
    payload JSONB NOT NULL,
    headers JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ NULL,
    error_info TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox_events(status, next_retry_at)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS processed_events (
    event_id VARCHAR(128) PRIMARY KEY,
    workflow_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NULL,
    event_type VARCHAR(128) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dlq (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL,
    trace_id VARCHAR(128) NULL,
    workflow_id VARCHAR(128) NULL,
    task_id VARCHAR(128) NULL,
    reason VARCHAR(256) NOT NULL,
    error_info JSONB NULL,
    payload JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retried_at TIMESTAMPTZ NULL
);
