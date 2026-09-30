-- Nadree 테스트 렌탈 시나리오 데이터
--
-- 전제:
--   1) migrations/test_seed_top_level.sql을 먼저 실행한다.
--   2) 기존 최상위 지점과 대표관리자를 삭제하거나 새로 만들지 않는다.
--   3) 아래 NRTEST_* 식별자 행만 생성·갱신한다.
--   4) 운영 DB에서 실행하지 말고 RIDERLOG_V2_DATA_TEST 같은 별도 테스트 DB에서만 실행한다.
--
-- 기존 테스트 지점:
--   spot_master_id = 00000000-0000-4000-8000-000000000101
-- 기존 대표관리자:
--   admin_id       = 00000000-0000-4000-8000-000000000201
--
-- 관리자 테스트 로그인:
--   대표: nadree.test.admin@example.com / Nadree-Test-123!
--   일반: nadree.test.manager@example.com / Nadree-Test-123!
--
-- FCM 토큰은 형식 확인용 값이다. 실제 푸시 수신 테스트에서는 앱이 발급한
-- Firebase 토큰으로 MSP_ADMIN/MSP_RENTAL_USER 값을 교체한다.
-- QR 행은 QR_HASH_KEY를 모르는 SQL에서 위조할 수 없으므로 넣지 않는다.
-- 관리자 QR 인계 테스트는 /nadreego/vehicle/create에 qrToken을 보내 생성한다.

SET NAMES utf8mb4;
SET @test_now = UTC_TIMESTAMP();
SET @spot_master_id = '00000000-0000-4000-8000-000000000101';
SET @primary_admin_id = '00000000-0000-4000-8000-000000000201';
SET @manager_admin_id = '00000000-0000-4000-8000-000000000202';
SET @test_contract_id = 'NR_TEST_20260921';
SET @delivery_region_id = 990000001;

-- Asia/Makassar(UTC+08:00) 기준의 테스트 기간.
SET @req_start = DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 5 DAY)), INTERVAL 8 HOUR);
SET @req_end = DATE_SUB(DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 9 DAY)), INTERVAL 8 HOUR), INTERVAL 1 SECOND);
SET @approved_start = DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 10 DAY)), INTERVAL 8 HOUR);
SET @approved_end = DATE_SUB(DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 14 DAY)), INTERVAL 8 HOUR), INTERVAL 1 SECOND);
SET @pending_start = DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 20 DAY)), INTERVAL 8 HOUR);
SET @pending_end = DATE_SUB(DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 24 DAY)), INTERVAL 8 HOUR), INTERVAL 1 SECOND);
SET @active_start = DATE_SUB(TIMESTAMP(DATE_SUB(CURRENT_DATE, INTERVAL 2 DAY)), INTERVAL 8 HOUR);
SET @active_end = DATE_SUB(DATE_SUB(TIMESTAMP(DATE_ADD(CURRENT_DATE, INTERVAL 6 DAY)), INTERVAL 8 HOUR), INTERVAL 1 SECOND);
SET @returned_start = DATE_SUB(TIMESTAMP(DATE_SUB(CURRENT_DATE, INTERVAL 14 DAY)), INTERVAL 8 HOUR);
SET @returned_end = DATE_SUB(DATE_SUB(TIMESTAMP(DATE_SUB(CURRENT_DATE, INTERVAL 10 DAY)), INTERVAL 8 HOUR), INTERVAL 1 SECOND);

START TRANSACTION;

-- 1. 관리자·역할·scope: 기존 지점에 일반관리자만 추가한다.
UPDATE MSP_ADMIN
   SET fcm_token = 'test-admin-fcm-token-primary', fcm_token_updated_at = @test_now
 WHERE admin_id = @primary_admin_id;

INSERT INTO MSP_ROLE (role_code, role_name, role_desc, is_active)
VALUES ('rental_manager', '렌탈 일반관리자', '테스트 지점 일반관리자', 1)
ON DUPLICATE KEY UPDATE role_name = VALUES(role_name), role_desc = VALUES(role_desc), is_active = 1;

INSERT INTO MSP_ADMIN
    (admin_id, login_id, email, phone, mfa_method, admin_name, password_hash,
     account_type, contract_id, primary_spot_master_id, is_active, is_legacy,
     fcm_token, fcm_token_updated_at)
