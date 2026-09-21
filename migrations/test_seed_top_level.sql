-- Nadree/RiderLog 격리 테스트용 최상위 계약·조직·대표관리자 시드
--
-- 주의:
--   * 운영 DB에서 실행하지 않는다. RIDERLOG_V2_DATA_TEST처럼 별도 테스트 DB에서만 실행한다.
--   * 기존 데이터를 삭제하지 않으며, 아래 NR_TEST_* 식별자 행만 멱등적으로 갱신한다.
--   * 하위 region/local/spot은 이 SQL로 직접 넣지 않고
--     POST /api/v1/organizations/spots 로 생성해 계층 생성 API를 검증한다.
--
-- 테스트 로그인:
--   login_id: nadree.test.admin
--   password: Nadree-Test-123!
--   email:    nadree.test.admin@example.com

SET NAMES utf8mb4;

START TRANSACTION;

-- 최상위 계약. 계약 ID는 기존 RiderLog 코드 규칙과 같은 상위 prefix의 기반이 된다.
INSERT INTO MSP_CONTRACT
    (contract_id, contract_name, status, sensor_quota, start_date, end_date, memo, created_by)
VALUES
    ('NR_TEST_20260921', 'Nadree API 테스트 계약', 'active', 0, '2026-01-01', '2099-12-31',
     '자동화/API 통합 테스트 전용', NULL)
ON DUPLICATE KEY UPDATE
    contract_name = VALUES(contract_name),
    status = VALUES(status),
    sensor_quota = VALUES(sensor_quota),
    start_date = VALUES(start_date),
    end_date = VALUES(end_date),
    memo = VALUES(memo);

-- RiderLog 계층의 L1 최상위 조직.
INSERT INTO MSP_ORG
    (org_id, contract_id, unit_code, org_name, address, biz_reg_num, phone,
     lat, lng, zip_code, contract_start, contract_end, is_active)
VALUES
    ('00000000-0000-4000-8000-000000000101', 'NR_TEST_20260921',
     'NR_TEST_20260921-ORG01', 'Nadree 테스트 최상위 조직',
     'Test Organization Address', 'TEST-BIZ-20260921', '+62-000-000-000',
     -8.650000, 115.216000, '80000', '2026-01-01', '2099-12-31', 1)
ON DUPLICATE KEY UPDATE
    contract_id = VALUES(contract_id),
    org_name = VALUES(org_name),
    address = VALUES(address),
    biz_reg_num = VALUES(biz_reg_num),
    phone = VALUES(phone),
    lat = VALUES(lat),
    lng = VALUES(lng),
    zip_code = VALUES(zip_code),
    contract_start = VALUES(contract_start),
    contract_end = VALUES(contract_end),
    is_active = 1;

-- 운영 API의 단일 지점 진입점. spot_id는 일부 구 DB에서 삭제됐을 수 있으므로
-- 의도적으로 기록하지 않고 spot_master_id를 기준으로 연결한다.
INSERT INTO MSP_SPOT_MASTER
    (spot_master_id, contract_id, org_id, region_id, local_id,
     org_name, region_name, local_name, unit_code, spot_name,
     unit_name,
     address, zip_code, biz_reg_num, phone, lat, lng,
     contract_start, contract_end, hierarchy_level, is_active)
VALUES
    ('00000000-0000-4000-8000-000000000101', 'NR_TEST_20260921',
     '00000000-0000-4000-8000-000000000101', NULL, NULL,
     'Nadree 테스트 최상위 조직', NULL, NULL, 'NR_TEST_20260921-ORG01',
     'Nadree 테스트 최상위 조직', 'Nadree 테스트 최상위 조직',
     'Test Organization Address', '80000',
     'TEST-BIZ-20260921', '+62-000-000-000', -8.650000, 115.216000,
     '2026-01-01', '2099-12-31', 'org', 1)
ON DUPLICATE KEY UPDATE
    contract_id = VALUES(contract_id),
    org_id = VALUES(org_id),
    region_id = VALUES(region_id),
    local_id = VALUES(local_id),
    org_name = VALUES(org_name),
    region_name = VALUES(region_name),
    local_name = VALUES(local_name),
    unit_code = VALUES(unit_code),
    spot_name = VALUES(spot_name),
    unit_name = VALUES(unit_name),
    address = VALUES(address),
    zip_code = VALUES(zip_code),
    biz_reg_num = VALUES(biz_reg_num),
    phone = VALUES(phone),
    lat = VALUES(lat),
    lng = VALUES(lng),
    contract_start = VALUES(contract_start),
    contract_end = VALUES(contract_end),
    hierarchy_level = VALUES(hierarchy_level),
    is_active = 1;

