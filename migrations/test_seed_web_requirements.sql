-- 웹 고객 API 확인용 추가 테스트 데이터
--
-- 전제:
--   1) test_seed_top_level.sql을 먼저 실행한다.
--   2) test_seed_rental_scenarios.sql을 먼저 실행한다.
--   3) 별도 테스트 DB에서만 실행한다. 운영 DB에서는 실행하지 않는다.
--   4) 이 파일이 만드는 행은 모두 NRTEST-WEB-* 식별자를 사용한다.
--
-- 제공하는 시나리오:
--   * 같은 모델의 BASIC/PREMIUM 가격 선택
--   * Kuta/Canggu 배송지역의 동일 주소·지역 불일치 확인
--   * 브라우저가 바로 시험할 수 있는 테스트 이미지 URL
--   * 배송 미지원 모델

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET @test_now = UTC_TIMESTAMP();
SET @spot_master_id = '00000000-0000-4000-8000-000000000101';
SET @primary_admin_id = '00000000-0000-4000-8000-000000000201';
SET @web_basic_vehicle = 'NRTEST-WEB-BASIC-125';
SET @web_premium_vehicle = 'NRTEST-WEB-PREMIUM-125';
SET @web_no_delivery_vehicle = 'NRTEST-WEB-NODELIVERY';
SET @web_model_id = 'NRTEST-WEB-MODEL-125';
SET @web_no_delivery_model = 'NRTEST-WEB-MODEL-ND';
SET @kuta_region_id = 990000001;
SET @canggu_region_id = 990000002;
SET @canggu_link_id = 990000002;

START TRANSACTION;

-- 1. 두 번째 지역: 서로 다른 주소의 배송 불가와 동일 지역 왕복을 구분한다.
INSERT INTO MSP_DELIVERY_REGION
    (delivery_region_id, country_code, region_name, parent_region_id, region_level,
     region_code, sort_order, is_active, created_at, updated_at)
