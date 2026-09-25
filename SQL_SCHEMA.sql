-- Evalio database schema (PostgreSQL)
-- The API creates and migrates this automatically on startup (db.init_db);
-- this file is a reference / for manual provisioning.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_type') THEN
        CREATE TYPE project_type AS ENUM (
            'VANILLA_JS', 'REACT', 'NEXT_JS', 'VUE', 'NUXT', 'ANGULAR', 'SVELTE', 'SVELTEKIT',
            'ASTRO', 'REMIX', 'TAILWIND', 'NODE_EXPRESS', 'FASTAPI', 'DJANGO', 'SPRING_BOOT',
            'GIN', 'RAILS', 'LARAVEL', 'ACTIX', 'SWIFT_UI', 'KOTLIN_JETPACK', 'REACT_NATIVE',
            'EXPO', 'FLUTTER', 'DOTNET_MAUI', 'IONIC', 'NATIVESCRIPT', 'OTHER'
        );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS hackathons (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    theme TEXT DEFAULT '',                    -- comma-separated themes
    technologies TEXT DEFAULT '',             -- comma-separated expected technologies
    is_allowed BOOLEAN DEFAULT FALSE,         -- submissions open
    criteria TEXT DEFAULT '',                 -- comma-separated criteria names (legacy/readable)
    criteria_config JSONB DEFAULT NULL,       -- [{name, weight, judge, description}]
    starts_at TIMESTAMPTZ DEFAULT NULL,
    deadline TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(255) UNIQUE NOT NULL,  -- UUID
    hackathon_id INTEGER REFERENCES hackathons(id) ON DELETE SET NULL,
    name TEXT DEFAULT '',
    short_description TEXT DEFAULT '',
    long_description TEXT DEFAULT '',
    github_link TEXT DEFAULT '',
    demo_link TEXT DEFAULT NULL,
    theme TEXT DEFAULT '',
    project_type project_type DEFAULT 'OTHER',
    is_reviewed BOOLEAN DEFAULT FALSE,
    -- evaluation state
    status VARCHAR(20) DEFAULT 'queued',      -- queued | running | completed | partial | failed | legacy
    pipeline JSONB DEFAULT '{}'::jsonb,       -- per-stage status: ingest, code, market, product, verdict
    last_error TEXT DEFAULT NULL,
    -- evaluation results
    repo_snapshot JSONB DEFAULT NULL,         -- measured repo facts: languages, stack, signals, git history
    code_agent_analysis JSONB DEFAULT NULL,   -- Code Judge report
    market_agent_analysis JSONB DEFAULT NULL, -- Market Judge report (with cited sources)
    product_agent_analysis JSONB DEFAULT NULL,-- Product Judge report (claims, demo, originality)
    verdict JSONB DEFAULT NULL,               -- Head Judge verdict
    criteria_scores JSONB DEFAULT '[]'::jsonb,
    flags JSONB DEFAULT '[]'::jsonb,          -- integrity / rule flags
    overall_score NUMERIC(5,4) DEFAULT NULL,  -- weighted final score on a 0..1 scale (API shows 0..10)
    score_explanation TEXT DEFAULT '',
    evaluated_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- One row per scored criterion (analytics / reporting)
CREATE TABLE IF NOT EXISTS evaluations (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(255) REFERENCES projects(project_id) ON DELETE CASCADE,
    criteria_name VARCHAR(255) NOT NULL,
    score DECIMAL(3,2) DEFAULT 0.00,          -- 0..1
    remarks TEXT DEFAULT '',
    agent_type VARCHAR(50) DEFAULT 'code',    -- code | market | product
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Durable evaluation queue (claimed with FOR UPDATE SKIP LOCKED)
CREATE TABLE IF NOT EXISTS evaluation_jobs (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(255) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'queued', -- queued | running | done | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ DEFAULT NULL,
    heartbeat_at TIMESTAMPTZ DEFAULT NULL,
    finished_at TIMESTAMPTZ DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_hackathon_id ON projects(hackathon_id);
CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(hackathon_id, overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_evaluations_project_id ON evaluations(project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON evaluation_jobs(status, created_at);
