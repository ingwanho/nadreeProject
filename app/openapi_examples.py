"""Swagger request/response examples for the Nadree test database.

Secrets are deliberately represented by placeholders because this data is
served from the public OpenAPI document.
"""

TEST_SPOT = {
    "shopId": "00000000-0000-4000-8000-000000000101",
    "spotMasterId": "00000000-0000-4000-8000-000000000101",
    "spotCode": "NR_TEST_20260921-ORG01",
    "unitCode": "NR_TEST_20260921-ORG01",
    "spotName": "Nadree 테스트 최상위 조직",
    "phone": "+62-000-000-000",
    "location": {
        "address": "Test Organization Address",
        "zipCode": "80000",
        "latitude": -8.65,
        "longitude": 115.216,
    },
}

TEST_MODEL_125 = {
    "modelId": "NRTEST-MODEL-125",
    "brand": "Honda",
    "modelName": "Vario 125",
    "cc": 125,
    "vehicleType": "SCOOTER",
    "modelImageKey": "models/test-vario-125.jpg",
}

TEST_MODEL_155 = {
    "modelId": "NRTEST-MODEL-155",
    "brand": "Yamaha",
    "modelName": "NMAX 155",
    "cc": 155,
    "vehicleType": "SCOOTER",
    "modelImageKey": "models/test-nmax-155.jpg",
}

TEST_WEB_MODEL_125 = {
    "modelId": "NRTEST-WEB-MODEL-125",
    "brand": "Honda",
    "modelName": "Vario Web Test 125",
    "cc": 125,
    "vehicleType": "SCOOTER",
    "modelImageKey": "https://placehold.co/640x480/png?text=NRTEST-WEB-125",
}

TEST_WEB_MODEL_NO_DELIVERY = {
    "modelId": "NRTEST-WEB-MODEL-ND",
    "brand": "SYM",
    "modelName": "Cruiser No Delivery Test",
    "cc": 125,
    "vehicleType": "SCOOTER",
    "modelImageKey": "https://placehold.co/640x480/png?text=NRTEST-NO-DELIVERY",
}

TEST_PRICE = {
    "currency": "USD",
    "rentalDays": 3,
    "dailyFrom": 25,
    "dailyTo": 25,
    "dailyPriceFrom": 25,
    "dailyPriceTo": 25,
    "rentalFrom": 75,
    "rentalTo": 75,
    "pricingTiers": [{
        "priceType": "BASIC",
        "tierType": "BASIC",
        "minCc": 0,
        "maxCc": 125,
        "dailyPriceFrom": 25,
        "dailyPriceTo": 25,
    }],
    "deliveryStart": 0,
    "deliveryReturn": 0,
    "deliveryTotal": 0,
    "deliveryStartFee": 0,
    "deliveryReturnFee": 0,
    "deliveryTotalFee": 0,
    "totalOptions": [75],
    "totalFrom": 75,
    "totalTo": 75,
    "requestedTotal": 75,
    "calculatedTotalFrom": 75,
    "calculatedTotalTo": 75,
    "finalTotal": 75,
}

TEST_DELIVERY = {
    "deliveryRequestType": "START_AND_RETURN",
    "deliveryRegionId": 990000001,
    "pickupLocation": "Kuta Test Area",
    "returnLocation": "Kuta Test Area",
    "startDeliveryFee": 10,
    "returnDeliveryFee": 10,
    "deliveryTotalFee": 20,
}

TEST_WEB_DELIVERY = {
    "deliveryRequestType": "START_AND_RETURN",
    "deliveryRegionId": 990000002,
    "pickupLocation": "Canggu Test Area, Bali",
    "returnLocation": "Canggu Test Area, Bali",
    "startDeliveryFee": 15,
    "returnDeliveryFee": 15,
    "deliveryTotalFee": 30,
}

