-- Prefer python -m app.migrate: inspect the plan before applying to the confirmed DB.
-- Workflow history lives in Firestore; SQL only holds this admission-control link.
ALTER TABLE MSP_SPOT_RENT ADD COLUMN deletion_request_id VARCHAR(80) DEFAULT NULL;