-- 렌탈 지점 사이드카와 대표관리자 가입 테스트용 초대코드.
INSERT INTO MSP_SPOT_RENT
    (spot_master_id, legacy_spot_code, delivery_service_type, invite_code)
VALUES
    ('00000000-0000-4000-8000-000000000101', NULL, 'NONE',
     'NR_TEST_ROOT_INVITE_20260921')
ON DUPLICATE KEY UPDATE
    delivery_service_type = VALUES(delivery_service_type),
    invite_code = VALUES(invite_code),
    updated_at = CURRENT_TIMESTAMP;

-- Nadree 서버가 사용하는 렌탈 role. 이미 있으면 테스트 DB에서 활성 상태를 보장한다.
INSERT INTO MSP_ROLE (role_code, role_name, role_desc, is_active)
VALUES
    ('rental_primary_admin', '렌탈 대표관리자', '최상위 지점과 하위지점의 대표 관리자', 1),
    ('rental_manager', '렌탈 일반관리자', '승인된 지점의 일반 관리자', 1)
ON DUPLICATE KEY UPDATE
    role_name = VALUES(role_name),
    role_desc = VALUES(role_desc),
    is_active = 1;

-- RiderLog 호환 관리자 계정. password_hash는 Nadree-Test-123!의 bcrypt 해시다.
INSERT INTO MSP_ADMIN
    (admin_id, login_id, email, phone, mfa_method, admin_name, password_hash,
     account_type, contract_id, primary_spot_master_id, is_active, is_legacy,
     fcm_token, fcm_token_updated_at)
VALUES
    ('00000000-0000-4000-8000-000000000201', 'nadree.test.admin',
     'nadree.test.admin@example.com', NULL, 'none',
     'Nadree 테스트 대표관리자',
     '$2b$12$cYfiUE0lEkf1ra0VpvrozuWvqq6lfDWWJ6FDsJMesc6LI6M0s0pKy',
     'manager', 'NR_TEST_20260921',
     '00000000-0000-4000-8000-000000000101', 1, 0, NULL, NULL)
ON DUPLICATE KEY UPDATE
    email = VALUES(email),
    phone = NULL,
    mfa_method = VALUES(mfa_method),
    admin_name = VALUES(admin_name),
    password_hash = VALUES(password_hash),
    account_type = VALUES(account_type),
    contract_id = VALUES(contract_id),
    primary_spot_master_id = VALUES(primary_spot_master_id),
    is_active = 1,
    is_legacy = 0,
    fcm_token = NULL,
    fcm_token_updated_at = NULL;

UPDATE MSP_CONTRACT
   SET created_by = '00000000-0000-4000-8000-000000000201'
 WHERE contract_id = 'NR_TEST_20260921';

INSERT INTO MSP_ADMIN_ROLE (admin_id, role_code, assigned_at, expires_at)
VALUES
    ('00000000-0000-4000-8000-000000000201', 'rental_primary_admin', CURRENT_TIMESTAMP, NULL)
ON DUPLICATE KEY UPDATE
    assigned_at = VALUES(assigned_at),
    expires_at = NULL;

INSERT INTO MSP_ADMIN_SPOT_SCOPE
    (admin_id, spot_master_id, unit_code, access_type, granted_at, granted_by)
VALUES
    ('00000000-0000-4000-8000-000000000201',
     '00000000-0000-4000-8000-000000000101',
     'NR_TEST_20260921-ORG01', 'manage', CURRENT_TIMESTAMP,
     '00000000-0000-4000-8000-000000000201')
ON DUPLICATE KEY UPDATE
    unit_code = VALUES(unit_code),
    access_type = VALUES(access_type),
    granted_at = VALUES(granted_at),
    granted_by = VALUES(granted_by);

COMMIT;

-- 실행 후 확인용 조회. 테스트 비밀번호나 해시는 조회하지 않는다.
SELECT contract_id, status, start_date, end_date
  FROM MSP_CONTRACT
 WHERE contract_id = 'NR_TEST_20260921';

SELECT spot_master_id, contract_id, org_id, unit_code, hierarchy_level, is_active
  FROM MSP_SPOT_MASTER
 WHERE spot_master_id = '00000000-0000-4000-8000-000000000101';

SELECT admin_id, login_id, email, account_type, contract_id,
       primary_spot_master_id, is_active
  FROM MSP_ADMIN
 WHERE admin_id = '00000000-0000-4000-8000-000000000201';

SELECT admin_id, role_code
  FROM MSP_ADMIN_ROLE
 WHERE admin_id = '00000000-0000-4000-8000-000000000201';

SELECT admin_id, spot_master_id, unit_code, access_type
  FROM MSP_ADMIN_SPOT_SCOPE
 WHERE admin_id = '00000000-0000-4000-8000-000000000201';
