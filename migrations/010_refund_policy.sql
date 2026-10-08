-- Stored cumulative refund target: customer cancellation 90%, administrator cancellation 100%.
-- Apply after 004_payment_refund.sql on databases that already have the payment table.

ALTER TABLE MSP_RENTAL_PAYMENT
    ADD COLUMN refund_requested_amount DECIMAL(18,2) NULL AFTER refund_reason;
