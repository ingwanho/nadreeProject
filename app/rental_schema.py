"""Approved rental extensions. Runtime uses reflection, never create_all."""
from sqlalchemy import (BigInteger, CheckConstraint, Column as C, Computed, Date, DateTime, ForeignKey,
                        Index, Integer, JSON, MetaData, Numeric, String, Table,
                        Text, UniqueConstraint, text)
from sqlalchemy.dialects.mysql import LONGTEXT, VARCHAR

metadata = MetaData()
ID = BigInteger().with_variant(Integer, "sqlite")
HANDOVER_ID = String(36).with_variant(VARCHAR(36, charset="utf8mb4", collation="utf8mb4_bin"), "mysql")


def timestamps():
    return [C("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
            C("updated_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))]


Table("MSP_DELIVERY_REGION", metadata,
      C("delivery_region_id", ID, primary_key=True, autoincrement=True),
      C("country_code", String(10), nullable=False, index=True), C("region_name", String(100), nullable=False),
      C("parent_region_id", ID, index=True), C("region_level", String(20), nullable=False),
      C("region_code", String(50), unique=True), C("sort_order", Integer, nullable=False, server_default="0"),
      C("is_active", Integer, nullable=False, server_default="1"), *timestamps())
Table("MSP_SPOT_DELIVERY_REGION", metadata,
      C("spot_delivery_region_id", ID, primary_key=True, autoincrement=True),
      C("spot_master_id", String(36), nullable=False), C("delivery_region_id", ID, nullable=False),
      C("is_delivery_enabled", Integer, nullable=False, server_default="0"),
      C("start_delivery_fee", Integer, nullable=False, server_default="0"),
      C("return_delivery_fee", Integer, nullable=False, server_default="0"), C("memo", String(300)),
      *timestamps(), UniqueConstraint("spot_master_id", "delivery_region_id", name="uq_spot_delivery_region"),
      CheckConstraint("start_delivery_fee >= 0 AND return_delivery_fee >= 0", name="ck_delivery_fee"))
Table("MSP_RENTAL_USER", metadata,
      C("uid_token", String(36), primary_key=True),
      C("name", String(100)), C("gender", String(20)),
      C("age", Integer), C("nationality", String(50)),
      C("fcm_token", String(512), index=True), C("fcm_token_updated_at", DateTime),
      C("user_access_revoked_at", DateTime), C("passport_number_enc", Text),
      C("driver_license_number_enc", Text), C("sns_info", Text),
      C("privacy_policy_agreed_at", DateTime), C("terms_agreed_at", DateTime), *timestamps())
Table("MSP_RENTAL_USER_REFRESH_TOKEN", metadata,
      C("token_id", String(36), primary_key=True), C("uid_token", String(36), nullable=False, index=True),
      C("token_hash", String(200), nullable=False), C("issued_at", DateTime, nullable=False),
      C("expires_at", DateTime, nullable=False), C("revoked_at", DateTime),
      Index("ix_rental_user_refresh_active", "uid_token", "revoked_at", "expires_at"))
Table("MSP_VEHICLE_MODEL", metadata,
      C("model_id", String(50), primary_key=True), C("brand", String(50), nullable=False),
      C("model_name", String(50), nullable=False), C("cc", Integer),
      C("vehicle_type", String(30), nullable=False), C("model_image_key", String(500)),
      C("is_delivery_supported", Integer, nullable=False, server_default="0"),
      C("is_active", Integer, nullable=False, server_default="1"), *timestamps(),
      CheckConstraint("cc IS NULL OR cc >= 0", name="ck_model_cc"))
Table("MSP_RENTAL_VEHICLE", metadata,
      C("vehicle_id", String(36), primary_key=True), C("model_id", String(50), nullable=False, index=True),
      C("plate_number_full", String(25)), C("vehicle_image_key", String(500)),
      C("price_type", String(20), nullable=False, server_default="BASIC"), C("premium_daily_price", Integer),
      C("rental_enabled", Integer, nullable=False, server_default="1"), C("rental_memo", String(500)),
      *timestamps(), CheckConstraint("(price_type = 'BASIC' AND premium_daily_price IS NULL) OR "
          "(price_type = 'PREMIUM' AND premium_daily_price IS NOT NULL AND premium_daily_price >= 0)",
          name="ck_rental_vehicle_price"))
Table("MSP_VEHICLE_STATUS", metadata,
      C("vehicle_id", String(36), primary_key=True), C("status", String(20), nullable=False, server_default="AVAILABLE"),
      C("maintenance_until", Date), C("untracked_rent_until", Date),
      C("operation_id", String(64)), C("state_version", Integer, nullable=False, server_default="0"),
      C("status_reason", String(200)), C("status_changed_at", DateTime, nullable=False),
      C("changed_by", String(36)), *timestamps(),
      CheckConstraint("status IN ('AVAILABLE','ON_RENT','MAINTENANCE','DISABLED','UNTRACKED_RENT')", name="ck_vehicle_status"),
      CheckConstraint("(status = 'UNTRACKED_RENT' AND untracked_rent_until IS NOT NULL) OR "
                      "(status != 'UNTRACKED_RENT' AND untracked_rent_until IS NULL)", name="ck_untracked_rent_until"),
      CheckConstraint("status != 'MAINTENANCE' OR maintenance_until IS NOT NULL", name="ck_maintenance_until"))
Table("MSP_VEHICLE_QR", metadata,
      C("vehicle_id", String(36), primary_key=True), C("qr_id", String(36), nullable=False, unique=True),
      C("qr_code_hash", String(64), nullable=False, unique=True),
      C("qr_status", String(20), nullable=False, server_default="ACTIVE"), C("issued_at", DateTime, nullable=False),
      C("expired_at", DateTime), *timestamps(),
      CheckConstraint("qr_status IN ('ACTIVE','INACTIVE','EXPIRED')", name="ck_qr_status"))
Table("MSP_VEHICLE_QR_HISTORY", metadata,
      C("history_id", ID, primary_key=True, autoincrement=True), C("qr_id", String(36), nullable=False),
      C("vehicle_id", String(36), nullable=False, index=True), C("qr_code_hash", String(64), nullable=False, index=True),
      C("qr_status", String(20), nullable=False), C("change_type", String(20), nullable=False),
      C("previous_qr_id", String(36)), C("valid_from", DateTime, nullable=False), C("valid_to", DateTime),
      C("change_reason", String(200)), C("changed_by", String(36)), C("created_at", DateTime, nullable=False))
Table("MSP_RESERVATION", metadata,
      C("reservation_id", String(50), primary_key=True), C("uid_token", String(36), nullable=False, index=True),
      C("spot_master_id", String(36), nullable=False), C("model_id", String(50), nullable=False),
      C("assigned_vehicle_id", String(36), index=True),
      C("vehicle_assignment_status", String(20), nullable=False, server_default="SOFT_HOLD"),
      C("vehicle_assigned_at", DateTime), C("required_criteria_json", JSON),
      C("client_request_id", String(64)), C("handed_over_at", DateTime), C("receipt_deadline_at", DateTime),
      C("start_datetime", DateTime, nullable=False), C("end_datetime", DateTime, nullable=False),
      C("delivery_region_id", ID), C("delivery_request_type", String(30), nullable=False, server_default="PICKUP"),
      C("delivery_start_address", String(500)), C("delivery_return_address", String(500)),
      C("start_delivery_fee_snapshot", Integer, nullable=False, server_default="0"),
      C("return_delivery_fee_snapshot", Integer, nullable=False, server_default="0"),
      C("delivery_total_fee_snapshot", Integer, nullable=False, server_default="0"),
      C("reservation_status", String(20), nullable=False, server_default="REQUESTED"),
      C("hold_expires_at", DateTime), *timestamps(),
      Index("ix_reservation_availability", "spot_master_id", "model_id", "reservation_status", "start_datetime"),
      CheckConstraint("end_datetime >= start_datetime", name="ck_reservation_period"),
      UniqueConstraint("uid_token", "client_request_id", name="uq_reservation_client_request"),
      Index("idx_reservation_receipt_deadline", "reservation_status", "receipt_deadline_at"),
      CheckConstraint("reservation_status IN ('REQUESTED','APPROVED','HANDOVER_PENDING','HANDED_OVER','RETURNED','REJECTED','CANCELED','EXPIRED','NO_RESPONSE')", name="ck_reservation_status"),
      CheckConstraint("vehicle_assignment_status IN ('SOFT_HOLD','PROVISIONAL','REALLOCATED','LOCKED','RELEASED')", name="ck_assignment_status"),
      CheckConstraint("start_delivery_fee_snapshot >= 0 AND return_delivery_fee_snapshot >= 0 AND "
                      "delivery_total_fee_snapshot = start_delivery_fee_snapshot + return_delivery_fee_snapshot", name="ck_delivery_snapshot"))
Table("MSP_RENTAL_ONSITE_REQUEST", metadata,
      C("uid_token", String(36), primary_key=True), C("client_request_id", String(64), primary_key=True),
      C("request_fingerprint", String(64)), C("request_state", String(20), nullable=False),
      C("reservation_id", String(50)), C("error_code", String(80)), C("http_status", Integer), *timestamps(),
      CheckConstraint("(request_state = 'PROCESSING' AND request_fingerprint IS NOT NULL AND reservation_id IS NULL "
                      "AND error_code IS NULL AND http_status IS NULL) OR "
                      "(request_state = 'ACCEPTED' AND reservation_id IS NOT NULL AND error_code IS NULL AND http_status IS NULL) OR "
                      "(request_state = 'REJECTED' AND reservation_id IS NULL AND error_code IS NOT NULL "
                      "AND http_status BETWEEN 400 AND 499)", name="ck_onsite_request_outcome"))
Table("MSP_RESERVATION_HISTORY", metadata,
      C("history_id", ID, primary_key=True, autoincrement=True), C("reservation_id", String(50), nullable=False),
      C("event_type", String(30), nullable=False), C("previous_reservation_status", String(20)),
      C("new_reservation_status", String(20)), C("previous_vehicle_id", String(36)), C("new_vehicle_id", String(36)),
      C("previous_assignment_status", String(20)), C("new_assignment_status", String(20)),
      C("reason", String(200)), C("details", JSON), C("changed_by", String(36)), C("created_at", DateTime, nullable=False),
      Index("ix_reservation_history_latest", "reservation_id", "created_at", "history_id"))
Table("MSP_RENTAL_HANDOVER", metadata,
      C("handover_id", HANDOVER_ID, primary_key=True),
      C("reservation_id", String(50), ForeignKey("MSP_RESERVATION.reservation_id"), nullable=False, index=True),
      C("active_reservation_id", String(50), Computed(
          "CASE WHEN handover_status != 'CANCELED' THEN reservation_id ELSE NULL END", persisted=True), unique=True),
      C("uid_token", String(36), ForeignKey("MSP_RENTAL_USER.uid_token"), nullable=False, index=True),
      C("spot_master_id", String(36), nullable=False), C("vehicle_id", String(36), nullable=False),
      C("assigned_admin_id", String(36)), C("client_request_id", String(64)),
      C("customer_status", String(20), nullable=False, server_default="NOT_STARTED"),
      C("admin_status", String(20), nullable=False, server_default="UNASSIGNED"),
      C("handover_status", String(20), nullable=False, server_default="NOT_STARTED"),
      C("signature_status", String(20), nullable=False, server_default="NOT_STARTED"),
      C("final_price", Integer, nullable=False),
      C("passport_number_enc", Text), C("driver_license_number_enc", Text), C("accommodation_location_enc", Text),
      C("helmet_count", Integer), C("start_date", Date, nullable=False), C("return_date", Date, nullable=False),
      C("pending_changes_enc", Text), C("sns_snapshot_enc", Text), C("signature_completed_at", DateTime),
      C("media_state_json", JSON),
      C("video_key", String(500)), C("passport_photo_key", String(500)),
      C("driver_license_photo_key", String(500)), C("extra_photo_key", String(500)),
      C("customer_started_at", DateTime), C("submitted_at", DateTime), C("admin_confirmed_at", DateTime),
      C("started_at", DateTime), C("canceled_at", DateTime), C("cancel_reason", String(200)), *timestamps(),
      UniqueConstraint("uid_token", "client_request_id", name="uq_handover_customer_request"),
      Index("idx_handover_shop_state", "spot_master_id", "handover_status"),
      CheckConstraint("final_price >= 0 AND (helmet_count IS NULL OR helmet_count >= 0)", name="ck_handover_values"),
      CheckConstraint("handover_status IN ('NOT_STARTED','IN_PROGRESS','WAITING_CUSTOMER','READY','STARTED','CANCELED')", name="ck_handover_status"),
      CheckConstraint("customer_status IN ('NOT_STARTED','DRAFT','SUBMITTED','CHANGE_PENDING','CONFIRMED','REJECTED')", name="ck_handover_customer_status"),
      CheckConstraint("admin_status IN ('UNASSIGNED','REVIEWING','CHANGES_PROPOSED','CONFIRMED')", name="ck_handover_admin_status"),
      CheckConstraint("signature_status IN ('NOT_STARTED','COMPLETED')", name="ck_handover_signature_status"))
Table("MSP_RENTAL_CONTRACT", metadata,
      C("rental_contract_id", String(50), primary_key=True), C("reservation_id", String(50), unique=True),
      C("handover_id", HANDOVER_ID, ForeignKey("MSP_RENTAL_HANDOVER.handover_id"), unique=True),
      C("vehicle_id", String(36), nullable=False, index=True), C("uid_token", String(36), nullable=False, index=True),
      C("sensor_id", String(36)), C("pickup_spot_master_id", String(36), nullable=False, index=True),
      C("return_spot_master_id", String(36)), C("actual_start_time", DateTime), C("actual_end_time", DateTime),
      C("pickup_location_snapshot", JSON), C("return_location_snapshot", JSON),
      C("planned_end_date", Date, nullable=False), C("contract_status", String(20), nullable=False, server_default="ON_RENT"),
      *timestamps(), CheckConstraint("contract_status IN ('ON_RENT','OVERDUE','RETURNED','CANCELED')", name="ck_contract_status"),
      Index("ix_contract_vehicle_open", "vehicle_id", "actual_end_time", "contract_status"))
Table("MSP_RENTAL_CONTRACT_HISTORY", metadata,
      C("history_id", ID, primary_key=True, autoincrement=True), C("rental_contract_id", String(50), nullable=False),
      C("event_type", String(30), nullable=False), C("previous_contract_status", String(20)),
      C("new_contract_status", String(20), nullable=False), C("reason", String(200)), C("changed_by", String(36)),
      C("created_at", DateTime, nullable=False),
      Index("ix_contract_history_latest", "rental_contract_id", "created_at", "history_id"))
Table("MSP_MODEL_DAILY_INVENTORY", metadata,
      C("inventory_id", ID, primary_key=True, autoincrement=True), C("spot_master_id", String(36), nullable=False),
      C("model_id", String(50), nullable=False), C("target_date", Date, nullable=False),
      C("total_qty", Integer, nullable=False), C("reserved_qty", Integer, nullable=False),
      C("available_qty", Integer, nullable=False), C("calculated_at", DateTime, nullable=False), *timestamps(),
      UniqueConstraint("spot_master_id", "model_id", "target_date", name="uq_daily_inventory"),
      CheckConstraint("total_qty >= 0 AND reserved_qty >= 0 AND reserved_qty <= total_qty AND "
                      "available_qty = total_qty - reserved_qty", name="ck_inventory_quantities"))
Table("MSP_RENTAL_TIER", metadata,
      C("spot_master_id", String(36)), C("price", Integer, nullable=False),
      C("max_cc", Integer, nullable=False), C("min_cc", Integer, nullable=False), C("tier_type", String(20), nullable=False),
      UniqueConstraint("spot_master_id", "tier_type", "min_cc", "max_cc", name="uq_rental_tier"),
      CheckConstraint("min_cc >= 0 AND max_cc >= min_cc AND price >= 0", name="ck_tier_values"),
      CheckConstraint("tier_type IN ('BASE','BASIC')", name="ck_tier_type"))
Table("MSP_RENTAL_PAYMENT", metadata,
      C("payment_id", ID, primary_key=True, autoincrement=True), C("reservation_id", String(50), index=True),
      C("rental_contract_id", String(50), index=True), C("payment_provider", String(20), nullable=False, server_default="PAYPAL"),
      C("payment_environment", String(10), nullable=False), C("payment_status", String(30), nullable=False, server_default="CREATED"),
      C("paypal_order_id", String(50)), C("paypal_capture_id", String(50)), C("total_price", Numeric(18, 2), nullable=False),
      C("currency", String(3), nullable=False), C("refunded_amount", Numeric(18, 2), nullable=False, server_default="0"),
      C("refund_status", String(20), nullable=False, server_default="NONE"), C("paypal_refund_id", String(50)),
      C("refund_requested_at", DateTime), C("refund_requested_by_admin_id", String(36)), C("refund_reason", String(200)),
      C("refund_requested_amount", Numeric(18, 2)),
      C("cancellation_requested_by_type", String(20)), C("cancellation_requested_by_id", String(36)),
      C("refund_percentage", Integer),
      C("order_requested_at", DateTime), C("capture_requested_at", DateTime),
      C("refund_attempt_state", JSON), C("paypal_merchant_id", String(13)),
      C("paid_at", DateTime), *timestamps(),
      UniqueConstraint("payment_environment", "paypal_order_id", name="uq_paypal_order"),
      UniqueConstraint("payment_environment", "paypal_capture_id", name="uq_paypal_capture"),
      CheckConstraint("reservation_id IS NOT NULL OR rental_contract_id IS NOT NULL", name="ck_payment_subject"),
      CheckConstraint("total_price > 0 AND refunded_amount >= 0 AND refunded_amount <= total_price", name="ck_payment_amount"),
      CheckConstraint("refund_status IN ('NONE','NOT_REQUIRED','REQUESTED','PENDING','COMPLETED','FAILED')", name="ck_refund_status"))
Table("MSP_PAYPAL_WEBHOOK_EVENT", metadata,
      C("webhook_event_id", ID, primary_key=True, autoincrement=True), C("paypal_event_id", String(100), nullable=False),
      C("payment_environment", String(10), nullable=False), C("payment_id", ID, index=True),
      C("event_type", String(100), nullable=False), C("raw_body", Text().with_variant(LONGTEXT, "mysql"), nullable=False),
      C("verification_headers", JSON, nullable=False), C("verification_status", String(20), nullable=False),
      C("processing_status", String(20), nullable=False, server_default="PENDING"),
      C("retry_count", Integer, nullable=False, server_default="0"), C("last_error", Text),
      C("received_at", DateTime, nullable=False), C("processed_at", DateTime), C("updated_at", DateTime, nullable=False),
      UniqueConstraint("payment_environment", "paypal_event_id", name="uq_paypal_event"),
      Index("ix_paypal_event_retry", "processing_status", "updated_at"))

Table("MSP_RENTAL_NOTIFICATION", metadata,
      C("notification_id", ID, primary_key=True, autoincrement=True),
      C("spot_master_id", String(36), nullable=False), C("event_type", String(50), nullable=False),
      C("target_type", String(20), nullable=False), C("target_id", String(50), nullable=False),
      C("event_key", String(180), nullable=False, unique=True), C("created_at", DateTime, nullable=False),
      C("read_at", DateTime), Index("ix_notification_shop_read", "spot_master_id", "read_at", "notification_id"))

# Opaque provider identifiers and QR digests require case-sensitive MySQL comparisons.
for name in ("MSP_RENTAL_PAYMENT", "MSP_PAYPAL_WEBHOOK_EVENT", "MSP_VEHICLE_QR", "MSP_RENTAL_ONSITE_REQUEST"):
    metadata.tables[name].dialect_options["mysql"]["collate"] = "utf8mb4_bin"
for table in metadata.tables.values():
    table.dialect_options["mysql"]["engine"] = "InnoDB"
    table.dialect_options["mysql"]["charset"] = "utf8mb4"

EXISTING = {
    "MSP_VEHICLE": "vehicle_id vehicle_code plate_number vehicle_type model_name is_active created_by created_at updated_at",
    "MSP_SENSOR": "sensor_id sensor_code vehicle_id spot_id is_active",
    "MSP_VEHICLE_SPOT_HISTORY": "history_id vehicle_id spot_master_id assigned_at released_at assigned_by reason",
    "MSP_SENSOR_SPOT_HISTORY": "history_id sensor_id spot_master_id assigned_at released_at assigned_by reason",
    "MSP_DRIVER": "driver_id driver_name phone nationality license_type is_active",
    "MSP_DRIVER_SPOT_HISTORY": "id driver_id spot_master_id released_at",
}
