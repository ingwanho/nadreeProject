-- 차량 QR/선택 센서 검증용 추가 데이터 (MySQL 8.0.16+, 위치/Firebase 제외).
-- 실제 DB를 조회/실행한 결과가 아니라 저장소 스키마를 기준으로 작성했다.
-- 선행: test_seed_top_level.sql + test_seed_web_requirements.sql의 지점/모델.
-- 기존 행 UPDATE/DELETE 없음. 재실행/중복 식별자/QR 충돌 시 중단한다.
-- mysql --force 사용 금지. 오류 시 ROLLBACK 후 원인을 확인한다.
-- QR 원문을 넣지 말 것. 서버 NADREE_QR_HASH_KEY의 HMAC-SHA256(소문자 hex)을
-- 아래 두 변수를 mysql --init-command로 설정하고 배치 입력으로 실행한다.
--   SET @nr_qr_only_hash = '<QR 전용 차량 원문의 서버 HMAC-SHA256 64자리>';
--   SET @nr_qr_sensor_hash = '<센서 차량 QR 원문의 서버 HMAC-SHA256 64자리>';
-- 전체 실행 예시는 migrations/README.md의 차량 QR 시드 절을 따른다.
-- 원문 예: testQr123123 / testQr456456 (실제 스캔 원문을 쓸 수도 있다).
-- sensor_code는 위 QR 원문/해시와 다른 별도 장치 식별값이다.

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET @nr_qr_seed_ok = 0;
SET @nr_qr_seed_now = UTC_TIMESTAMP();
SET @nr_qr_seed_spot = '00000000-0000-4000-8000-000000000101';
SET @nr_qr_seed_admin = '00000000-0000-4000-8000-000000000201';
SET @nr_qr_seed_model = 'NRTEST-WEB-MODEL-125';
SET @nr_qr_seed_sensor = 'NRTEST-SENSOR-QR-001';

DROP TEMPORARY TABLE IF EXISTS nr_qr_seed_rows;
CREATE TEMPORARY TABLE nr_qr_seed_rows (
    vehicle_id VARCHAR(36) PRIMARY KEY,
    vehicle_code VARCHAR(50) NOT NULL,
    plate_number VARCHAR(25) NOT NULL,
    qr_id VARCHAR(36) NOT NULL,
    qr_hash VARCHAR(64),
    equipment_type VARCHAR(20) NOT NULL
) ENGINE=InnoDB;
INSERT INTO nr_qr_seed_rows VALUES
    ('NRTEST-QR-ONLY-001', 'NR-TEST-QR-ONLY-001', 'DK-QR-ONLY-001',
     'NRTEST-QR-ID-ONLY-001', @nr_qr_only_hash, 'QR_ONLY'),
    ('NRTEST-QR-SENSOR-001', 'NR-TEST-QR-SENSOR-001', 'DK-QR-SENSOR-001',
     'NRTEST-QR-ID-SENSOR-001', @nr_qr_sensor_hash, 'QR_WITH_SENSOR');

DROP TEMPORARY TABLE IF EXISTS nr_qr_seed_guard;
CREATE TEMPORARY TABLE nr_qr_seed_guard (
    ok TINYINT NOT NULL,
    CONSTRAINT nr_qr_seed_preconditions CHECK (ok = 1)
) ENGINE=InnoDB;

START TRANSACTION;
-- 지점 단위 동시 시드 실행 직렬화. 지점이 없으면 아래 검증에서 중단한다.
SELECT spot_master_id FROM MSP_SPOT_MASTER
 WHERE spot_master_id = @nr_qr_seed_spot FOR UPDATE;

