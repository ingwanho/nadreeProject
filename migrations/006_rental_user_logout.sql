ALTER TABLE MSP_RENTAL_USER
    ADD COLUMN user_access_revoked_at DATETIME NULL AFTER fcm_token_updated_at;