TEST_WEB_PRICE = {
    "currency": "USD",
    "rentalDays": 3,
    "dailyFrom": 25,
    "dailyTo": 45,
    "dailyPriceFrom": 25,
    "dailyPriceTo": 45,
    "rentalFrom": 75,
    "rentalTo": 135,
    "pricingTiers": [{
        "priceType": "BASIC",
        "tierType": "BASIC",
        "minCc": 0,
        "maxCc": 125,
        "dailyPriceFrom": 25,
        "dailyPriceTo": 25,
    }, {
        "priceType": "PREMIUM",
        "tierType": None,
        "minCc": None,
        "maxCc": None,
        "dailyPriceFrom": 45,
        "dailyPriceTo": 45,
    }],
    "deliveryStart": 15,
    "deliveryReturn": 15,
    "deliveryTotal": 30,
    "deliveryStartFee": 15,
    "deliveryReturnFee": 15,
    "deliveryTotalFee": 30,
    "totalOptions": [105, 165],
    "totalFrom": 105,
    "totalTo": 165,
    "requestedTotal": None,
    "calculatedTotalFrom": None,
    "calculatedTotalTo": None,
    "finalTotal": None,
}

TEST_WEB_REQUEST_PRICE = dict(TEST_WEB_PRICE, requestedTotal=105,
                              calculatedTotalFrom=105, calculatedTotalTo=165, finalTotal=105)

TEST_RECORD = {
    "recordType": "RESERVATION",
    "reservationId": "NRTEST-RES-APP-001",
    "bookingId": "NRTEST-RES-APP-001",
    "rentalContractId": None,
    "bookedNo": "BONRTEST-RES-APP-001",
    "reservationStatus": "APPROVED",
    "rentalStatus": None,
    "vehicleAssignmentStatus": "PROVISIONAL",
    "shopId": TEST_SPOT["shopId"],
    "spotMasterId": TEST_SPOT["spotMasterId"],
    "modelId": TEST_MODEL_155["modelId"],
    "paymentAvailability": "PAYMENT_REQUIRED",
    "spot": TEST_SPOT,
    "model": TEST_MODEL_155,
    "startDate": "2026-10-09",
    "returnDate": "2026-10-13",
    "actualStartTime": None,
    "actualEndTime": None,
    "deliveryRequestType": "PICKUP",
    "pickupLocation": None,
    "returnLocation": None,
    "delivery": {
        "deliveryRequestType": "PICKUP",
        "deliveryRegionId": None,
        "pickupLocation": None,
        "returnLocation": None,
        "startDeliveryFee": 0,
        "returnDeliveryFee": 0,
        "deliveryTotalFee": 0,
    },
    "price": dict(TEST_PRICE, dailyFrom=35, dailyTo=35, dailyPriceFrom=35,
                  dailyPriceTo=35, rentalFrom=140, rentalTo=140,
                  totalOptions=[140], totalFrom=140, totalTo=140,
                  requestedTotal=140, calculatedTotalFrom=140,
                  calculatedTotalTo=140, finalTotal=140,
                  pricingTiers=[dict(TEST_PRICE["pricingTiers"][0], maxCc=200,
                                    minCc=126, dailyPriceFrom=35, dailyPriceTo=35)]),
    "payment": None,
}


