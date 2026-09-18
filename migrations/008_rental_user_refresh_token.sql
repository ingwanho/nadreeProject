CREATE TABLE MSP_RENTAL_USER_REFRESH_TOKEN (
    token_id VARCHAR(36) NOT NULL,
    uid_token VARCHAR(36) NOT NULL,
    token_hash VARCHAR(200) NOT NULL,
    issued_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL,
    PRIMARY KEY (token_id),
    KEY ix_rental_user_refresh_active (uid_token, revoked_at, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
