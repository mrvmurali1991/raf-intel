-- HIPAA 164.312(b) — Dedicated PHI access audit trail
-- Separate from general audit_log for compliance reporting and retention policies.

CREATE TABLE IF NOT EXISTS phi_access_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    tenant_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,  -- READ, CREATE, UPDATE, DELETE, EXPORT, CALCULATE
    resource_type VARCHAR(50) NOT NULL,  -- patient, encounter, diagnosis, raf_score, submission
    resource_id VARCHAR(100),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    request_path VARCHAR(500),
    request_method VARCHAR(10),
    status_code INT,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_phi_tenant (tenant_id),
    INDEX idx_phi_user (user_id),
    INDEX idx_phi_resource (resource_type, resource_id),
    INDEX idx_phi_accessed (accessed_at),
    INDEX idx_phi_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
