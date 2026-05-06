-- =============================================================================
-- RAF Intelligence — Knowledge Graph: kg_query_log
-- =============================================================================
-- Telemetry table for the unified KG query service. Every public entry-point
-- on app.services.knowledge_graph.kg_lookup_service writes one row per call
-- so we can monitor latency, cache effectiveness, and query mix.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS). Safe to re-run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS kg_query_log (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    query_type    VARCHAR(80)     NOT NULL,
    params_json   JSON,
    duration_ms   INT UNSIGNED,
    result_count  INT UNSIGNED,
    cached        TINYINT(1)      DEFAULT 0,
    created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_type_time (query_type, created_at)
) ENGINE=InnoDB CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