OPENAPI_EXAMPLES = {
    "Login": {
        "email": "nadree.test.admin@example.com",
        "password": "<test-password>",
        "fcmToken": "<real-device-fcm-token>",
    },
    "AdminSignup": {
        "loginId": "nadree.test.newmanager",
        "email": "nadree.test.newmanager@example.com",
        "password": "<test-password>",
        "name": "Nadree 테스트 일반관리자",
        "phone": "+62-000-000-001",
        "representativeEmail": "nadree.test.admin@example.com",
    },
    "Profile": {
        "name": "Nadree 테스트 대표관리자 수정",
        "email": "nadree.test.admin@example.com",
        "phone": "+62-000-000-000",
        "fcmToken": "<real-device-fcm-token>",
    },
    "FcmToken": {"fcmToken": "<real-device-fcm-token>"},
    "SpotCode": {"spotCode": "NR_TEST_20260921-ORG01"},
    "Email": {"email": "nadree.test.manager@example.com"},
    "AdminId": {"adminId": "00000000-0000-4000-8000-000000000202"},
    "Shop": {
        "shopName": "Nadree 테스트 최상위 조직",
        "location": "Test Organization Address",
        "introduction": "Nadree API 테스트 지점",
        "contact": "+62-000-000-000",
        "email": "nadree.test.admin@example.com",
        "deliveryServiceType": "START_AND_RETURN",
    },
    "RequestAction": {
        "email": "nadree.test.newmanager@example.com",
        "action": "APPROVE",
        "spotMasterId": TEST_SPOT["spotMasterId"],
    },
    "SpotCreate": {
        "spot_name": "Nadree 테스트 하위 지점",
        "unit_type": "spot",
        "parent_spot_id": TEST_SPOT["spotMasterId"],
        "phone": "+62-000-000-002",
        "biz_reg_num": "TEST-BIZ-CHILD-001",
        "address": "Kuta Test Area",
        "address_detail": "Test Shop 1",
        "zip_code": "80361",
        "lat": -8.717,
        "lng": 115.169,
        "contract_start": "2026-01-01",
        "contract_end": "2099-12-31",
    },
    "Page": {"page": 1, "pageSize": 20},
    "Calendar": {
        "page": 1,
        "pageSize": 20,
        "spotCode": TEST_SPOT["spotCode"],
        "startDate": "2026-10-10",
        "endDate": "2026-10-13",
        "modelId": "NRTEST-MODEL-125",
    },
    "Operations": {
        "page": 1,
        "pageSize": 20,
        "startDate": "2026-10-01",
        "endDate": "2026-10-31",
        "recordType": "RESERVATION",
    },
    "VehicleNumber": {"vehicleNumber": "DK-TEST-301"},
    "VehicleCreate": {
        "qrToken": "<server-generated-qr-token>",
        "brand": "Honda",
        "vehicleName": "Vario 125",
        "modelId": "NRTEST-MODEL-125",
        "plateNumber": "DK-TEST-305",
        "vehicleImageKey": "vehicles/test-305.jpg",
    },
    "Detach": {"vehicleNumber": "DK-TEST-301", "division": "QR"},
    "PriceChange": {"vehicleNumber": "DK-TEST-301", "priceType": "BASIC", "priceInfo": None},
    "Qr": {"qrCode": "<server-issued-qr-code>"},
    "Repair": {"vehicleNumber": "DK-TEST-302", "date": "2026-10-03", "reason": "정기 점검"},
    "Move": {"vehicleNumber": "DK-TEST-301", "spotCode": TEST_SPOT["spotCode"]},
    "BookingAction": {"bookedNo": "BONRTEST-RES-REQ-001", "action": "APPROVE"},
    "ReservationCancel": {"reservationId": "NRTEST-RES-REQ-001", "reason": "테스트 취소"},
    "RentApprove": {"qrCode": "<server-issued-qr-code>", "bookedNo": "BONRTEST-RES-APP-001"},
    "PassportUpload": {
        "bookedNo": "BONRTEST-RES-HAND-001",
        "contentType": "image/jpeg",
        "imageBase64": "<base64-of-already-masked-jpeg>",
        "masked": True,
    },
    "TierRange": {"minCc": 0, "maxCc": 125},
    "TierCreate": {"minCc": 0, "maxCc": 125, "price": 25, "type": "BASIC", "spotCode": TEST_SPOT["spotCode"]},
    "Delivery": {
        "spotCode": TEST_SPOT["spotCode"],
        "deliveryRegionId": 990000002,
        "isDeliveryEnabled": True,
        "startDeliveryFee": 15,
        "returnDeliveryFee": 15,
        "memo": "Nadree 웹 배송 테스트 지역",
    },
    "DeliveryDelete": {"spotDeliveryRegionId": 990000002},
    "NadriLogin": {"UID": "NRTEST-USER-001", "fcmToken": "<real-device-fcm-token>"},
    "NadriProfile": {"NAME": "Nadree Test Customer", "Age": 30, "GENDER": "M", "NATIONALITY": "KR"},
    "NadriAvailability": {
        "startDate": "2026-10-10", "returnDate": "2026-10-13", "cc": 125,
        "deliveryRequested": True, "pickupLocation": "Canggu Test Area, Bali",
        "returnLocation": "Canggu Test Area, Bali",
    },
    "NadriRentalRequest": {
        "spotMasterId": TEST_SPOT["spotMasterId"], "modelId": "NRTEST-WEB-MODEL-125",
        "startDate": "2026-10-25", "returnDate": "2026-10-28", "totalPrice": 105,
        "currency": "USD", "deliveryRequested": True,
        "pickupLocation": "Canggu Test Area, Bali", "returnLocation": "Canggu Test Area, Bali",
    },
    "NadriPaymentOrder": {"reservationId": "NRTEST-RES-APP-001"},
    "NadriPaymentCapture": {"paymentId": 2},
    "Status": {"status": "success"},
    "Error": {"status": "fail", "errorCode": "RESERVATION_NOT_APPROVED_FOR_PAYMENT"},
    "Admin": {
        "adminId": "00000000-0000-4000-8000-000000000201",
        "name": "Nadree 테스트 대표관리자",
        "email": "nadree.test.admin@example.com",
        "role": "rental_primary_admin",
    },
    "Tokens": {"status": "success", "accessToken": "<nadree-access-token>", "refreshToken": "<nadree-refresh-token>"},
    "CustomerProfile": {
        "uidToken": "NRTEST-USER-001", "name": "Nadree Test Customer", "age": 30,
        "gender": "M", "nationality": "KR",
    },
    "CustomerLocation": TEST_SPOT["location"],
    "CustomerSpot": TEST_SPOT,
    "CustomerModel": TEST_WEB_MODEL_125,
    "CustomerPricingTier": TEST_WEB_PRICE["pricingTiers"][0],
    "CustomerPrice": TEST_WEB_PRICE,
    "CustomerDelivery": TEST_WEB_DELIVERY,
    "CustomerRecord": TEST_RECORD,
    "CustomerUser": {
        "uidToken": "NRTEST-USER-001",
        "name": "Nadree Test Customer",
        "age": 30,
        "gender": "M",
        "nationality": "KR",
        "ongoingRequests": [TEST_RECORD],
    },
    "CustomerAvailabilityItem": {
        "shopId": TEST_SPOT["shopId"], "modelId": TEST_WEB_MODEL_125["modelId"],
        "spot": TEST_SPOT, "model": TEST_WEB_MODEL_125, "price": TEST_WEB_PRICE,
    },
    "CustomerAvailability": {
        "status": "success", "items": [{
            "shopId": TEST_SPOT["shopId"], "modelId": TEST_WEB_MODEL_125["modelId"],
            "spot": TEST_SPOT, "model": TEST_WEB_MODEL_125, "price": TEST_WEB_PRICE,
        }],
    },
    "CustomerLogin": {
        "status": "success", "isNewUser": False,
        "accessToken": "<nadree-user-access-token>", "refreshToken": "<nadree-user-refresh-token>",
        "user": dict({
            "uidToken": "NRTEST-USER-001", "name": "Nadree Test Customer", "age": 30,
            "gender": "M", "nationality": "KR",
        }, ongoingRequests=[TEST_RECORD]),
    },
    "CustomerProfileResult": {
        "status": "success", "user": {
            "uidToken": "NRTEST-USER-001", "name": "Nadree Test Customer", "age": 30,
            "gender": "M", "nationality": "KR",
        },
    },
    "CustomerRequest": {
        "status": "success", "reservationId": "<new-reservation-uuid>",
        "bookingId": "<new-reservation-uuid>", "bookedNo": "BO<new-reservation-uuid>",
        "reservationStatus": "REQUESTED", "vehicleAssignmentStatus": "SOFT_HOLD",
        "paymentAvailability": "WAITING_APPROVAL", "paymentStatus": "WAITING_APPROVAL",
        "shopId": TEST_SPOT["shopId"], "spotMasterId": TEST_SPOT["spotMasterId"],
        "modelId": TEST_WEB_MODEL_125["modelId"], "totalPrice": 105, "currency": "USD",
        "deliveryRequestType": "START_AND_RETURN", "spot": TEST_SPOT, "model": TEST_WEB_MODEL_125,
        "price": TEST_WEB_REQUEST_PRICE,
    },
    "CustomerPage": {"status": "success", "items": [TEST_RECORD], "page": 1, "pageSize": 20, "totalCount": 1, "hasNext": False},
    "CustomerPayment": {
        "status": "success", "paymentId": 2, "reservationId": "NRTEST-RES-HAND-001",
        "bookingId": "NRTEST-RES-HAND-001", "shopId": TEST_SPOT["shopId"],
        "paymentStatus": "PAID", "paypalOrderId": "NRTEST-ORDER-PAID-001",
        "paypalCaptureId": "NRTEST-CAPTURE-PAID-001", "approvalUrl": None,
        "totalPrice": 200, "serverTotalPrice": 200, "currency": "USD",
        "paymentDeadline": "2026-10-04T10:00:00+08:00", "canPay": False,
        "cannotPayReason": "PAYMENT_ALREADY_COMPLETED", "refundRequestedAmount": None,
        "payment": {"refundStatus": "NONE", "lastWebhookEventType": "PAYMENT.CAPTURE.COMPLETED"},
    },
    "CustomerAccountDeletion": {"status": "success", "deleted": True},
    "CustomerCancellation": {
        "status": "success", "reservationId": "NRTEST-RES-REQ-001",
        "bookedNo": "BONRTEST-RES-REQ-001", "reservationStatus": "CANCELED", "refundStatus": "REQUESTED",
        "refundRequestedAmount": 90, "refundReason": "CUSTOMER_REFUND_90_PERCENT",
    },
    "HierarchyItem": {
        "spot_master_id": TEST_SPOT["spotMasterId"], "unit_code": TEST_SPOT["unitCode"],
        "spot_name": TEST_SPOT["spotName"], "hierarchy_level": "org", "org_name": TEST_SPOT["spotName"],
        "region_name": None, "is_active": True, "manager_name": "Nadree 테스트 대표관리자",
    },
    "Applicant": {"email": "nadree.test.newmanager@example.com", "name": "Nadree 테스트 일반관리자"},
}

