-- ─── Users ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username    VARCHAR(100) UNIQUE NOT NULL,
    email       VARCHAR(255) UNIQUE,
    hashed_pw   TEXT NOT NULL,
    role        VARCHAR(50) DEFAULT 'user',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Projects ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    status      VARCHAR(50) DEFAULT 'active',
    owner_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Tasks ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    status          VARCHAR(50) DEFAULT 'pending',
    priority        INTEGER DEFAULT 5,
    assigned_agent  VARCHAR(100),
    parent_task_id  UUID REFERENCES tasks(id) ON DELETE SET NULL,
    retries         INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    result          JSONB,
    error_log       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- ─── Agent Messages (shared graph state history) ──────────────────
CREATE TABLE IF NOT EXISTS agent_messages (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id     UUID REFERENCES tasks(id) ON DELETE CASCADE,
    agent_name  VARCHAR(100) NOT NULL,
    role        VARCHAR(50) NOT NULL,  -- 'human', 'ai', 'tool'
    content     TEXT NOT NULL,
    tool_calls  JSONB,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Episodic Memory ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS episodic_memory (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name  VARCHAR(100) NOT NULL,
    task_id     UUID REFERENCES tasks(id) ON DELETE CASCADE,
    event_type  VARCHAR(100),
    content     TEXT NOT NULL,
    importance  FLOAT DEFAULT 0.5,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Semantic Memory (vector store) ──────────────────────────────
CREATE TABLE IF NOT EXISTS semantic_memory (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name  VARCHAR(100),
    content     TEXT NOT NULL,
    embedding   TEXT,   -- Fallback to TEXT for standard PG compatibility
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Reports ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reports (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id     UUID UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    project_id  VARCHAR(255) DEFAULT 'default',
    title       VARCHAR(255) NOT NULL,
    content     TEXT NOT NULL,
    format      VARCHAR(50) DEFAULT 'markdown',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
