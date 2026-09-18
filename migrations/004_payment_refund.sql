-- PayPal 환불 요청과 웹훅 결과를 MSP_RENTAL_PAYMENT에 기록한다.
-- 운영 DB 적용 전 스테이징에서 기존 결제 행과 인덱스를 확인한다.

ALTER TABLE MSP_RENTAL_PAYMENT
    ADD COLUMN refund_status VARCHAR(20) NOT NULL DEFAULT 'NONE' AFTER refunded_amount,
    ADD COLUMN paypal_refund_id VARCHAR(50) NULL AFTER refund_status,
    ADD COLUMN refund_requested_at DATETIME NULL AFTER paypal_refund_id,
    ADD COLUMN refund_requested_by_admin_id VARCHAR(36) NULL AFTER refund_requested_at,
    ADD COLUMN refund_reason VARCHAR(200) NULL AFTER refund_requested_by_admin_id,
    ADD KEY idx_rental_payment_refund (refund_status, updated_at),
    ADD CONSTRAINT ck_refund_status CHECK (refund_status IN ('NONE','NOT_REQUIRED','REQUESTED','PENDING','COMPLETED','FAILED'));