OPENAPI_EXAMPLES.update({
    "SignedInAdmin": dict(OPENAPI_EXAMPLES["Admin"], spotMasterId=TEST_SPOT["spotMasterId"]),
    "SignedIn": {
        "status": "success", "accessToken": "<nadree-access-token>", "refreshToken": "<nadree-refresh-token>",
        "admin": dict(OPENAPI_EXAMPLES["Admin"], spotMasterId=TEST_SPOT["spotMasterId"]),
    },
    "ProfileResult": {
        "status": "success", "adminId": "00000000-0000-4000-8000-000000000201",
        "name": "Nadree 테스트 대표관리자", "email": "nadree.test.admin@example.com",
    },
    "SpotResult": {
        "status": "success", "spotMasterId": TEST_SPOT["spotMasterId"],
        "spotName": TEST_SPOT["spotName"], "unitCode": TEST_SPOT["unitCode"], "isDeliverySupported": True,
    },
    "PrimaryResult": {"status": "success", "primaryAdminId": "00000000-0000-4000-8000-000000000202"},
    "Admins": {
        "status": "success", "admin": [OPENAPI_EXAMPLES["Admin"], {
            "adminId": "00000000-0000-4000-8000-000000000202", "name": "Nadree 테스트 일반관리자",
            "email": "nadree.test.manager@example.com", "role": "rental_manager",
        }],
    },
    "ShopResult": {"spotMasterId": TEST_SPOT["spotMasterId"], "deliveryServiceType": "START_AND_RETURN"},
    "HierarchyItem": {
        "spot_master_id": TEST_SPOT["spotMasterId"], "unit_code": TEST_SPOT["unitCode"],
        "spot_name": TEST_SPOT["spotName"], "hierarchy_level": "org", "org_name": TEST_SPOT["spotName"],
        "region_name": None, "is_active": True, "manager_name": "Nadree 테스트 대표관리자",
    },
    "Hierarchy": {"items": [OPENAPI_EXAMPLES["HierarchyItem"]], "total": 1},
    "CreatedSpot": {
        "spot_id": "00000000-0000-4000-8000-000000000102", "unit_code": "NR_TEST_20260921-ORG01-SP01",
        "spot_name": "Nadree 테스트 하위 지점", "hierarchy_level": "spot", "phone": "+62-000-000-002",
        "biz_reg_num": "TEST-BIZ-CHILD-001", "address": "Kuta Test Area", "zip_code": "80361",
        "lat": -8.717, "lng": 115.169, "contract_start": "2026-01-01", "contract_end": "2099-12-31",
        "is_active": True, "inviteCode": "NR_TEST_CHILD_INVITE_20261001",
    },
    "Applicant": {"email": "nadree.test.newmanager@example.com", "name": "Nadree 테스트 일반관리자"},
    "Applicants": {"status": "success", "admins": [OPENAPI_EXAMPLES["Applicant"]]},
    "AdminSignupResult": {
        "status": "success", "adminId": "<created-admin-uuid>", "requestId": "<request-uuid>",
        "spotMasterId": TEST_SPOT["spotMasterId"], "requestStatus": "REQUESTED",
    },
    "PassportUploadResult": {
        "status": "success", "bookedNo": "BONRTEST-RES-HAND-001", "available": True,
        "contentType": "image/jpeg", "sizeBytes": 184320,
        "uploadedAt": "2026-10-07T09:00:00+08:00",
        "downloadPath": "/nadreego/rent/passport/BONRTEST-RES-HAND-001",
    },
})


