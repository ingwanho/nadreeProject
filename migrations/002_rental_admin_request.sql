CREATE TABLE MSP_RENTAL_ADMIN_REQUEST (
    request_id VARCHAR(36) NOT NULL,
    spot_master_id VARCHAR(36) NOT NULL,
    admin_id VARCHAR(36) NOT NULL,
    email VARCHAR(200) COLLATE utf8mb4_bin NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'REQUESTED',
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at DATETIME DEFAULT NULL,
    reviewed_by_admin_id VARCHAR(36) DEFAULT NULL,
    PRIMARY KEY (request_id),
    UNIQUE KEY uq_rental_admin_request_email (spot_master_id, email),
    UNIQUE KEY uq_rental_admin_request_admin (spot_master_id, admin_id),
    KEY idx_rental_admin_request_pending (spot_master_id, status, requested_at),
    KEY idx_rental_admin_request_admin (admin_id),
    CONSTRAINT chk_rental_admin_request_status CHECK (status IN ('REQUESTED', 'APPROVED', 'REJECTED')),
    CONSTRAINT chk_rental_admin_request_review CHECK (
        (status = 'REQUESTED' AND reviewed_at IS NULL AND reviewed_by_admin_id IS NULL)
        OR (status IN ('APPROVED', 'REJECTED') AND reviewed_at IS NOT NULL AND reviewed_by_admin_id IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
