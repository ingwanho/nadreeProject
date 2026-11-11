-- Star Pickers 브랜드/모델 카탈로그 추가 (작성: 2026-11-11).
-- 원본: Unit List for Star Pickers.xlsx / Sheet1, 8개 브랜드 / 105개 모델.
-- Beneli, Custom Motorcycle은 모델이 없어 제외한다.
-- 대상: RIDERLOG_V2_DATA_TEST / MySQL 8.0.16+ / MSP_VEHICLE_MODEL (InnoDB).
-- 이 파일은 작성/격리 검증용이며 실제 서버 DB에는 아직 실행하지 않았다.
--
-- 적용:
--   cd /srv/nadree-api
--   mysql -h www.riderlog-lte.com -P 50020 -u Datateam -p \
--     RIDERLOG_V2_DATA_TEST < migrations/insert_star_pickers_vehicle_models.sql
-- mysql 배치 입력으로 파일 전체를 실행한다. --force는 사용하지 않는다.
-- 오류가 발생하면 연결 종료로 미커밋 변경이 취소된다. 대화형 실행 중 오류 시 ROLLBACK한다.
--
-- 브랜드 테이블은 따로 없으므로 공용 모델 카탈로그에 등록한다.
-- 차량/QR/가격/예약 데이터는 생성하지 않는다. API 재시작 없이 새 조회부터 반영된다.
-- 기존 brand+model_name(대소문자/양끝 공백 무시)이 있으면 그대로 유지한다.
-- 비활성 모델도 중복 생성/재활성화하지 않는다. 동일 model_id의 다른 모델은 오류로 중단한다.
-- 모델명 앞 브랜드/RE/CF Moto 접두어와 양끝 공백만 제거한다.
-- Roadsycn, Tourine, V-Storm 등 Excel 내부 표기는 임의 교정하지 않는다.
-- 공식 자료의 모델 계열을 대응시킨 경우는 아래 출처 설명에 표시한다.
-- 연식 미표기 일반 모델은 현행/최근 공개 제원 기준이며 실차 연식별 등록증 확인을 대신하지 않는다.
-- cc는 정수형이므로 확인한 소수점 제원은 반올림한다 (예: 156.9 -> 157).
-- 제조사가 정수 cc만 표기한 자료는 해당 값을 사용한다. 모델명 숫자가 cc와 다를 수 있다.
-- 미확정 3개(F01~F03)는 사용자 지정값 50cc로 넣는다. 실제 50cc 확인이라는 뜻은 아니다.
-- 이 값은 BASE/BASIC 가격 구간 판정에도 사용되므로 아래 cc 차이/기본값 결과를 확인한다.
-- 이미지 NULL, 배송지원 0(기존 기본값), 활성 1로 신규 모델만 추가한다.
-- 임시 작업표는 현재 연결에만 존재하며 마지막에 삭제한다.
--
-- 배기량 근거 (조회: 2026-11-11). 동일 엔진 계열의 세부형은 설명된 계열 제원을 적용했다.
-- H01: 109.5 → 110; BeAT/BeAT Street
--   https://www.astra-honda.com/brochures/Honda-BeAT-2020.pdf
-- H02: 108.2 → 108; Scoopy gen 4의 2017년 공개 제원
--   https://www.astra-honda.com/brochures/Brochure-all-new-scoopy-2017.pdf
-- H03: 109.51 → 110; Scoopy gen 5
--   https://www.wahanahonda.com/assets/upload/buku_manual/honda-scoopy.pdf
-- H04: 109.5 → 110; Scoopy gen 6
--   https://www.wahanahonda.com/blog/all-new-honda-scoopy-2025-lebih-segar-lebih-trendi
-- H05: 109.55 → 110; Genio
--   https://www.astra-honda.com/product/genio?gad=1
-- H06: 124.8 → 125; Vario 125/Street는 동일 모델 계열의 제원 적용
--   https://www.astra-honda.com/brochures/Vario-125-2020-Brochure-01.pdf
-- H07: 149.3 → 149; Vario 150
--   https://www.astra-honda.com/brochures/Honda%20Vario%20150-2019%2001.pdf
-- H08: 156.9 → 157; Vario Evo 160 CBS/ABS
--   https://www.wahanahonda.com/produk/honda-vario-evo-160
-- H09: 156.9 → 157; Stylo 160 CBS/ABS
--   https://www.astra-honda.com/product/stylo-160
-- H10: 149.3 → 149; PCX 150 CBS/ABS
--   https://www.astra-honda.com/brochures/Brochure-PCX-150-2020.pdf
-- H11: 156.9 → 157; PCX 160 CBS/ABS/RoadSync
--   https://www.wahanahonda.com/produk/honda-pcx-160
-- H12: 149.3 → 149; ADV 150 CBS/ABS
--   https://asset.astra-honda.com/uploads/download/adv-150-2020-brochure-01-1-1-16042021-045837.pdf
-- H13: 156.9 → 157; ADV 160 CBS/ABS/RoadSync
--   https://www.wahanahonda.com/produk/honda-adv-160
-- H14: 249; 인도네시아 판매 Forza
--   https://www.wahanahonda.com/produk/honda-forza
-- H15: 149.16 → 149; CB150R Streetfire
--   https://asset.astra-honda.com/uploads/download/honda-cb150r-streetfire-brochure2019-1.pdf
-- H16: 149.16 → 149; CB150X
--   https://www.wahanahonda.com/produk/honda-cb150x
-- H17: 149.15 → 149; CRF150L
--   https://www.astra-honda.com/brochures/Brochure-CRF150L-1-Oktober-2018.pdf
-- H18: 149.16 → 149; CBR150R/ABS
--   https://www.wahanahonda.com/produk/honda-cbr150r
-- H19: 249.7 → 250; CBR250RR
--   https://www.astra-honda.com/cbrseries/the-art-of-kabuki
-- H20: 249.67 → 250; CRF250L
--   https://www.wahanahonda.com/produk/honda-crf250l
-- H21: 249.6 → 250; CRF250 Rally
--   https://www.wahanahonda.com/produk/honda-crf250-rally
-- K01: 249; Ninja 250/ABS SE
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/ninja/sport/ninja-250/2026-ninja-250-abs-se
-- K02: 249.8 → 250; ZX-25R 계열의 엔진 제원 적용
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/ninja/supersport/ninja-zx-25r/2026-ninja-zx-25r-se
-- K03: 249; Z250/ABS
--   https://kawasaki.com.my/product/z/z250-abs
-- K04: 249; Versys-X 250. Excel의 Versys 250도 동일 계열로 해석
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/versys/adventure-touring/versys-x-250/2026-versys-x-250
-- K05: 177; W175/ABS
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/w/retro-classic/2024-w175l/2026-w175
-- K06: 233; Meguro S1
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/meguro/retro-classic/meguro-s1/2025-meguro-s1
-- K07: 249; D-Tracker X
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/d-tracker/supermoto/d-tracker-x
-- K08: 144; KLX150
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/klx/dual-purpose-150/klx150/2026-klx150
-- K09: 144; KLX150SM
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/klx/supermoto/klx150sm/2025-klx150sm
-- K10: 233; KLX230
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/klx/dual-purpose-230-250/klx230
-- K11: 249; KLX250
--   https://www.kawasaki-motor.co.id/id-id/sepeda-motor/klx/dual-purpose-230-250/klx250
-- Y01: 155.09 → 155; Aerox 계열 제원, ABS/CBS 표기는 Excel 유지
--   https://www.yamaha-motor.co.id/web_new/product/pdf/Brosur%20-%20Aerox%20Alpha.pdf
-- Y02: 124.86 → 125; Fazzio
--   https://www.yamaha-motor.co.id/product/fazzio/
-- Y03: 125; Fino 125
--   https://www.yamaha-motor.co.id/product/fino/
-- Y04: 125; FreeGo 125. FreeGo 110은 확인되지 않아 F02 사용
--   https://www.yamaha-motor.co.id/product/freego-125/
-- Y05: 124.86 → 125; Grand Filano
--   https://www.yamaha-motor.co.id/product/grand-filano/
-- Y06: 124.96 → 125; Gear 125
--   https://www.yamaha-motor.co.id/product/gear-125/
-- Y07: 124.86 → 125; Gear Ultima
--   https://www.yamaha-motor.co.id/product/gear-ultima/
-- Y08: 155.09 → 155; Nmax 계열
--   https://www.yamaha-motor.co.id/product/nmax-turbo/
-- Y09: 124.7 → 125; Lexi 125
--   https://www.yamaha-motor.co.id/product/lexi/
-- Y10: 155.09 → 155; Lexi LX 155 계열
--   https://www.yamaha-motor.co.id/product/lexi-lx-155/
-- Y11: 124.96 → 125; Mio M3 125
--   https://www.yamaha-motor.co.id/web_new/product/pdf/Brosur%20-%20Mio%20M3.pdf
-- Y12: 249.8 → 250; Xmax 250 계열
--   https://www.yamaha-motor.co.id/web_new/product/pdf/Brosur%20-%20XMAX.pdf
-- Y13: 125; X-Ride 125
--   https://www.yamaha-motor.co.id/product/x-ride/
-- Y14: 155; XSR155 공식 엔진 표기
--   https://www.yamaha-motor.co.id/product/xsr-155/
-- Y15: 155; R15/ABS와 MT-15의 현행 155cc 계열 제원 적용
--   https://www.yamaha-motor.co.id/archives/news/blog/2026/10/perbedaan-yamaha-r15-dan-mt-15-fairing-atau-naked/
-- Y16: 250; R25/ABS와 MT-25의 공식 250cc 계열 표기; MT-25 249.55도 반올림 시 동일
--   https://www.yamaha-motor.co.id/archives/news/blog/2025/10/motor-250cc-ulasan-spesifikasi-dan-tips-perawatan/
-- Y17: 155.09 → 155; WR155R
--   https://www.yamaha-motor.co.id/product/wr155r/
-- T01: 113; Callisto 110의 현행 인도네시아 공식 페이지 표기. 구형 제원으로 확정한 값이 아님
--   https://indonesia.tvsmotor.com/id/our-products/tvs-callisto-110
-- T02: 124.8 → 125; Callisto 125
--   https://indonesia.tvsmotor.com/id/our-products/tvs-callisto-125-basic
-- T03: 225; Ronin의 인도네시아 공식 페이지 표기
--   https://indonesia.tvsmotor.com/tvs-ronin/
-- R01: 349.34 → 349; Classic 350 현행 J-series
--   https://www.royalenfield.com/content/dam/royal-enfield/united-kingdom/motorcycles/technical-specifications/royal-enfield-classic-350-technical-specifications.pdf
-- R02: 452; Himalayan 450
--   https://www.royalenfield.com/in/en/motorcycles/new-himalayan/
-- R03: 349.34 → 349; Meteor 350
--   https://www.royalenfield.com/in/en/motorcycles/meteor/
-- Q01: 197; SRV 200 MT
--   https://qjmotorindonesia.com/model/srv-200-mt/
-- Q02: 249; SRV 250 AMT
--   https://qjmotorindonesia.com/model/srv-250-amt/
-- Q03: 249; SRV 250 Libero
--   https://qjmotorindonesia.com/model/srv-250-libero/
-- Q04: 175; Fort 180 Adventure
--   https://qjmotorindonesia.com/model/fort-180-adventure/
-- Q05: 249.7 → 250; Fort 250
--   https://qjmotorindonesia.com/model/fort-250/
-- Q06: 249.4 → 249; Fort 250 Adventure
--   https://qjmotorindonesia.com/model/fort-250-adventure/
-- Q07: 249; Tourine/Tourino 250 DX
--   https://qjmotorindonesia.com/model/tourino-250-dx/
-- S01: 124; Access 125
--   https://www.suzuki.co.id/uploads/brochures/access125.pdf
-- S02: 124; Burgman Street 125 EX
--   https://www.suzuki.co.id/motorcycle/burgman-street-125ex
-- S03: 113; Nex II/Nex Crossover/Address FI
--   https://www.suzuki.co.id/uploads/SuzukiCompanyProfile2025%28ENG%29_compressed.pdf
-- S04: 147.3 → 147; GSX-S150
--   https://www.suzuki.co.id/motorcycle/gsx-s150
-- S05: 147.3 → 147; GSX-R150
--   https://www.suzuki.co.id/motorcycle/gsx-r150
-- S06: 249; V-Strom 250 SX. Excel V-Storm 표기 유지
--   https://www.suzuki.co.id/uploads/SuzukiCompanyProfile2025%28ENG%29_compressed.pdf
-- C01: 449; 450MT 수출형 공식 제원
--   https://www.cfmoto.com.au/model/450mt
-- F01: 50; Scoopy Old: 연식/세대 미상으로 정확한 제원 미확정. 사용자 지정 기본값
-- F02: 50; FreeGo 110: 이 모델명을 제조사 자료에서 확인하지 못함. 125로 임의 변경하지 않음
-- F03: 50; X-Ride: 구형/125 구분 미상. 별도 X-Ride 125 행은 공식 125 사용

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET @sp_catalog_ok = 0;
SET @sp_catalog_inserted = 0;
SET @sp_catalog_now = UTC_TIMESTAMP();