VALUES
    (@canggu_region_id, 'ID', 'Canggu Test Area', NULL, 'CITY',
     'NRTEST-CANGGU', 2, 1, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    country_code = VALUES(country_code), region_name = VALUES(region_name),
    region_level = VALUES(region_level), region_code = VALUES(region_code),
    sort_order = VALUES(sort_order), is_active = 1, updated_at = VALUES(updated_at);

INSERT INTO MSP_SPOT_DELIVERY_REGION
    (spot_delivery_region_id, spot_master_id, delivery_region_id,
     is_delivery_enabled, start_delivery_fee, return_delivery_fee, memo,
     created_at, updated_at)
VALUES
    (@canggu_link_id, @spot_master_id, @canggu_region_id,
     1, 15, 15, 'Nadree 웹 배송 테스트 지역', @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    is_delivery_enabled = 1, start_delivery_fee = 15,
    return_delivery_fee = 15, memo = VALUES(memo), updated_at = VALUES(updated_at);

-- 2. 같은 모델의 BASIC/PREMIUM을 함께 노출하는 테스트 모델.
INSERT INTO MSP_VEHICLE_MODEL
    (model_id, brand, model_name, cc, vehicle_type, model_image_key,
     is_delivery_supported, is_active, created_at, updated_at)
VALUES
    (@web_model_id, 'Honda', 'Vario Web Test 125', 125, 'SCOOTER',
     'https://placehold.co/640x480/png?text=NRTEST-WEB-125', 1, 1, @test_now, @test_now),
    (@web_no_delivery_model, 'SYM', 'Cruiser No Delivery Test', 125, 'SCOOTER',
     'https://placehold.co/640x480/png?text=NRTEST-NO-DELIVERY', 0, 1, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    brand = VALUES(brand), model_name = VALUES(model_name), cc = VALUES(cc),
    vehicle_type = VALUES(vehicle_type), model_image_key = VALUES(model_image_key),
    is_delivery_supported = VALUES(is_delivery_supported), is_active = 1,
    updated_at = VALUES(updated_at);

INSERT INTO MSP_VEHICLE
    (vehicle_id, vehicle_code, plate_number, vehicle_type, model_name,
     is_active, created_by, created_at, updated_at)
VALUES
    (@web_basic_vehicle, 'NR-TEST-WEB-BASIC-125', 'DK-WEB-BASIC-125', 'SCOOTER',
     'Vario Web Test 125', 1, @primary_admin_id, @test_now, @test_now),
    (@web_premium_vehicle, 'NR-TEST-WEB-PREMIUM-125', 'DK-WEB-PREMIUM-125', 'SCOOTER',
     'Vario Web Test 125', 1, @primary_admin_id, @test_now, @test_now),
    (@web_no_delivery_vehicle, 'NR-TEST-WEB-NODELIVERY', 'DK-WEB-NODELIVERY', 'SCOOTER',
     'Cruiser No Delivery Test', 1, @primary_admin_id, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    vehicle_code = VALUES(vehicle_code), plate_number = VALUES(plate_number),
    vehicle_type = VALUES(vehicle_type), model_name = VALUES(model_name),
    is_active = 1, updated_at = VALUES(updated_at);

INSERT INTO MSP_RENTAL_VEHICLE
    (vehicle_id, model_id, plate_number_full, vehicle_image_key, price_type,
     premium_daily_price, rental_enabled, rental_memo, created_at, updated_at)
VALUES
    (@web_basic_vehicle, @web_model_id, 'DK-WEB-BASIC-125',
     'https://placehold.co/640x480/png?text=NRTEST-BASIC', 'BASIC', NULL, 1,
     '웹 BASIC 가격 테스트 차량', @test_now, @test_now),
    (@web_premium_vehicle, @web_model_id, 'DK-WEB-PREMIUM-125',
     'https://placehold.co/640x480/png?text=NRTEST-PREMIUM', 'PREMIUM', 45, 1,
     '웹 PREMIUM 가격 테스트 차량', @test_now, @test_now),
    (@web_no_delivery_vehicle, @web_no_delivery_model, 'DK-WEB-NODELIVERY',
     'https://placehold.co/640x480/png?text=NRTEST-NO-DELIVERY', 'BASIC', NULL, 1,
     '웹 배송 미지원 테스트 차량', @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    model_id = VALUES(model_id), plate_number_full = VALUES(plate_number_full),
    vehicle_image_key = VALUES(vehicle_image_key), price_type = VALUES(price_type),
    premium_daily_price = VALUES(premium_daily_price), rental_enabled = 1,
    rental_memo = VALUES(rental_memo), updated_at = VALUES(updated_at);

INSERT INTO MSP_VEHICLE_STATUS
    (vehicle_id, status, maintenance_until, status_reason, status_changed_at,
     changed_by, created_at, updated_at)
VALUES
    (@web_basic_vehicle, 'AVAILABLE', NULL, '웹 BASIC 가격 테스트', @test_now,
     @primary_admin_id, @test_now, @test_now),
    (@web_premium_vehicle, 'AVAILABLE', NULL, '웹 PREMIUM 가격 테스트', @test_now,
     @primary_admin_id, @test_now, @test_now),
    (@web_no_delivery_vehicle, 'AVAILABLE', NULL, '웹 배송 미지원 테스트', @test_now,
     @primary_admin_id, @test_now, @test_now)
ON DUPLICATE KEY UPDATE
    status = 'AVAILABLE', maintenance_until = NULL,
    status_reason = VALUES(status_reason), status_changed_at = VALUES(status_changed_at),
    changed_by = VALUES(changed_by), updated_at = VALUES(updated_at);

-- 3. 테스트 차량을 기존 테스트 지점에 연결한다.
UPDATE MSP_VEHICLE_SPOT_HISTORY
   SET released_at = @test_now
 WHERE vehicle_id IN (@web_basic_vehicle, @web_premium_vehicle, @web_no_delivery_vehicle)
   AND released_at IS NULL;

INSERT INTO MSP_VEHICLE_SPOT_HISTORY
    (vehicle_id, spot_master_id, assigned_at, released_at, assigned_by, reason)
SELECT vehicle_id, @spot_master_id, @test_now, NULL, @primary_admin_id, 'Nadree web test seed'
  FROM (
      SELECT @web_basic_vehicle AS vehicle_id
      UNION ALL SELECT @web_premium_vehicle
      UNION ALL SELECT @web_no_delivery_vehicle
  ) v
 WHERE NOT EXISTS (
       SELECT 1 FROM MSP_VEHICLE_SPOT_HISTORY h
        WHERE h.vehicle_id = v.vehicle_id AND h.spot_master_id = @spot_master_id
          AND h.released_at IS NULL);

-- 4. 60일 재고를 추가한다. BASIC/PREMIUM은 같은 모델의 후보로 계산된다.
DROP TEMPORARY TABLE IF EXISTS NRTEST_WEB_SEQ;
CREATE TEMPORARY TABLE NRTEST_WEB_SEQ (n INT PRIMARY KEY);
INSERT INTO NRTEST_WEB_SEQ (n) VALUES
    (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12),(13),(14),
    (15),(16),(17),(18),(19),(20),(21),(22),(23),(24),(25),(26),(27),(28),(29),
    (30),(31),(32),(33),(34),(35),(36),(37),(38),(39),(40),(41),(42),(43),(44),
    (45),(46),(47),(48),(49),(50),(51),(52),(53),(54),(55),(56),(57),(58),(59);

INSERT INTO MSP_MODEL_DAILY_INVENTORY
    (spot_master_id, model_id, target_date, total_qty, reserved_qty,
     available_qty, calculated_at, created_at, updated_at)
SELECT @spot_master_id, @web_model_id, DATE_ADD(CURRENT_DATE, INTERVAL n DAY),
       2, 0, 2, @test_now, @test_now, @test_now
  FROM NRTEST_WEB_SEQ
ON DUPLICATE KEY UPDATE
    total_qty = VALUES(total_qty), reserved_qty = VALUES(reserved_qty),
    available_qty = VALUES(available_qty), calculated_at = VALUES(calculated_at),
    updated_at = VALUES(updated_at);

INSERT INTO MSP_MODEL_DAILY_INVENTORY
    (spot_master_id, model_id, target_date, total_qty, reserved_qty,
     available_qty, calculated_at, created_at, updated_at)
SELECT @spot_master_id, @web_no_delivery_model, DATE_ADD(CURRENT_DATE, INTERVAL n DAY),
       1, 0, 1, @test_now, @test_now, @test_now
  FROM NRTEST_WEB_SEQ
ON DUPLICATE KEY UPDATE
    total_qty = VALUES(total_qty), reserved_qty = VALUES(reserved_qty),
    available_qty = VALUES(available_qty), calculated_at = VALUES(calculated_at),
    updated_at = VALUES(updated_at);

COMMIT;

-- 확인용 조회. 비밀번호·토큰 원문은 출력하지 않는다.
SELECT model_id, brand, model_name, cc, model_image_key, is_delivery_supported
  FROM MSP_VEHICLE_MODEL
 WHERE model_id IN (@web_model_id, @web_no_delivery_model);

SELECT vehicle_id, model_id, price_type, premium_daily_price, rental_memo
  FROM MSP_RENTAL_VEHICLE
 WHERE vehicle_id IN (@web_basic_vehicle, @web_premium_vehicle, @web_no_delivery_vehicle);

SELECT delivery_region_id, region_name, region_code, is_active
  FROM MSP_DELIVERY_REGION
 WHERE delivery_region_id IN (@kuta_region_id, @canggu_region_id);