OPENAPI_RESPONSE_EXAMPLES = {
    ("GET", "/health/live"): {"status": "ok", "service": "nadree-api"},
    ("GET", "/health/ready"): {"status": "ok", "limitations": ["MFA_FLOW_NOT_IMPLEMENTED"]},
    ("POST", "/nadreego/shop/delivery"): {
        "status": True, "spotDeliveryRegionId": 990000002, "deliveryRegionId": 990000002,
        "isDeliveryEnabled": True, "startDeliveryFee": 15, "returnDeliveryFee": 15,
    },
    ("GET", "/nadreego/shop/delivery/regions"): {
        "status": True, "items": [{
            "deliveryRegionId": 990000001, "countryCode": "ID", "regionName": "Kuta Test Area",
            "parentRegionId": None, "regionLevel": "CITY", "regionCode": "NRTEST-KUTA",
            "sortOrder": 1, "isActive": True,
        }, {
            "deliveryRegionId": 990000002, "countryCode": "ID", "regionName": "Canggu Test Area",
            "parentRegionId": None, "regionLevel": "CITY", "regionCode": "NRTEST-CANGGU",
            "sortOrder": 2, "isActive": True,
        }], "page": 1, "pageSize": 100, "totalCount": 2,
    },
    ("GET", "/nadreego/shop/delivery"): {
        "status": True, "items": [{
            "spotDeliveryRegionId": 990000001, "deliveryRegionId": 990000001,
            "regionName": "Kuta Test Area", "regionCode": "NRTEST-KUTA",
            "isDeliveryEnabled": True, "startDeliveryFee": 10,
            "returnDeliveryFee": 10, "memo": "Nadree 테스트 배송 지역",
        }, {
            "spotDeliveryRegionId": 990000002, "deliveryRegionId": 990000002,
            "regionName": "Canggu Test Area", "regionCode": "NRTEST-CANGGU",
            "isDeliveryEnabled": True, "startDeliveryFee": 15,
            "returnDeliveryFee": 15, "memo": "Nadree 웹 배송 테스트 지역",
        }], "page": 1, "pageSize": 100, "totalCount": 2,
    },
    ("POST", "/nadreego/shop/deliveryDelete"): {"status": True},
    ("POST", "/nadreego/shop/tierCreate"): {
        "status": "success", "tier": {
            "minCc": 0, "maxCc": 125, "price": 25, "type": "BASIC",
            "spotCode": TEST_SPOT["spotCode"], "action": "UPDATED",
        },
    },
    ("GET", "/nadreego/shop/tierCreate"): {
        "status": "success", "tiers": [
            {"minCc": 0, "maxCc": 125, "price": 25, "type": "BASE", "spotCode": None},
            {"minCc": 126, "maxCc": 200, "price": 35, "type": "BASE", "spotCode": None},
            {"minCc": 0, "maxCc": 125, "price": 25, "type": "BASIC", "spotCode": TEST_SPOT["spotCode"]},
        ],
    },
    ("POST", "/nadreego/shop/tierDelete"): {"status": "success"},
    ("POST", "/nadreego/vehicle/create"): {
        "status": "success", "vehicleId": "<created-vehicle-uuid>", "iot": {},
        "brand": "Honda", "vehicleName": "Vario 125",
    },
    ("POST", "/nadreego/vehicle/qr/validate"): {
        "status": True, "errorCode": None,
        "data": {"vehicleId": "NRTEST-VEHICLE-301", "qrId": "<qr-id>", "qrStatus": "ACTIVE"},
    },
    ("POST", "/nadreego/vehicle/location"): {
        "status": "success", "geopoint": {"latitude": -8.65, "longitude": 115.216},
    },
    ("POST", "/nadreego/vehicle/repair"): {
        "status": True, "errorCode": None, "message": "success", "currentState": "MAINTENANCE",
        "changedAt": "2026-10-01T08:00:00+08:00", "changedBy": "00000000-0000-4000-8000-000000000201",
        "data": {"vehicleId": "NRTEST-VEHICLE-302", "vehicleStatus": "MAINTENANCE", "maintenanceUntil": "2026-10-03"},
    },
    ("POST", "/nadreego/vehicle/spotChange"): {
        "status": "success", "spotMasterId": TEST_SPOT["spotMasterId"],
    },
    ("POST", "/nadreego/brand"): {
        "brand": ["Honda", "SYM", "Yamaha"], "vehicle": [
            {"modelId": TEST_MODEL_125["modelId"], "brand": "Honda", "modelName": "Vario 125",
             "cc": 125, "modelImageKey": "models/test-vario-125.jpg", "vehicleCount": 3, "price": 25},
            {"modelId": TEST_WEB_MODEL_125["modelId"], "brand": "Honda", "modelName": "Vario Web Test 125",
             "cc": 125, "modelImageKey": TEST_WEB_MODEL_125["modelImageKey"], "vehicleCount": 2, "price": 25},
            {"modelId": TEST_WEB_MODEL_NO_DELIVERY["modelId"], "brand": "SYM",
             "modelName": "Cruiser No Delivery Test", "cc": 125,
             "modelImageKey": TEST_WEB_MODEL_NO_DELIVERY["modelImageKey"], "vehicleCount": 1, "price": 25},
            {"modelId": TEST_MODEL_155["modelId"], "brand": "Yamaha", "modelName": "NMAX 155",
             "cc": 155, "modelImageKey": "models/test-nmax-155.jpg", "vehicleCount": 1, "price": 35},
        ], "tier": [], "price": None, "page": 1, "pageSize": 20, "totalCount": 4, "hasNext": False,
    },
    ("POST", "/nadreego/vehicle/select"): {
        "status": True, "items": [{
            "vehicleId": "NRTEST-VEHICLE-301", "vehicleNo": "DK-TEST-301",
            "modelId": TEST_MODEL_125["modelId"], "modelName": "Vario 125", "vehicleStatus": "AVAILABLE",
        }, {
            "vehicleId": "NRTEST-VEHICLE-302", "vehicleNo": "DK-TEST-302",
            "modelId": TEST_MODEL_125["modelId"], "modelName": "Vario 125", "vehicleStatus": "MAINTENANCE",
        }, {
            "vehicleId": "NRTEST-VEHICLE-303", "vehicleNo": "DK-TEST-303",
            "modelId": TEST_MODEL_125["modelId"], "modelName": "Vario 125", "vehicleStatus": "ON_RENT",
        }, {
            "vehicleId": "NRTEST-VEHICLE-304", "vehicleNo": "DK-TEST-304",
            "modelId": TEST_MODEL_155["modelId"], "modelName": "NMAX 155", "vehicleStatus": "AVAILABLE",
        }, {
            "vehicleId": "NRTEST-WEB-BASIC-125", "vehicleNo": "DK-WEB-BASIC-125",
            "modelId": TEST_WEB_MODEL_125["modelId"], "modelName": "Vario Web Test 125", "vehicleStatus": "AVAILABLE",
        }, {
            "vehicleId": "NRTEST-WEB-PREMIUM-125", "vehicleNo": "DK-WEB-PREMIUM-125",
            "modelId": TEST_WEB_MODEL_125["modelId"], "modelName": "Vario Web Test 125", "vehicleStatus": "AVAILABLE",
        }, {
            "vehicleId": "NRTEST-WEB-NODELIVERY", "vehicleNo": "DK-WEB-NODELIVERY",
            "modelId": TEST_WEB_MODEL_NO_DELIVERY["modelId"], "modelName": "Cruiser No Delivery Test",
            "vehicleStatus": "AVAILABLE",
        }], "page": 1, "pageSize": 20, "totalCount": 7, "hasNext": False,
    },
    ("POST", "/nadreego/booking/action"): {
        "status": True, "errorCode": None, "message": "success", "currentState": "APPROVED",
        "changedAt": "2026-10-01T08:00:00+08:00", "changedBy": "00000000-0000-4000-8000-000000000201",
        "data": {"bookedNo": "BONRTEST-RES-REQ-001", "reservationStatus": "APPROVED", "vehicleAssignmentStatus": "PROVISIONAL"},
    },
    ("POST", "/nadreego/rent/approve"): {
        "status": True, "errorCode": None, "message": "success", "currentState": "ON_RENT",
        "changedAt": "2026-10-01T08:00:00+08:00", "changedBy": "00000000-0000-4000-8000-000000000201",
        "data": {"bookedNo": "BONRTEST-RES-APP-001", "rentalContractId": "<rental-contract-uuid>",
                 "contractStatus": "ON_RENT", "vehicleStatus": "ON_RENT", "plannedEndDate": "2026-10-13",
                 "reservationStatus": "HANDED_OVER", "vehicleAssignmentStatus": "LOCKED"},
    },
    ("PUT", "/nadreego/rent/passport"): {
        "status": "success", "bookedNo": "BONRTEST-RES-HAND-001", "available": True,
        "contentType": "image/jpeg", "sizeBytes": 184320,
        "uploadedAt": "2026-10-07T09:00:00+08:00",
        "downloadPath": "/nadreego/rent/passport/BONRTEST-RES-HAND-001",
    },
    ("POST", "/nadreego/vehicle/return"): {
        "status": True, "errorCode": None, "message": "success", "currentState": "RETURNED",
        "changedAt": "2026-10-01T08:00:00+08:00", "changedBy": "00000000-0000-4000-8000-000000000201",
        "data": {"rentalContractId": "NRTEST-CONTRACT-ONRENT", "actualEndTime": "2026-10-01T08:00:00+08:00",
                 "vehicleStatus": "AVAILABLE", "reservationStatus": "RETURNED", "vehicleAssignmentStatus": "RELEASED"},
    },
    ("POST", "/nadreego/booking/select"): {
        "status": True, "items": [{"bookedNo": "BONRTEST-RES-APP-001", "recordType": "RESERVATION",
                                     "reservationStatus": "APPROVED", "rentalStatus": None,
                                     "user": {"userId": "NRTEST-USER-001", "name": "Nadree Test Customer"}}],
        "page": 1, "pageSize": 20, "totalCount": 8, "hasNext": False,
    },
    ("POST", "/nadreego/main/calendar"): {
        "status": True, "items": [{"vehicleId": "NRTEST-VEHICLE-301", "vehicleNo": "DK-TEST-301",
                                     "modelId": TEST_MODEL_125["modelId"], "modelName": "Vario 125",
                                     "vehicleStatus": "AVAILABLE", "events": []}],
        "page": 1, "pageSize": 20, "totalCount": 7, "hasNext": False,
        "startDate": "2026-10-10", "endDate": "2026-10-13", "timeZone": "Asia/Makassar",
        "fetchedAt": "2026-10-01T08:00:00+08:00", "warnings": [],
    },
    ("GET", "/nadreego/main"): {
        "status": "success", "group": {"spotMasterId": TEST_SPOT["spotMasterId"],
        "spotCode": TEST_SPOT["spotCode"], "name": TEST_SPOT["spotName"]},
        "name": "Nadree 테스트 대표관리자", "totalVehicles": 7, "totalReservations": 2,
        "pending": 1, "chat": 0, "todayWork": [],
    },
    ("POST", "/nadreego/paypal/webhook"): {"status": True},
}

OPENAPI_REQUEST_EXAMPLES = {
    ("POST", "/nadreego/paypal/webhook"): {
        "id": "WH-TEST-EVENT-001", "event_version": "1.0", "create_time": "2026-10-01T00:00:00Z",
        "resource_type": "capture", "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "summary": "Test capture completed", "resource": {"id": "NRTEST-CAPTURE-PAID-001", "status": "COMPLETED"},
    },
}
