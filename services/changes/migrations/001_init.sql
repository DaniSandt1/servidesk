-- Migración inicial de ms-changes.
-- Se ejecuta dentro de cada schema tenant_*.

-- 1. Solicitudes de cambio
CREATE TABLE IF NOT EXISTS changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(20) NOT NULL UNIQUE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    type VARCHAR(20) NOT NULL,
    risk VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    rollback_plan TEXT,
    planned_start TIMESTAMP,
    planned_end TIMESTAMP,
    requester_id UUID NOT NULL,
    problem_id UUID,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_change_type
        CHECK (type IN (
            'standard', 'normal', 'emergency'
        )),

    CONSTRAINT chk_change_risk
        CHECK (risk IN (
            'low', 'medium', 'high'
        )),

    CONSTRAINT chk_change_status
        CHECK (status IN (
            'draft', 'submitted', 'approved',
            'rejected', 'scheduled',
            'implemented', 'failed'
        )),

    CONSTRAINT chk_change_dates
        CHECK (
            planned_start IS NULL
            OR planned_end IS NULL
            OR planned_end > planned_start
        )
);

-- 2. Aprobaciones CAB
CREATE TABLE IF NOT EXISTS change_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    change_id UUID NOT NULL
        REFERENCES changes(id) ON DELETE CASCADE,
    approver_id UUID NOT NULL,
    decision VARCHAR(10) NOT NULL,
    comment VARCHAR(2000),
    decided_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_approval_decision
        CHECK (decision IN (
            'pending', 'approved', 'rejected'
        ))
);

-- 3. Elementos de configuración afectados
CREATE TABLE IF NOT EXISTS change_cis (
    change_id UUID NOT NULL
        REFERENCES changes(id) ON DELETE CASCADE,
    ci_id UUID NOT NULL,
    new_version VARCHAR(50),

    PRIMARY KEY (change_id, ci_id)
);

-- 4. Tareas asociadas al cambio
CREATE TABLE IF NOT EXISTS change_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    change_id UUID NOT NULL
        REFERENCES changes(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    assignee_id UUID,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. Índices para búsquedas y filtros
CREATE INDEX IF NOT EXISTS idx_changes_status
    ON changes(status);

CREATE INDEX IF NOT EXISTS idx_changes_type
    ON changes(type);

CREATE INDEX IF NOT EXISTS idx_changes_risk
    ON changes(risk);

CREATE INDEX IF NOT EXISTS idx_changes_requester
    ON changes(requester_id);

CREATE INDEX IF NOT EXISTS idx_changes_planned_start
    ON changes(planned_start);

CREATE INDEX IF NOT EXISTS idx_changes_created_at
    ON changes(created_at);

CREATE INDEX IF NOT EXISTS idx_change_approvals_change
    ON change_approvals(change_id);

CREATE INDEX IF NOT EXISTS idx_change_tasks_change
    ON change_tasks(change_id);

