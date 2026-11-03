-- MySQL 8.0.16+. New durable onsite-request outcomes only.
-- Prefer python -m app.migrate: read-only plan first, then an approved --apply.
-- No existing reservations, QR values, accounts or payments are rewritten.
CREATE TABLE IF NOT EXISTS MSP_RENTAL_ONSITE_REQUEST (
    uid_token VARCHAR(36) NOT NULL,
    client_request_id VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(64) DEFAULT NULL,
    request_state VARCHAR(20) NOT NULL,
    reservation_id VARCHAR(50) DEFAULT NULL,
    error_code VARCHAR(80) DEFAULT NULL,
    http_status INTEGER DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uid_token, client_request_id),
    CONSTRAINT ck_onsite_request_outcome CHECK (
        (request_state = 'PROCESSING' AND request_fingerprint IS NOT NULL
            AND reservation_id IS NULL AND error_code IS NULL AND http_status IS NULL)
        OR (request_state = 'ACCEPTED' AND reservation_id IS NOT NULL
            AND error_code IS NULL AND http_status IS NULL)
        OR (request_state = 'REJECTED' AND reservation_id IS NULL
            AND error_code IS NOT NULL AND http_status BETWEEN 400 AND 499)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