DROP TEMPORARY TABLE IF EXISTS sp_catalog_source;
CREATE TEMPORARY TABLE sp_catalog_source (
    source_row SMALLINT NOT NULL UNIQUE,
    model_id VARCHAR(50) PRIMARY KEY,
    brand VARCHAR(50) NOT NULL,
    model_name VARCHAR(50) NOT NULL,
    cc INT NOT NULL,
    vehicle_type VARCHAR(30) NOT NULL,
    spec_ref VARCHAR(3) NOT NULL,
    UNIQUE KEY uq_sp_catalog_name (brand, model_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO sp_catalog_source
    (source_row, model_id, brand, model_name, cc, vehicle_type, spec_ref)
VALUES
    (3, 'SPCAT-HONDA-BEAT', 'Honda', 'Beat', 110, 'SCOOTER', 'H01'),
    (4, 'SPCAT-HONDA-BEAT-STREET', 'Honda', 'Beat Street', 110, 'SCOOTER', 'H01'),
    (5, 'SPCAT-HONDA-SCOOPY-OLD', 'Honda', 'Scoopy Old', 50, 'SCOOTER', 'F01'),
    (6, 'SPCAT-HONDA-SCOOPY-GEN-4-2017-2020', 'Honda', 'Scoopy gen 4 (2017-2020)', 108, 'SCOOTER', 'H02'),
    (7, 'SPCAT-HONDA-SCOOPY-GEN-5-2020-2024', 'Honda', 'Scoopy gen 5 (2020-2024)', 110, 'SCOOTER', 'H03'),
    (8, 'SPCAT-HONDA-SCOOPY-GEN-6-2024-NOW', 'Honda', 'Scoopy gen 6 (2024-Now)', 110, 'SCOOTER', 'H04'),
    (9, 'SPCAT-HONDA-GENIO', 'Honda', 'Genio', 110, 'SCOOTER', 'H05'),
    (10, 'SPCAT-HONDA-VARIO-125', 'Honda', 'Vario 125', 125, 'SCOOTER', 'H06'),
    (11, 'SPCAT-HONDA-VARIO-125-STREET', 'Honda', 'Vario 125 Street', 125, 'SCOOTER', 'H06'),
    (12, 'SPCAT-HONDA-VARIO-150', 'Honda', 'Vario 150', 149, 'SCOOTER', 'H07'),
    (13, 'SPCAT-HONDA-VARIO-EVO-160-CBS', 'Honda', 'Vario Evo 160 CBS', 157, 'SCOOTER', 'H08'),
    (14, 'SPCAT-HONDA-VARIO-EVO-160-ABS', 'Honda', 'Vario Evo 160 ABS', 157, 'SCOOTER', 'H08'),
    (15, 'SPCAT-HONDA-STYLO-160-ABS', 'Honda', 'Stylo 160 ABS', 157, 'SCOOTER', 'H09'),
    (16, 'SPCAT-HONDA-STYLO-160-CBS', 'Honda', 'Stylo 160 CBS', 157, 'SCOOTER', 'H09'),
    (17, 'SPCAT-HONDA-PCX-150-CBS', 'Honda', 'PCX 150 CBS', 149, 'SCOOTER', 'H10'),
    (18, 'SPCAT-HONDA-PCX-150-ABS', 'Honda', 'PCX 150 ABS', 149, 'SCOOTER', 'H10'),
    (19, 'SPCAT-HONDA-PCX-160-CBS', 'Honda', 'PCX 160 CBS', 157, 'SCOOTER', 'H11'),
    (20, 'SPCAT-HONDA-PCX-160-ABS', 'Honda', 'PCX 160 ABS', 157, 'SCOOTER', 'H11'),
    (21, 'SPCAT-HONDA-PCX-ROADSYCN', 'Honda', 'PCX Roadsycn', 157, 'SCOOTER', 'H11'),
    (22, 'SPCAT-HONDA-ADV-150-ABS', 'Honda', 'ADV 150 ABS', 149, 'SCOOTER', 'H12'),
    (23, 'SPCAT-HONDA-ADV-150-CBS', 'Honda', 'ADV 150 CBS', 149, 'SCOOTER', 'H12'),
    (24, 'SPCAT-HONDA-ADV-160-ABS', 'Honda', 'ADV 160 ABS', 157, 'SCOOTER', 'H13'),
    (25, 'SPCAT-HONDA-ADV-160-CBS', 'Honda', 'ADV 160 CBS', 157, 'SCOOTER', 'H13'),
    (26, 'SPCAT-HONDA-ADV-160-ROADSYCN', 'Honda', 'ADV 160 Roadsycn', 157, 'SCOOTER', 'H13'),
    (27, 'SPCAT-HONDA-FORZA', 'Honda', 'Forza', 249, 'SCOOTER', 'H14'),
    (28, 'SPCAT-HONDA-CB-150-R-STREETFIRE', 'Honda', 'CB 150 R Streetfire', 149, 'MOTORCYCLE', 'H15'),
    (29, 'SPCAT-HONDA-CB-150-X', 'Honda', 'CB 150 X', 149, 'MOTORCYCLE', 'H16'),
    (30, 'SPCAT-HONDA-CRF-150L', 'Honda', 'CRF 150L', 149, 'MOTORCYCLE', 'H17'),
    (31, 'SPCAT-HONDA-CBR-150-R', 'Honda', 'CBR 150 R', 149, 'MOTORCYCLE', 'H18'),
    (32, 'SPCAT-HONDA-CBR-150-R-ABS', 'Honda', 'CBR 150 R ABS', 149, 'MOTORCYCLE', 'H18'),
    (33, 'SPCAT-HONDA-CBR-250-RR', 'Honda', 'CBR 250 RR', 250, 'MOTORCYCLE', 'H19'),
    (34, 'SPCAT-HONDA-CRF-250-L', 'Honda', 'CRF 250 L', 250, 'MOTORCYCLE', 'H20'),
    (35, 'SPCAT-HONDA-CRF-250-RALLY', 'Honda', 'CRF 250 RALLY', 250, 'MOTORCYCLE', 'H21'),
    (38, 'SPCAT-KAWASAKI-NINJA-250', 'Kawasaki', 'Ninja 250', 249, 'MOTORCYCLE', 'K01'),
    (39, 'SPCAT-KAWASAKI-NINJA-250-ABS-SE', 'Kawasaki', 'Ninja 250 ABS SE', 249, 'MOTORCYCLE', 'K01'),
    (40, 'SPCAT-KAWASAKI-NINJA-ZX-25-RR', 'Kawasaki', 'Ninja ZX-25 RR', 250, 'MOTORCYCLE', 'K02'),
    (41, 'SPCAT-KAWASAKI-NINJA-ZX-25-R-SE', 'Kawasaki', 'Ninja ZX-25 R SE', 250, 'MOTORCYCLE', 'K02'),
    (42, 'SPCAT-KAWASAKI-NINJA-ZX-25-R', 'Kawasaki', 'Ninja ZX-25 R', 250, 'MOTORCYCLE', 'K02'),
    (43, 'SPCAT-KAWASAKI-NINJA-ZX-25-R-ABS', 'Kawasaki', 'Ninja ZX-25 R ABS', 250, 'MOTORCYCLE', 'K02'),
    (44, 'SPCAT-KAWASAKI-Z-250', 'Kawasaki', 'Z-250', 249, 'MOTORCYCLE', 'K03'),
    (45, 'SPCAT-KAWASAKI-Z-250-ABS', 'Kawasaki', 'Z-250 ABS', 249, 'MOTORCYCLE', 'K03'),
    (46, 'SPCAT-KAWASAKI-VERSYS-X-250', 'Kawasaki', 'Versys-X 250', 249, 'MOTORCYCLE', 'K04'),
    (47, 'SPCAT-KAWASAKI-VERSYS-250', 'Kawasaki', 'Versys 250', 249, 'MOTORCYCLE', 'K04'),
    (48, 'SPCAT-KAWASAKI-W-175', 'Kawasaki', 'W-175', 177, 'MOTORCYCLE', 'K05'),
    (49, 'SPCAT-KAWASAKI-W-175-ABS', 'Kawasaki', 'W-175 ABS', 177, 'MOTORCYCLE', 'K05'),
    (50, 'SPCAT-KAWASAKI-MEGURO-S1', 'Kawasaki', 'Meguro S1', 233, 'MOTORCYCLE', 'K06'),
    (51, 'SPCAT-KAWASAKI-D-TRACKER-X', 'Kawasaki', 'D-Tracker X', 249, 'MOTORCYCLE', 'K07'),
    (52, 'SPCAT-KAWASAKI-KLX-150', 'Kawasaki', 'KLX 150', 144, 'MOTORCYCLE', 'K08'),
    (53, 'SPCAT-KAWASAKI-KLX-150-SM', 'Kawasaki', 'KLX 150 SM', 144, 'MOTORCYCLE', 'K09'),
    (54, 'SPCAT-KAWASAKI-KLX-230', 'Kawasaki', 'KLX 230', 233, 'MOTORCYCLE', 'K10'),
    (55, 'SPCAT-KAWASAKI-KLX-250', 'Kawasaki', 'KLX 250', 249, 'MOTORCYCLE', 'K11'),
    (58, 'SPCAT-YAMAHA-AEROX-ABS', 'Yamaha', 'Aerox ABS', 155, 'SCOOTER', 'Y01'),
    (59, 'SPCAT-YAMAHA-AEROX-CBS', 'Yamaha', 'Aerox CBS', 155, 'SCOOTER', 'Y01'),
    (60, 'SPCAT-YAMAHA-AEROX-TURBO', 'Yamaha', 'Aerox Turbo', 155, 'SCOOTER', 'Y01'),
    (61, 'SPCAT-YAMAHA-FAZZIO', 'Yamaha', 'Fazzio', 125, 'SCOOTER', 'Y02'),
    (62, 'SPCAT-YAMAHA-FINO-125', 'Yamaha', 'Fino 125', 125, 'SCOOTER', 'Y03'),
    (63, 'SPCAT-YAMAHA-FREEGO-110', 'Yamaha', 'FreeGo 110', 50, 'SCOOTER', 'F02'),
    (64, 'SPCAT-YAMAHA-FREEGO-125', 'Yamaha', 'FreeGo 125', 125, 'SCOOTER', 'Y04'),
    (65, 'SPCAT-YAMAHA-GRAND-FILANO', 'Yamaha', 'Grand Filano', 125, 'SCOOTER', 'Y05'),
    (66, 'SPCAT-YAMAHA-GEAR-125', 'Yamaha', 'Gear 125', 125, 'SCOOTER', 'Y06'),
    (67, 'SPCAT-YAMAHA-GEAR-ULTIMA', 'Yamaha', 'Gear Ultima', 125, 'SCOOTER', 'Y07'),
    (68, 'SPCAT-YAMAHA-NMAX-NEW-ABS', 'Yamaha', 'Nmax New ABS', 155, 'SCOOTER', 'Y08'),
    (69, 'SPCAT-YAMAHA-NMAX-NEW-CBS', 'Yamaha', 'Nmax New CBS', 155, 'SCOOTER', 'Y08'),
    (70, 'SPCAT-YAMAHA-NMAX-TURBO', 'Yamaha', 'Nmax Turbo', 155, 'SCOOTER', 'Y08'),
    (71, 'SPCAT-YAMAHA-NMAX-NEO', 'Yamaha', 'Nmax Neo', 155, 'SCOOTER', 'Y08'),
    (72, 'SPCAT-YAMAHA-LEXI-125', 'Yamaha', 'Lexi 125', 125, 'SCOOTER', 'Y09'),
    (73, 'SPCAT-YAMAHA-LEXI-155-ABS', 'Yamaha', 'Lexi 155 ABS', 155, 'SCOOTER', 'Y10'),
    (74, 'SPCAT-YAMAHA-LEXI-155-CBS', 'Yamaha', 'Lexi 155 CBS', 155, 'SCOOTER', 'Y10'),
    (75, 'SPCAT-YAMAHA-MIO-M3-125', 'Yamaha', 'Mio M3 125', 125, 'SCOOTER', 'Y11'),
    (76, 'SPCAT-YAMAHA-XMAX-250', 'Yamaha', 'Xmax 250', 250, 'SCOOTER', 'Y12'),
    (77, 'SPCAT-YAMAHA-XMAX-250-TECH-MAX', 'Yamaha', 'Xmax 250 Tech Max', 250, 'SCOOTER', 'Y12'),
    (78, 'SPCAT-YAMAHA-XMAX-250-CONNECTED', 'Yamaha', 'Xmax 250 Connected', 250, 'SCOOTER', 'Y12'),
    (79, 'SPCAT-YAMAHA-X-RIDE', 'Yamaha', 'X-Ride', 50, 'SCOOTER', 'F03'),
    (80, 'SPCAT-YAMAHA-X-RIDE-125', 'Yamaha', 'X-Ride 125', 125, 'SCOOTER', 'Y13'),
    (81, 'SPCAT-YAMAHA-XSR-155', 'Yamaha', 'XSR 155', 155, 'MOTORCYCLE', 'Y14'),
    (82, 'SPCAT-YAMAHA-R-15', 'Yamaha', 'R-15', 155, 'MOTORCYCLE', 'Y15'),
    (83, 'SPCAT-YAMAHA-R-15-ABS', 'Yamaha', 'R-15 ABS', 155, 'MOTORCYCLE', 'Y15'),
    (84, 'SPCAT-YAMAHA-R-25', 'Yamaha', 'R-25', 250, 'MOTORCYCLE', 'Y16'),
    (85, 'SPCAT-YAMAHA-R-25-ABS', 'Yamaha', 'R-25 ABS', 250, 'MOTORCYCLE', 'Y16'),
    (86, 'SPCAT-YAMAHA-MT-15', 'Yamaha', 'MT-15', 155, 'MOTORCYCLE', 'Y15'),
    (87, 'SPCAT-YAMAHA-MT-25', 'Yamaha', 'MT-25', 250, 'MOTORCYCLE', 'Y16'),
    (88, 'SPCAT-YAMAHA-WR-155-R', 'Yamaha', 'WR 155 R', 155, 'MOTORCYCLE', 'Y17'),
    (91, 'SPCAT-TVS-CALLISTO-110', 'TVS', 'Callisto 110', 113, 'SCOOTER', 'T01'),
    (92, 'SPCAT-TVS-CALLISTO-125', 'TVS', 'Callisto 125', 125, 'SCOOTER', 'T02'),
    (93, 'SPCAT-TVS-RONIN', 'TVS', 'RONIN', 225, 'MOTORCYCLE', 'T03'),
    (94, 'SPCAT-TVS-RONIN-ABS', 'TVS', 'RONIN ABS', 225, 'MOTORCYCLE', 'T03'),
    (97, 'SPCAT-ROYAL-ENFIELD-CLASSIC-350', 'Royal Enfield', 'Classic 350', 349, 'MOTORCYCLE', 'R01'),
    (98, 'SPCAT-ROYAL-ENFIELD-HIMALAYAN-450', 'Royal Enfield', 'Himalayan 450', 452, 'MOTORCYCLE', 'R02'),
    (99, 'SPCAT-ROYAL-ENFIELD-METEOR-350', 'Royal Enfield', 'Meteor 350', 349, 'MOTORCYCLE', 'R03'),
    (102, 'SPCAT-QJ-MOTOR-SRV-200-MT', 'QJ Motor', 'SRV 200 MT', 197, 'MOTORCYCLE', 'Q01'),
    (103, 'SPCAT-QJ-MOTOR-SRV-250-AMT', 'QJ Motor', 'SRV 250 AMT', 249, 'MOTORCYCLE', 'Q02'),
    (104, 'SPCAT-QJ-MOTOR-SRV-250-LIBERO', 'QJ Motor', 'SRV 250 Libero', 249, 'MOTORCYCLE', 'Q03'),
    (105, 'SPCAT-QJ-MOTOR-FORT-180-ADVENTURE', 'QJ Motor', 'Fort 180 Adventure', 175, 'SCOOTER', 'Q04'),
    (106, 'SPCAT-QJ-MOTOR-FORT-250', 'QJ Motor', 'Fort 250', 250, 'SCOOTER', 'Q05'),
    (107, 'SPCAT-QJ-MOTOR-FORT-250-ADVENTURE', 'QJ Motor', 'Fort 250 Adventure', 249, 'SCOOTER', 'Q06'),
    (108, 'SPCAT-QJ-MOTOR-TOURINE-250-DX', 'QJ Motor', 'Tourine 250 DX', 249, 'MOTORCYCLE', 'Q07'),
    (111, 'SPCAT-SUZUKI-ACCESS-125', 'Suzuki', 'Access 125', 124, 'SCOOTER', 'S01'),
    (112, 'SPCAT-SUZUKI-BURGMAN-STREET-125-EX', 'Suzuki', 'Burgman Street 125 EX', 124, 'SCOOTER', 'S02'),
    (113, 'SPCAT-SUZUKI-NEX-II', 'Suzuki', 'Nex II', 113, 'SCOOTER', 'S03'),
    (114, 'SPCAT-SUZUKI-NEX-CROSSOVER', 'Suzuki', 'Nex Crossover', 113, 'SCOOTER', 'S03'),
    (115, 'SPCAT-SUZUKI-ADDRESS-FI', 'Suzuki', 'Address FI', 113, 'SCOOTER', 'S03'),
    (116, 'SPCAT-SUZUKI-GSX-S150', 'Suzuki', 'GSX-S150', 147, 'MOTORCYCLE', 'S04'),
    (117, 'SPCAT-SUZUKI-GSX-R150', 'Suzuki', 'GSX-R150', 147, 'MOTORCYCLE', 'S05'),
    (118, 'SPCAT-SUZUKI-V-STORM-250-SX', 'Suzuki', 'V-Storm 250 SX', 249, 'MOTORCYCLE', 'S06'),
    (120, 'SPCAT-CFMOTO-450-MT', 'CFMoto', '450 MT', 449, 'MOTORCYCLE', 'C01');

DROP TEMPORARY TABLE IF EXISTS sp_catalog_guard;
CREATE TEMPORARY TABLE sp_catalog_guard (
    ok TINYINT NOT NULL,
    CONSTRAINT ck_sp_catalog_preconditions CHECK (ok = 1)
) ENGINE=InnoDB;

SELECT COUNT(*), COUNT(DISTINCT brand)
  INTO @sp_catalog_source_count, @sp_catalog_brand_count
  FROM sp_catalog_source;

-- 새 ID가 다른 기존 모델을 가리키는 경우 원본/ID를 확인하고 중단한다.
SELECT COUNT(*) INTO @sp_catalog_id_conflicts
  FROM sp_catalog_source s JOIN MSP_VEHICLE_MODEL m ON m.model_id = s.model_id
 WHERE NOT (
     CONVERT(TRIM(m.brand) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.brand
     AND CONVERT(TRIM(m.model_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.model_name
 );

SET @sp_catalog_ok = COALESCE(
    DATABASE() = 'RIDERLOG_V2_DATA_TEST'
    AND @sp_catalog_source_count = 105
    AND @sp_catalog_brand_count = 8
    AND @sp_catalog_id_conflicts = 0
    AND EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = DATABASE() AND table_name = 'MSP_VEHICLE_MODEL'
           AND engine = 'InnoDB'
    ), 0);

SELECT DATABASE() AS target_database, @sp_catalog_source_count AS source_models,
       @sp_catalog_brand_count AS source_brands, @sp_catalog_id_conflicts AS id_conflicts,
       @sp_catalog_ok AS preconditions_ok;
INSERT INTO sp_catalog_guard (ok) VALUES (@sp_catalog_ok);

START TRANSACTION;

-- 한 번의 INSERT만 수행한다. 같은 브랜드/모델이 있으면 기존 ID/cc/활성 상태 등 모두 보존한다.
INSERT INTO MSP_VEHICLE_MODEL
    (model_id, brand, model_name, cc, vehicle_type, model_image_key,
     is_delivery_supported, is_active, created_at, updated_at)
SELECT s.model_id, s.brand, s.model_name, s.cc, s.vehicle_type, NULL,
       0, 1, @sp_catalog_now, @sp_catalog_now
  FROM sp_catalog_source s
  LEFT JOIN MSP_VEHICLE_MODEL m
    ON CONVERT(TRIM(m.brand) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.brand
   AND CONVERT(TRIM(m.model_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.model_name
 WHERE @sp_catalog_ok = 1
   AND m.model_id IS NULL;
SET @sp_catalog_inserted = ROW_COUNT();

SELECT COUNT(DISTINCT s.source_row) INTO @sp_catalog_matched
  FROM sp_catalog_source s JOIN MSP_VEHICLE_MODEL m
    ON CONVERT(TRIM(m.brand) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.brand
   AND CONVERT(TRIM(m.model_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.model_name;

-- 105개 원본 모델이 모두 연결된 경우만 완료한다.
INSERT INTO sp_catalog_guard (ok) VALUES (
    COALESCE(@sp_catalog_ok = 1 AND @sp_catalog_matched = 105, 0)
);
COMMIT;

SELECT @sp_catalog_inserted AS inserted_models,
       @sp_catalog_source_count - @sp_catalog_inserted AS existing_models_preserved,
       @sp_catalog_matched AS matched_source_models;

-- 브랜드별 요청 모델 수와 활성 상태를 확인한다. 기존 DB 전체 모델 수는 이보다 많을 수 있다.
SELECT s.brand, COUNT(DISTINCT s.source_row) AS source_models,
       COUNT(DISTINCT CASE WHEN m.is_active = 1 THEN s.source_row END) AS active_source_models
  FROM sp_catalog_source s LEFT JOIN MSP_VEHICLE_MODEL m
    ON CONVERT(TRIM(m.brand) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.brand
   AND CONVERT(TRIM(m.model_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.model_name
 GROUP BY s.brand ORDER BY s.brand;

-- 실제 저장/보존 결과. expected_cc와 stored_cc가 다르면 아래 별도 결과에도 표시된다.
SELECT s.source_row, m.model_id, m.brand, m.model_name,
       s.cc AS expected_cc, m.cc AS stored_cc, m.vehicle_type, m.is_active, s.spec_ref
  FROM sp_catalog_source s JOIN MSP_VEHICLE_MODEL m
    ON CONVERT(TRIM(m.brand) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.brand
   AND CONVERT(TRIM(m.model_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.model_name
 ORDER BY s.source_row, m.model_id;

-- 미확정 기본값 사용 3개. 이미 존재하던 모델은 원래 cc를 유지할 수 있다.
SELECT source_row, brand, model_name, cc AS fallback_cc, spec_ref
  FROM sp_catalog_source WHERE spec_ref IN ('F01', 'F02', 'F03')
 ORDER BY source_row;

-- 기존 cc/비활성 상태를 보존한 항목만 출력한다. 이 SQL은 이를 변경하지 않는다.
SELECT s.source_row, m.model_id, m.brand, m.model_name,
       s.cc AS expected_cc, m.cc AS preserved_cc, m.is_active
  FROM sp_catalog_source s JOIN MSP_VEHICLE_MODEL m
    ON CONVERT(TRIM(m.brand) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.brand
   AND CONVERT(TRIM(m.model_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci = s.model_name
 WHERE m.cc IS NULL OR m.cc <> s.cc OR m.is_active <> 1
 ORDER BY s.source_row, m.model_id;

DROP TEMPORARY TABLE sp_catalog_guard;
DROP TEMPORARY TABLE sp_catalog_source;
