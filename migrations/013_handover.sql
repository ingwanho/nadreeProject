-- 2026-11-24 approved handover delta, MySQL 8.0.
-- Review artifact for a fully migrated pre-handover schema. NOT an idempotent script.
-- Preferred application: python -m app.migrate (plan), then --apply --confirm-database NAME.
-- Do not run this file and app.migrate against the same database.
-- Stop API writers and take a backup before schema changes. MySQL DDL is not atomic.
-- Existing CHECK names/collations may differ; app.migrate inspects current definitions.

CREATE TABLE `MSP_RENTAL_HANDOVER` (
	handover_id VARCHAR(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, 
	reservation_id VARCHAR(50) NOT NULL, 
	active_reservation_id VARCHAR(50) GENERATED ALWAYS AS (CASE WHEN handover_status != 'CANCELED' THEN reservation_id ELSE NULL END) STORED, 
	uid_token VARCHAR(36) NOT NULL, 
	spot_master_id VARCHAR(36) NOT NULL, 
	vehicle_id VARCHAR(36) NOT NULL, 
	assigned_admin_id VARCHAR(36), 
	client_request_id VARCHAR(64), 
	customer_status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED', 
	admin_status VARCHAR(20) NOT NULL DEFAULT 'UNASSIGNED', 
	handover_status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED', 
	signature_status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED', 
	final_price INTEGER NOT NULL, 
	passport_number_enc TEXT, 
	driver_license_number_enc TEXT, 
	accommodation_location_enc TEXT, 
	helmet_count INTEGER, 
	start_date DATE NOT NULL, 
	return_date DATE NOT NULL, 
	pending_changes_enc TEXT, 
	media_state_json JSON, 
	video_key VARCHAR(500), 
	passport_photo_key VARCHAR(500), 
	driver_license_photo_key VARCHAR(500), 
	extra_photo_key VARCHAR(500), 
	customer_started_at DATETIME, 
	submitted_at DATETIME, 
	admin_confirmed_at DATETIME, 
	started_at DATETIME, 
	canceled_at DATETIME, 
	cancel_reason VARCHAR(200), 
	created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (handover_id), 
	CONSTRAINT uq_handover_customer_request UNIQUE (uid_token, client_request_id), 
	CONSTRAINT ck_handover_values CHECK (final_price >= 0 AND (helmet_count IS NULL OR helmet_count >= 0)), 
	CONSTRAINT ck_handover_status CHECK (handover_status IN ('NOT_STARTED','IN_PROGRESS','WAITING_CUSTOMER','READY','STARTED','CANCELED')), 
	CONSTRAINT ck_handover_customer_status CHECK (customer_status IN ('NOT_STARTED','DRAFT','SUBMITTED','CHANGE_PENDING','CONFIRMED','REJECTED')), 
	CONSTRAINT ck_handover_admin_status CHECK (admin_status IN ('UNASSIGNED','REVIEWING','CHANGES_PROPOSED','CONFIRMED')), 
	CONSTRAINT ck_handover_signature_status CHECK (signature_status IN ('NOT_STARTED','COMPLETED')), 
	FOREIGN KEY(reservation_id) REFERENCES `MSP_RESERVATION` (reservation_id), 
	UNIQUE (active_reservation_id), 
	FOREIGN KEY(uid_token) REFERENCES `MSP_RENTAL_USER` (uid_token)
)ENGINE=InnoDB CHARSET=utf8mb4;
CREATE INDEX idx_handover_shop_state ON `MSP_RENTAL_HANDOVER` (spot_master_id, handover_status);
CREATE INDEX `ix_MSP_RENTAL_HANDOVER_reservation_id` ON `MSP_RENTAL_HANDOVER` (reservation_id);
CREATE INDEX `ix_MSP_RENTAL_HANDOVER_uid_token` ON `MSP_RENTAL_HANDOVER` (uid_token);

ALTER TABLE MSP_RENTAL_USER ADD COLUMN passport_number_enc TEXT DEFAULT NULL,
    ADD COLUMN driver_license_number_enc TEXT DEFAULT NULL,
    ADD COLUMN sns_info TEXT DEFAULT NULL;
ALTER TABLE MSP_RENTAL_CONTRACT ADD COLUMN handover_id VARCHAR(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
    ADD UNIQUE INDEX uq_contract_handover (handover_id),
    ADD CONSTRAINT fk_contract_handover FOREIGN KEY (handover_id) REFERENCES MSP_RENTAL_HANDOVER (handover_id);
ALTER TABLE MSP_VEHICLE_STATUS ADD COLUMN untracked_rent_until DATE DEFAULT NULL;
-- Expand the existing vehicle status CHECK using app.migrate; retain its original name.
-- Then enforce ((status = 'UNTRACKED_RENT' AND untracked_rent_until IS NOT NULL)
--     OR (status != 'UNTRACKED_RENT' AND untracked_rent_until IS NULL)).
-- Retired passport_img_key: app.migrate refuses removal while non-NULL references exist.
-- Review retention/backup first. Never clear references just to bypass that guard.
