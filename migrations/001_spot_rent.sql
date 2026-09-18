CREATE TABLE MSP_SPOT_RENT (
    spot_master_id VARCHAR(36) NOT NULL,
    legacy_spot_code CHAR(21) DEFAULT NULL,
    delivery_service_type VARCHAR(30) NOT NULL DEFAULT 'NONE',
    invite_code VARCHAR(64) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (spot_master_id),
    UNIQUE KEY uq_spot_rent_legacy_code (legacy_spot_code),
    UNIQUE KEY uq_spot_rent_invite_code (invite_code),
    KEY idx_spot_rent_delivery_type (delivery_service_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