VALUES
    (@manager_admin_id, 'nadree.test.manager', 'nadree.test.manager@example.com',
     NULL, 'none', 'Nadree 테스트 일반관리자',
     '$2b$12$cYfiUE0lEkf1ra0VpvrozuWvqq6lfDWWJ6FDsJMesc6LI6M0s0pKy',
     'manager', @test_contract_id, @spot_master_id, 1, 0,
     'test-admin-fcm-token-001', @test_now)
ON DUPLICATE KEY UPDATE
    email = VALUES(email), mfa_method = VALUES(mfa_method),
    admin_name = VALUES(admin_name), password_hash = VALUES(password_hash),
    account_type = VALUES(account_type), contract_id = VALUES(contract_id),
    primary_spot_master_id = VALUES(primary_spot_master_id), is_active = 1,
    is_legacy = 0, fcm_token = VALUES(fcm_token), fcm_token_updated_at = VALUES(fcm_token_updated_at);

INSERT INTO MSP_ADMIN_ROLE (admin_id, role_code, assigned_at, expires_at)
VALUES (@manager_admin_id, 'rental_manager', @test_now, NULL)
ON DUPLICATE KEY UPDATE assigned_at = VALUES(assigned_at), expires_at = NULL;

INSERT INTO MSP_ADMIN_SPOT_SCOPE
    (admin_id, spot_master_id, unit_code, access_type, granted_at, granted_by)
SELECT @manager_admin_id, @spot_master_id, s.unit_code, 'manage', @test_now, @primary_admin_id
  FROM MSP_SPOT_MASTER s
 WHERE s.spot_master_id = @spot_master_id
ON DUPLICATE KEY UPDATE
    unit_code = VALUES(unit_code), access_type = VALUES(access_type),
    granted_at = VALUES(granted_at), granted_by = VALUES(granted_by);

-- 2. 배송 지역과 기존 지점의 배송 설정.
INSERT INTO MSP_DELIVERY_REGION
    (delivery_region_id, country_code, region_name, parent_region_id, region_level,
     region_code, sort_order, is_active, created_at, updated_at)