SET @nr_qr_seed_ok = COALESCE(
    DATABASE() = 'RIDERLOG_V2_DATA_TEST'
    AND REGEXP_LIKE(@nr_qr_only_hash, '^[0-9a-f]{64}$', 'c')
    AND REGEXP_LIKE(@nr_qr_sensor_hash, '^[0-9a-f]{64}$', 'c')
    AND @nr_qr_only_hash <> @nr_qr_sensor_hash
    AND (SELECT COUNT(*) FROM information_schema.tables
          WHERE table_schema = DATABASE() AND engine = 'InnoDB'
            AND table_name IN ('MSP_VEHICLE', 'MSP_RENTAL_VEHICLE', 'MSP_VEHICLE_STATUS',
                'MSP_VEHICLE_SPOT_HISTORY', 'MSP_SENSOR', 'MSP_SENSOR_SPOT_HISTORY',
                'MSP_VEHICLE_QR', 'MSP_VEHICLE_QR_HISTORY')) = 8
    AND EXISTS (SELECT 1 FROM MSP_SPOT_MASTER
                WHERE spot_master_id = @nr_qr_seed_spot AND is_active = 1)
    AND EXISTS (SELECT 1 FROM MSP_SPOT_RENT WHERE spot_master_id = @nr_qr_seed_spot)
    AND EXISTS (SELECT 1 FROM MSP_ADMIN WHERE admin_id = @nr_qr_seed_admin
                 AND is_active = 1 AND primary_spot_master_id = @nr_qr_seed_spot)
    AND EXISTS (SELECT 1 FROM MSP_VEHICLE_MODEL WHERE model_id = @nr_qr_seed_model AND is_active = 1)
    AND NOT EXISTS (SELECT 1 FROM MSP_VEHICLE
                    WHERE vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001')
                       OR vehicle_code IN ('NR-TEST-QR-ONLY-001', 'NR-TEST-QR-SENSOR-001')
                       OR plate_number IN ('DK-QR-ONLY-001', 'DK-QR-SENSOR-001'))
    AND NOT EXISTS (SELECT 1 FROM MSP_RENTAL_VEHICLE
                    WHERE vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001')
                       OR plate_number_full IN ('DK-QR-ONLY-001', 'DK-QR-SENSOR-001'))
    AND NOT EXISTS (SELECT 1 FROM MSP_VEHICLE_STATUS WHERE vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001'))
    AND NOT EXISTS (SELECT 1 FROM MSP_VEHICLE_SPOT_HISTORY WHERE vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001'))
    AND NOT EXISTS (SELECT 1 FROM MSP_VEHICLE_QR
                    WHERE vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001')
                       OR qr_id IN ('NRTEST-QR-ID-ONLY-001', 'NRTEST-QR-ID-SENSOR-001')
                       OR qr_code_hash IN (@nr_qr_only_hash, @nr_qr_sensor_hash))
    AND NOT EXISTS (SELECT 1 FROM MSP_VEHICLE_QR_HISTORY
                    WHERE vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001')
                       OR qr_id IN ('NRTEST-QR-ID-ONLY-001', 'NRTEST-QR-ID-SENSOR-001')
                       OR qr_code_hash IN (@nr_qr_only_hash, @nr_qr_sensor_hash))
    AND NOT EXISTS (SELECT 1 FROM MSP_SENSOR WHERE sensor_id = @nr_qr_seed_sensor
                    OR sensor_code = 'NRTEST-LOCATION-SENSOR-001'
                    OR legacy_sensor_code = 'NRTEST-LEGACY-SENSOR-001'
                    OR vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001'))
    AND NOT EXISTS (SELECT 1 FROM MSP_SENSOR_SPOT_HISTORY WHERE sensor_id = @nr_qr_seed_sensor), 0);

-- 0이면 대상 DB/해시/선행 시드/기존 식별자 충돌을 확인한다. 아래 INSERT도
-- 동일 변수로 제한하므로 선행 검증 실패 시 업무 행을 생성하지 않는다.
SELECT @nr_qr_seed_ok AS seed_preconditions_ok;
INSERT INTO nr_qr_seed_guard VALUES (@nr_qr_seed_ok);

INSERT INTO MSP_VEHICLE
    (vehicle_id, vehicle_code, plate_number, vehicle_type, model_name,
     is_active, created_by, created_at, updated_at)
SELECT s.vehicle_id, s.vehicle_code, s.plate_number, m.vehicle_type, m.model_name,
       1, @nr_qr_seed_admin, @nr_qr_seed_now, @nr_qr_seed_now
  FROM nr_qr_seed_rows s JOIN MSP_VEHICLE_MODEL m ON m.model_id = @nr_qr_seed_model
 WHERE @nr_qr_seed_ok = 1;

INSERT INTO MSP_RENTAL_VEHICLE
    (vehicle_id, model_id, plate_number_full, price_type, premium_daily_price,
     rental_enabled, rental_memo, created_at, updated_at)
SELECT vehicle_id, @nr_qr_seed_model, plate_number, 'PREMIUM', 45, 1,
       CONCAT('QR equipment test: ', equipment_type), @nr_qr_seed_now, @nr_qr_seed_now
  FROM nr_qr_seed_rows WHERE @nr_qr_seed_ok = 1;

INSERT INTO MSP_VEHICLE_STATUS
    (vehicle_id, status, status_reason, status_changed_at, changed_by, created_at, updated_at)
SELECT vehicle_id, 'AVAILABLE', 'QR equipment test seed', @nr_qr_seed_now,
       @nr_qr_seed_admin, @nr_qr_seed_now, @nr_qr_seed_now
  FROM nr_qr_seed_rows WHERE @nr_qr_seed_ok = 1;

INSERT INTO MSP_VEHICLE_SPOT_HISTORY
    (vehicle_id, spot_master_id, assigned_at, assigned_by, reason)
SELECT vehicle_id, @nr_qr_seed_spot, @nr_qr_seed_now, @nr_qr_seed_admin, 'QR equipment test seed'
  FROM nr_qr_seed_rows WHERE @nr_qr_seed_ok = 1;

INSERT INTO MSP_SENSOR
    (sensor_id, vehicle_id, spot_master_id, legacy_sensor_code, sensor_type, sensor_code,
     is_active, created_by, created_at, updated_at)
SELECT @nr_qr_seed_sensor, 'NRTEST-QR-SENSOR-001', spot_master_id, 'NRTEST-LEGACY-SENSOR-001',
       'lte', 'NRTEST-LOCATION-SENSOR-001', 1, @nr_qr_seed_admin, @nr_qr_seed_now, @nr_qr_seed_now
  FROM MSP_SPOT_MASTER WHERE spot_master_id = @nr_qr_seed_spot AND @nr_qr_seed_ok = 1;

INSERT INTO MSP_SENSOR_SPOT_HISTORY
    (sensor_id, spot_master_id, assigned_at, assigned_by, reason)
SELECT @nr_qr_seed_sensor, @nr_qr_seed_spot, @nr_qr_seed_now, @nr_qr_seed_admin, 'QR equipment test seed'
 WHERE @nr_qr_seed_ok = 1;

INSERT INTO MSP_VEHICLE_QR
    (vehicle_id, qr_id, qr_code_hash, qr_status, issued_at, created_at, updated_at)
SELECT vehicle_id, qr_id, qr_hash, 'ACTIVE', @nr_qr_seed_now, @nr_qr_seed_now, @nr_qr_seed_now
  FROM nr_qr_seed_rows WHERE @nr_qr_seed_ok = 1;

INSERT INTO MSP_VEHICLE_QR_HISTORY
    (qr_id, vehicle_id, qr_code_hash, qr_status, change_type, valid_from,
     change_reason, changed_by, created_at)
SELECT qr_id, vehicle_id, qr_hash, 'ACTIVE', 'ISSUED', @nr_qr_seed_now,
       'QR equipment test seed', @nr_qr_seed_admin, @nr_qr_seed_now
  FROM nr_qr_seed_rows WHERE @nr_qr_seed_ok = 1;

COMMIT;

-- 상태 확인: QR 원문/해시·인증정보는 출력하지 않는다.
SELECT v.vehicle_id, v.plate_number, h.spot_master_id, q.qr_status,
       CASE WHEN s.sensor_id IS NULL THEN 'QR_ONLY' ELSE 'QR_WITH_SENSOR' END AS equipment_type,
       s.sensor_id, s.sensor_code
  FROM MSP_VEHICLE v
  JOIN MSP_VEHICLE_SPOT_HISTORY h ON h.vehicle_id = v.vehicle_id AND h.released_at IS NULL
  JOIN MSP_VEHICLE_QR q ON q.vehicle_id = v.vehicle_id
  LEFT JOIN MSP_SENSOR s ON s.vehicle_id = v.vehicle_id AND s.is_active = 1
 WHERE v.vehicle_id IN ('NRTEST-QR-ONLY-001', 'NRTEST-QR-SENSOR-001');

DROP TEMPORARY TABLE nr_qr_seed_guard;
DROP TEMPORARY TABLE nr_qr_seed_rows;
-- Firebase/위치 문서/기존 예약/결제/사용자/관리자 권한/기존 QR은 변경하지 않는다.
-- 새 모델 일별 재고를 강제로 덮어쓰지 않는다. 재고 화면 검증까지 필요하면
-- 기존 app.jobs inventory 작업을 승인 후 별도로 실행한다.
