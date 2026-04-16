-- =============================================================================
-- RAF Intelligence — Migration 024: AI / Coder Action Audit Log
-- =============================================================================
-- Creates the `ai_audit_log` table referenced by
-- backend/app/services/audit.py::log_event. This is the single source of truth
-- for AI + coder decision audit events (LLM requests/responses, candidate
-- creations, coder accept/reject decisions, pipeline config changes).
--
-- Distinct from `audit_log` (HTTP/PHI access) and `audit_logger` (HIPAA reads).
-- See audit.py module docstring for the canonical action taxonomy.
--
-- Idempotent; safe to re-run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ai_audit_log (
    id            BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    tenant_id     VARCHAR(64)   NOT NULL DEFAULT 'default',
    actor_type    VARCHAR(16)   NOT NULL,      -- 'system' | 'user'
    actor_id      VARCHAR(128),                 -- user email, service name, etc.
    action        VARCHAR(64)   NOT NULL,       -- e.g. 'llm.request', 'coder.decision.accept'
    target_type   VARCHAR(64),                  -- e.g. 'llm', 'candidate', 'suspect'
    target_id     VARCHAR(128),                 -- stringified ID or model name
    `before`      JSON,                         -- prior state (nullable)
    `after`       JSON,                         -- new state / response (nullable)
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_aial_tenant_created (tenant_id, created_at),
    INDEX idx_aial_action_created (action, created_at),
    INDEX idx_aial_target (target_type, target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