VALUES
    (@delivery_region_id, 'ID', 'Kuta Test Area', NULL, 'CITY',
     'NRTEST-KUTA', 1, 1, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    country_code = VALUES(country_code), region_name = VALUES(region_name),
    region_level = VALUES(region_level), region_code = VALUES(region_code),
    sort_order = VALUES(sort_order), is_active = 1, updated_at = VALUES(updated_at);

UPDATE MSP_SPOT_RENT
   SET delivery_service_type = 'START_AND_RETURN',
       updated_at = @test_now
 WHERE spot_master_id = @spot_master_id;

INSERT INTO MSP_SPOT_DELIVERY_REGION
    (spot_delivery_region_id, spot_master_id, delivery_region_id,
     is_delivery_enabled, start_delivery_fee, return_delivery_fee, memo,
     created_at, updated_at)
VALUES
    (@delivery_region_id, @spot_master_id, @delivery_region_id,
     1, 10, 10, 'Nadree 테스트 배송 지역', @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    is_delivery_enabled = 1, start_delivery_fee = 10,
    return_delivery_fee = 10, memo = VALUES(memo), updated_at = VALUES(updated_at);

-- 3. 모델과 지점별 가격 티어. 통화는 NADREE_RENTAL_CURRENCY=USD 전제다.
INSERT INTO MSP_VEHICLE_MODEL
    (model_id, brand, model_name, cc, vehicle_type, model_image_key,
     is_delivery_supported, is_active, created_at, updated_at)
VALUES
    ('NRTEST-MODEL-125', 'Honda', 'Vario 125', 125, 'SCOOTER',
     'models/test-vario-125.jpg', 1, 1, @test_now, @test_now),
    ('NRTEST-MODEL-155', 'Yamaha', 'NMAX 155', 155, 'SCOOTER',
     'models/test-nmax-155.jpg', 1, 1, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    brand = VALUES(brand), model_name = VALUES(model_name), cc = VALUES(cc),
    vehicle_type = VALUES(vehicle_type), model_image_key = VALUES(model_image_key),
    is_delivery_supported = 1, is_active = 1, updated_at = VALUES(updated_at);

INSERT INTO MSP_RENTAL_TIER (spot_master_id, price, max_cc, min_cc, tier_type)
SELECT NULL, 25, 125, 0, 'BASE'
 WHERE NOT EXISTS (
       SELECT 1 FROM MSP_RENTAL_TIER
        WHERE spot_master_id IS NULL AND tier_type = 'BASE' AND min_cc = 0 AND max_cc = 125);
UPDATE MSP_RENTAL_TIER SET price = 25
 WHERE spot_master_id IS NULL AND tier_type = 'BASE' AND min_cc = 0 AND max_cc = 125;

INSERT INTO MSP_RENTAL_TIER (spot_master_id, price, max_cc, min_cc, tier_type)
SELECT NULL, 35, 200, 126, 'BASE'
 WHERE NOT EXISTS (
       SELECT 1 FROM MSP_RENTAL_TIER
        WHERE spot_master_id IS NULL AND tier_type = 'BASE' AND min_cc = 126 AND max_cc = 200);
UPDATE MSP_RENTAL_TIER SET price = 35
 WHERE spot_master_id IS NULL AND tier_type = 'BASE' AND min_cc = 126 AND max_cc = 200;

INSERT INTO MSP_RENTAL_TIER (spot_master_id, price, max_cc, min_cc, tier_type)
SELECT @spot_master_id, 25, 125, 0, 'BASIC'
 WHERE NOT EXISTS (
       SELECT 1 FROM MSP_RENTAL_TIER
        WHERE spot_master_id = @spot_master_id AND tier_type = 'BASIC' AND min_cc = 0 AND max_cc = 125);
UPDATE MSP_RENTAL_TIER SET price = 25
 WHERE spot_master_id = @spot_master_id AND tier_type = 'BASIC' AND min_cc = 0 AND max_cc = 125;

INSERT INTO MSP_RENTAL_TIER (spot_master_id, price, max_cc, min_cc, tier_type)
SELECT @spot_master_id, 35, 200, 126, 'BASIC'
 WHERE NOT EXISTS (
       SELECT 1 FROM MSP_RENTAL_TIER
        WHERE spot_master_id = @spot_master_id AND tier_type = 'BASIC' AND min_cc = 126 AND max_cc = 200);
UPDATE MSP_RENTAL_TIER SET price = 35
 WHERE spot_master_id = @spot_master_id AND tier_type = 'BASIC' AND min_cc = 126 AND max_cc = 200;

-- 4. 차량. 차량 301=대여 가능, 302=정비, 303=진행 중 렌트, 304=미래 승인 예약.
INSERT INTO MSP_VEHICLE
    (vehicle_id, vehicle_code, plate_number, vehicle_type, model_name,
     is_active, created_by, created_at, updated_at)
VALUES
    ('NRTEST-VEHICLE-301', 'NR-TEST-301', 'DK-TEST-301', 'SCOOTER', 'Vario 125', 1, @primary_admin_id, @test_now, @test_now),
    ('NRTEST-VEHICLE-302', 'NR-TEST-302', 'DK-TEST-302', 'SCOOTER', 'Vario 125', 1, @primary_admin_id, @test_now, @test_now),
    ('NRTEST-VEHICLE-303', 'NR-TEST-303', 'DK-TEST-303', 'SCOOTER', 'Vario 125', 1, @primary_admin_id, @test_now, @test_now),
    ('NRTEST-VEHICLE-304', 'NR-TEST-304', 'DK-TEST-304', 'SCOOTER', 'NMAX 155', 1, @primary_admin_id, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    vehicle_code = VALUES(vehicle_code), plate_number = VALUES(plate_number),
    vehicle_type = VALUES(vehicle_type), model_name = VALUES(model_name),
    is_active = 1, updated_at = VALUES(updated_at);

INSERT INTO MSP_RENTAL_VEHICLE
    (vehicle_id, model_id, plate_number_full, vehicle_image_key, price_type,
     premium_daily_price, rental_enabled, rental_memo, created_at, updated_at)
VALUES
    ('NRTEST-VEHICLE-301', 'NRTEST-MODEL-125', 'DK-TEST-301', 'vehicles/test-301.jpg', 'BASIC', NULL, 1, '대여 가능 테스트 차량', @test_now, @test_now),
    ('NRTEST-VEHICLE-302', 'NRTEST-MODEL-125', 'DK-TEST-302', 'vehicles/test-302.jpg', 'BASIC', NULL, 1, '정비 상태 테스트 차량', @test_now, @test_now),
    ('NRTEST-VEHICLE-303', 'NRTEST-MODEL-125', 'DK-TEST-303', 'vehicles/test-303.jpg', 'BASIC', NULL, 1, '진행 중 렌트 테스트 차량', @test_now, @test_now),
    ('NRTEST-VEHICLE-304', 'NRTEST-MODEL-155', 'DK-TEST-304', 'vehicles/test-304.jpg', 'BASIC', NULL, 1, '승인 예약 테스트 차량', @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    model_id = VALUES(model_id), plate_number_full = VALUES(plate_number_full),
    vehicle_image_key = VALUES(vehicle_image_key), price_type = VALUES(price_type),
    premium_daily_price = VALUES(premium_daily_price), rental_enabled = 1,
    rental_memo = VALUES(rental_memo), updated_at = VALUES(updated_at);

INSERT INTO MSP_VEHICLE_STATUS
    (vehicle_id, status, maintenance_until, status_reason, status_changed_at,
     changed_by, created_at, updated_at)
VALUES
    ('NRTEST-VEHICLE-301', 'AVAILABLE', NULL, '테스트 대여 가능', @test_now, @primary_admin_id, @test_now, @test_now),
    ('NRTEST-VEHICLE-302', 'MAINTENANCE', DATE_ADD(CURRENT_DATE, INTERVAL 3 DAY), '테스트 정비', @test_now, @primary_admin_id, @test_now, @test_now),
    ('NRTEST-VEHICLE-303', 'ON_RENT', NULL, '테스트 진행 중 렌트', @test_now, @primary_admin_id, @test_now, @test_now),
    ('NRTEST-VEHICLE-304', 'AVAILABLE', NULL, '테스트 승인 예약 차량', @test_now, @primary_admin_id, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    status = VALUES(status), maintenance_until = VALUES(maintenance_until),
    status_reason = VALUES(status_reason), status_changed_at = VALUES(status_changed_at),
    changed_by = VALUES(changed_by), updated_at = VALUES(updated_at);

-- 현재 배정 이력은 테스트 차량마다 한 건만 유지한다.
UPDATE MSP_VEHICLE_SPOT_HISTORY
   SET released_at = @test_now
 WHERE vehicle_id IN ('NRTEST-VEHICLE-301', 'NRTEST-VEHICLE-302',
                      'NRTEST-VEHICLE-303', 'NRTEST-VEHICLE-304')
   AND released_at IS NULL;

INSERT INTO MSP_VEHICLE_SPOT_HISTORY
    (vehicle_id, spot_master_id, assigned_at, released_at, assigned_by, reason)
SELECT v.vehicle_id, @spot_master_id, @test_now, NULL, @primary_admin_id, 'Nadree test seed'
  FROM (SELECT 'NRTEST-VEHICLE-301' AS vehicle_id
        UNION ALL SELECT 'NRTEST-VEHICLE-302'
        UNION ALL SELECT 'NRTEST-VEHICLE-303'
        UNION ALL SELECT 'NRTEST-VEHICLE-304') v
 WHERE NOT EXISTS (
       SELECT 1 FROM MSP_VEHICLE_SPOT_HISTORY h
        WHERE h.vehicle_id = v.vehicle_id AND h.spot_master_id = @spot_master_id
          AND h.released_at IS NULL);

-- 5. 관광객 계정. 로그인 시 refresh token은 API가 생성한다.
INSERT INTO MSP_RENTAL_USER
    (uid_token, name, gender, age, nationality, fcm_token, fcm_token_updated_at,
     user_access_revoked_at, created_at, updated_at)
VALUES
    ('NRTEST-USER-001', 'Nadree Test Customer', 'M', 30, 'KR',
     'test-customer-fcm-token-001', @test_now, NULL, @test_now, @test_now),
    ('NRTEST-USER-002', 'Nadree Conflict Customer', 'F', 28, 'US',
     'test-customer-fcm-token-002', @test_now, NULL, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    name = VALUES(name), gender = VALUES(gender), age = VALUES(age),
    nationality = VALUES(nationality), fcm_token = VALUES(fcm_token),
    fcm_token_updated_at = VALUES(fcm_token_updated_at),
    user_access_revoked_at = NULL, updated_at = VALUES(updated_at);

-- 기존에 생성했던 이 시나리오의 하위 행만 다시 만들어 멱등성을 보장한다.
DELETE FROM MSP_RENTAL_PAYMENT
 WHERE reservation_id IN ('NRTEST-RES-REQ-001', 'NRTEST-RES-APP-001',
                          'NRTEST-RES-PENDING-001', 'NRTEST-RES-REJECT-001',
                          'NRTEST-RES-CANCEL-001', 'NRTEST-RES-EXPIRED-001',
                          'NRTEST-RES-HAND-001', 'NRTEST-RES-RETURN-001')
    OR rental_contract_id IN ('NRTEST-CONTRACT-ONRENT', 'NRTEST-CONTRACT-RETURNED');

DELETE FROM MSP_RENTAL_CONTRACT_HISTORY
 WHERE rental_contract_id IN ('NRTEST-CONTRACT-ONRENT', 'NRTEST-CONTRACT-RETURNED');

DELETE FROM MSP_RENTAL_CONTRACT
 WHERE rental_contract_id IN ('NRTEST-CONTRACT-ONRENT', 'NRTEST-CONTRACT-RETURNED');

DELETE FROM MSP_RESERVATION_HISTORY
 WHERE reservation_id IN ('NRTEST-RES-REQ-001', 'NRTEST-RES-APP-001',
                          'NRTEST-RES-PENDING-001', 'NRTEST-RES-REJECT-001',
                          'NRTEST-RES-CANCEL-001', 'NRTEST-RES-EXPIRED-001',
                          'NRTEST-RES-HAND-001', 'NRTEST-RES-RETURN-001');

DELETE FROM MSP_RESERVATION
 WHERE reservation_id IN ('NRTEST-RES-REQ-001', 'NRTEST-RES-APP-001',
                          'NRTEST-RES-PENDING-001', 'NRTEST-RES-REJECT-001',
                          'NRTEST-RES-CANCEL-001', 'NRTEST-RES-EXPIRED-001',
                          'NRTEST-RES-HAND-001', 'NRTEST-RES-RETURN-001');

-- 6. 예약 상태별 샘플.
INSERT INTO MSP_RESERVATION
    (reservation_id, uid_token, spot_master_id, model_id, assigned_vehicle_id,
     vehicle_assignment_status, vehicle_assigned_at, required_criteria_json,
     start_datetime, end_datetime, delivery_region_id, delivery_request_type,
     delivery_start_address, delivery_return_address, start_delivery_fee_snapshot,
     return_delivery_fee_snapshot, delivery_total_fee_snapshot, reservation_status,
     hold_expires_at, created_at, updated_at)
VALUES
    ('NRTEST-RES-REQ-001', 'NRTEST-USER-001', @spot_master_id, 'NRTEST-MODEL-125', NULL,
     'SOFT_HOLD', NULL,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":25,"quote":{"currency":"USD","totalFrom":120,"totalTo":120}}',
     @req_start, @req_end, @delivery_region_id, 'START_AND_RETURN',
     'Kuta Test Pickup', 'Kuta Test Return', 10, 10, 20, 'REQUESTED', NULL, @test_now, @test_now),
    ('NRTEST-RES-APP-001', 'NRTEST-USER-001', @spot_master_id, 'NRTEST-MODEL-155', 'NRTEST-VEHICLE-304',
     'PROVISIONAL', @test_now,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":35,"quote":{"currency":"USD","totalFrom":140,"totalTo":140}}',
     @approved_start, @approved_end, NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'APPROVED', NULL, @test_now, @test_now),
    ('NRTEST-RES-PENDING-001', 'NRTEST-USER-002', @spot_master_id, 'NRTEST-MODEL-155', 'NRTEST-VEHICLE-304',
     'PROVISIONAL', @test_now,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":35,"quote":{"currency":"USD","totalFrom":140,"totalTo":140}}',
     @pending_start, @pending_end, NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'APPROVED', NULL, @test_now, @test_now),
    ('NRTEST-RES-REJECT-001', 'NRTEST-USER-002', @spot_master_id, 'NRTEST-MODEL-125', NULL,
     'RELEASED', NULL,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":25,"quote":{"currency":"USD","totalFrom":100,"totalTo":100}}',
     @returned_start, @returned_end, NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'REJECTED', NULL, @test_now, @test_now),
    ('NRTEST-RES-CANCEL-001', 'NRTEST-USER-002', @spot_master_id, 'NRTEST-MODEL-125', NULL,
     'RELEASED',
     NULL,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":25,"quote":{"currency":"USD","totalFrom":100,"totalTo":100}}',
     DATE_SUB(@returned_start, INTERVAL 4 DAY), DATE_SUB(@returned_end, INTERVAL 4 DAY), NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'CANCELED', NULL, @test_now, @test_now),
    ('NRTEST-RES-EXPIRED-001', 'NRTEST-USER-002', @spot_master_id, 'NRTEST-MODEL-125', NULL,
     'RELEASED',
     NULL,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":25,"quote":{"currency":"USD","totalFrom":100,"totalTo":100}}',
     DATE_SUB(@returned_start, INTERVAL 7 DAY), DATE_SUB(@returned_end, INTERVAL 7 DAY), NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'EXPIRED', DATE_SUB(@test_now, INTERVAL 1 DAY), @test_now, @test_now),
    ('NRTEST-RES-HAND-001', 'NRTEST-USER-001', @spot_master_id, 'NRTEST-MODEL-125', 'NRTEST-VEHICLE-303',
     'LOCKED', @test_now,
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":25,"quote":{"currency":"USD","totalFrom":200,"totalTo":200}}',
     @active_start, @active_end, NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'HANDED_OVER', NULL, @test_now, @test_now),
    ('NRTEST-RES-RETURN-001', 'NRTEST-USER-001', @spot_master_id, 'NRTEST-MODEL-125', 'NRTEST-VEHICLE-301',
     'LOCKED', DATE_SUB(@test_now, INTERVAL 10 DAY),
     '{"source":"test_seed","priceType":"BASIC","dailyPrice":25,"quote":{"currency":"USD","totalFrom":100,"totalTo":100}}',
     @returned_start, @returned_end, NULL, 'PICKUP',
     NULL, NULL, 0, 0, 0, 'RETURNED', NULL, DATE_SUB(@test_now, INTERVAL 10 DAY), DATE_SUB(@test_now, INTERVAL 10 DAY));

INSERT INTO MSP_RESERVATION_HISTORY
    (reservation_id, event_type, previous_reservation_status, new_reservation_status,
     previous_vehicle_id, new_vehicle_id, previous_assignment_status,
     new_assignment_status, reason, changed_by, created_at)
VALUES
    ('NRTEST-RES-REQ-001', 'REQUESTED', NULL, 'REQUESTED', NULL, NULL, NULL, 'SOFT_HOLD', 'test seed', 'NRTEST-USER-001', @test_now),
    ('NRTEST-RES-APP-001', 'APPROVED', 'REQUESTED', 'APPROVED', NULL, 'NRTEST-VEHICLE-304', 'SOFT_HOLD', 'PROVISIONAL', 'test seed', @primary_admin_id, @test_now),
    ('NRTEST-RES-PENDING-001', 'APPROVED', 'REQUESTED', 'APPROVED', NULL, 'NRTEST-VEHICLE-304', 'SOFT_HOLD', 'PROVISIONAL', 'test seed', @primary_admin_id, @test_now),
    ('NRTEST-RES-REJECT-001', 'REJECTED', 'REQUESTED', 'REJECTED', NULL, NULL, 'SOFT_HOLD', 'RELEASED', 'test seed', @primary_admin_id, @test_now),
    ('NRTEST-RES-CANCEL-001', 'CANCELED', 'REQUESTED', 'CANCELED', NULL, NULL, 'SOFT_HOLD', 'RELEASED', 'test seed', @primary_admin_id, @test_now),
    ('NRTEST-RES-EXPIRED-001', 'EXPIRED', 'APPROVED', 'EXPIRED', NULL, NULL, 'PROVISIONAL', 'RELEASED', 'test seed', 'nadree-job', @test_now),
    ('NRTEST-RES-HAND-001', 'APPROVED', 'REQUESTED', 'APPROVED', NULL, 'NRTEST-VEHICLE-303', 'SOFT_HOLD', 'PROVISIONAL', 'test seed', @primary_admin_id, @test_now),
    ('NRTEST-RES-HAND-001', 'HANDED_OVER', 'APPROVED', 'HANDED_OVER', 'NRTEST-VEHICLE-303', 'NRTEST-VEHICLE-303', 'PROVISIONAL', 'LOCKED', 'test seed', @primary_admin_id, @test_now),
    ('NRTEST-RES-RETURN-001', 'APPROVED', 'REQUESTED', 'APPROVED', NULL, 'NRTEST-VEHICLE-301', 'SOFT_HOLD', 'PROVISIONAL', 'test seed', @primary_admin_id, DATE_SUB(@test_now, INTERVAL 11 DAY)),
    ('NRTEST-RES-RETURN-001', 'HANDED_OVER', 'APPROVED', 'HANDED_OVER', 'NRTEST-VEHICLE-301', 'NRTEST-VEHICLE-301', 'PROVISIONAL', 'LOCKED', 'test seed', @primary_admin_id, DATE_SUB(@test_now, INTERVAL 10 DAY)),
    ('NRTEST-RES-RETURN-001', 'RETURNED', 'HANDED_OVER', 'RETURNED', 'NRTEST-VEHICLE-301', 'NRTEST-VEHICLE-301', 'LOCKED', 'LOCKED', 'test seed', @primary_admin_id, DATE_SUB(@test_now, INTERVAL 9 DAY));

INSERT INTO MSP_RENTAL_CONTRACT
    (rental_contract_id, reservation_id, vehicle_id, uid_token, sensor_id,
     pickup_spot_master_id, return_spot_master_id, actual_start_time,
     actual_end_time, planned_end_date, contract_status, created_at, updated_at)
VALUES
    ('NRTEST-CONTRACT-ONRENT', 'NRTEST-RES-HAND-001', 'NRTEST-VEHICLE-303', 'NRTEST-USER-001', NULL,
     @spot_master_id, NULL, @active_start, NULL, DATE_ADD(CURRENT_DATE, INTERVAL 6 DAY), 'ON_RENT', @active_start, @test_now),
    ('NRTEST-CONTRACT-RETURNED', 'NRTEST-RES-RETURN-001', 'NRTEST-VEHICLE-301', 'NRTEST-USER-001', NULL,
     @spot_master_id, @spot_master_id, @returned_start,
     DATE_SUB(@test_now, INTERVAL 10 DAY), DATE_SUB(CURRENT_DATE, INTERVAL 10 DAY), 'RETURNED',
     @returned_start, DATE_SUB(@test_now, INTERVAL 10 DAY))
ON DUPLICATE KEY UPDATE
    reservation_id = VALUES(reservation_id), vehicle_id = VALUES(vehicle_id),
    uid_token = VALUES(uid_token), pickup_spot_master_id = VALUES(pickup_spot_master_id),
    return_spot_master_id = VALUES(return_spot_master_id), actual_start_time = VALUES(actual_start_time),
    actual_end_time = VALUES(actual_end_time), planned_end_date = VALUES(planned_end_date),
    contract_status = VALUES(contract_status), updated_at = VALUES(updated_at);

INSERT INTO MSP_RENTAL_CONTRACT_HISTORY
    (rental_contract_id, event_type, previous_contract_status, new_contract_status,
     reason, changed_by, created_at)
VALUES
    ('NRTEST-CONTRACT-ONRENT', 'STARTED', NULL, 'ON_RENT', 'test seed', @primary_admin_id, @active_start),
    ('NRTEST-CONTRACT-RETURNED', 'STARTED', NULL, 'ON_RENT', 'test seed', @primary_admin_id, DATE_SUB(@test_now, INTERVAL 10 DAY)),
    ('NRTEST-CONTRACT-RETURNED', 'RETURNED', 'ON_RENT', 'RETURNED', 'test seed', @primary_admin_id, DATE_SUB(@test_now, INTERVAL 9 DAY));

-- 7. 결제 상태별 샘플. APPROVED 예약은 결제 행을 만들지 않아
-- payment/order API를 실제로 호출하면 CREATED 주문을 새로 만들 수 있게 한다.
INSERT INTO MSP_RENTAL_PAYMENT
    (reservation_id, rental_contract_id, payment_provider, payment_environment,
     payment_status, paypal_order_id, paypal_capture_id, total_price, currency,
     refunded_amount, refund_status, paypal_refund_id, refund_requested_at,
     refund_requested_by_admin_id, refund_reason, paid_at, created_at, updated_at)
VALUES
    ('NRTEST-RES-PENDING-001', NULL, 'PAYPAL', 'SANDBOX', 'PENDING', 'NRTEST-ORDER-PENDING', NULL, 140.00, 'USD',
     0.00, 'NONE', NULL, NULL, NULL, NULL, NULL, @test_now, @test_now),
    ('NRTEST-RES-HAND-001', 'NRTEST-CONTRACT-ONRENT', 'PAYPAL', 'SANDBOX', 'PAID',
     'NRTEST-ORDER-PAID-001', 'NRTEST-CAPTURE-PAID-001', 200.00, 'USD',
     0.00, 'NONE', NULL, NULL, NULL, NULL, DATE_SUB(@test_now, INTERVAL 1 DAY), DATE_SUB(@test_now, INTERVAL 2 DAY), @test_now),
    ('NRTEST-RES-RETURN-001', 'NRTEST-CONTRACT-RETURNED', 'PAYPAL', 'SANDBOX', 'PAID',
     'NRTEST-ORDER-REFUND-001', 'NRTEST-CAPTURE-REFUND-001', 100.00, 'USD',
     100.00, 'COMPLETED', 'NRTEST-REFUND-001', DATE_SUB(@test_now, INTERVAL 8 DAY),
     @primary_admin_id, '테스트 환불 완료', DATE_SUB(@test_now, INTERVAL 11 DAY),
     DATE_SUB(@test_now, INTERVAL 14 DAY), DATE_SUB(@test_now, INTERVAL 8 DAY)),
    ('NRTEST-RES-CANCEL-001', NULL, 'PAYPAL', 'SANDBOX', 'FAILED',
     NULL, NULL, 100.00, 'USD',
     0.00, 'NOT_REQUIRED', NULL, NULL, NULL, '테스트 결제 실패', NULL, @test_now, @test_now);

-- 8. 캘린더 조회용 60일 재고 스냅샷.
DROP TEMPORARY TABLE IF EXISTS NRTEST_SEQ;
CREATE TEMPORARY TABLE NRTEST_SEQ (n INT PRIMARY KEY);
INSERT INTO NRTEST_SEQ (n) VALUES
    (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12),(13),(14),
    (15),(16),(17),(18),(19),(20),(21),(22),(23),(24),(25),(26),(27),(28),(29),
    (30),(31),(32),(33),(34),(35),(36),(37),(38),(39),(40),(41),(42),(43),(44),
    (45),(46),(47),(48),(49),(50),(51),(52),(53),(54),(55),(56),(57),(58),(59);

INSERT INTO MSP_MODEL_DAILY_INVENTORY
    (spot_master_id, model_id, target_date, total_qty, reserved_qty,
     available_qty, calculated_at, created_at, updated_at)
SELECT @spot_master_id, 'NRTEST-MODEL-125', DATE_ADD(CURRENT_DATE, INTERVAL n DAY),
       3, 0, 3, @test_now, @test_now, @test_now
  FROM NRTEST_SEQ
ON DUPLICATE KEY UPDATE
    total_qty = VALUES(total_qty), reserved_qty = VALUES(reserved_qty),
    available_qty = VALUES(available_qty), calculated_at = VALUES(calculated_at),
    updated_at = VALUES(updated_at);

INSERT INTO MSP_MODEL_DAILY_INVENTORY
    (spot_master_id, model_id, target_date, total_qty, reserved_qty,
     available_qty, calculated_at, created_at, updated_at)
SELECT @spot_master_id, 'NRTEST-MODEL-155', DATE_ADD(CURRENT_DATE, INTERVAL n DAY),
       1, 0, 1, @test_now, @test_now, @test_now
  FROM NRTEST_SEQ
ON DUPLICATE KEY UPDATE
    total_qty = VALUES(total_qty), reserved_qty = VALUES(reserved_qty),
    available_qty = VALUES(available_qty), calculated_at = VALUES(calculated_at),
    updated_at = VALUES(updated_at);

COMMIT;

-- 확인용 조회. 비밀번호와 토큰 원문은 출력하지 않는다.
SELECT model_id, brand, model_name, cc, is_delivery_supported, is_active
  FROM MSP_VEHICLE_MODEL
 WHERE model_id IN ('NRTEST-MODEL-125', 'NRTEST-MODEL-155');

SELECT vehicle_id, vehicle_code, plate_number, is_active
  FROM MSP_VEHICLE
 WHERE vehicle_id LIKE 'NRTEST-VEHICLE-%';

SELECT reservation_id, uid_token, model_id, assigned_vehicle_id,
       reservation_status, vehicle_assignment_status, start_datetime, end_datetime
  FROM MSP_RESERVATION
 WHERE reservation_id LIKE 'NRTEST-RES-%'
 ORDER BY start_datetime;

SELECT rental_contract_id, reservation_id, vehicle_id, contract_status,
       actual_start_time, actual_end_time, planned_end_date
  FROM MSP_RENTAL_CONTRACT
 WHERE rental_contract_id LIKE 'NRTEST-%';

SELECT payment_id, reservation_id, rental_contract_id, payment_status,
       total_price, currency, refund_status
  FROM MSP_RENTAL_PAYMENT
 WHERE reservation_id LIKE 'NRTEST-%'
 ORDER BY payment_id;
