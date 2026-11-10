"""Swagger request/response examples for the Nadree test database.

Secrets are deliberately represented by placeholders because this data is
served from the public OpenAPI document.
"""
from app.onsite_requests import outcome as onsite_outcome

TEST_SPOT = {
    "shopId": "00000000-0000-4000-8000-000000000101",
    "spotMasterId": "00000000-0000-4000-8000-000000000101",
    "spotCode": "NR_TEST_20260921-ORG01",
    "unitCode": "NR_TEST_20260921-ORG01",
    "spotName": "Nadree Test Organization",
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
    "paymentMethod": "EXTERNAL", "onlinePaymentEnabled": False,
    "paymentAvailability": "EXTERNAL_PAYMENT", "paymentStatus": None,
    "paymentDeadline": None, "canPay": False, "canCapture": False,
    "cannotPayReason": "ONLINE_PAYMENT_NOT_REQUIRED",
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
        "name": "Nadree Test Manager",
        "phone": "+62-000-000-001",
        "representativeEmail": "nadree.test.admin@example.com",
    },
    "Profile": {
        "name": "Updated Nadree Test Representative",
        "email": "nadree.test.admin@example.com",
        "phone": "+62-000-000-000",
        "fcmToken": "<real-device-fcm-token>",
    },
    "FcmToken": {"fcmToken": "<real-device-fcm-token>"},
    "SpotCode": {"spotCode": "NR_TEST_20260921-ORG01"},
    "Email": {"email": "nadree.test.manager@example.com"},
    "AdminId": {"adminId": "00000000-0000-4000-8000-000000000202"},
    "Shop": {
        "shopName": "Nadree Test Organization",
        "location": "Test Organization Address",
        "introduction": "Nadree API Test Branch",
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
        "spot_name": "Nadree Test Child Branch",
        "email": "nadree.test.shop@example.com",
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
        "qrToken": "NDR-Ab12Cd34",
        "brand": "Honda",
        "vehicleName": "Vario 125",
        "modelId": "NRTEST-MODEL-125",
        "plateNumber": "DK-TEST-305",
        "vehicleImageKey": "vehicles/test-305.jpg",
    },
    "Detach": {"vehicleNumber": "DK-TEST-301", "division": "QR"},
    "QrLink": {"vehicleNumber": "DK-TEST-301", "qrToken": "NDR-Ab12Cd34"},
    "PriceChange": {"vehicleNumber": "DK-TEST-301", "priceType": "BASIC", "priceInfo": None},
    "Qr": {"qrCode": "NDR-Ab12Cd34"},
    "Lookup": {"qrCode": "NDR-Ab12Cd34", "reservationId": "NRTEST-RES-APP-001"},
    "Quote": {"qrCode": "NDR-Ab12Cd34", "returnDate": "2026-11-05"},
    "OnsiteRequest": {"qrCode": "NDR-Ab12Cd34", "returnDate": "2026-11-05",
        "clientRequestId": "11111111-2222-4333-8444-555555555555", "quoteToken": "<quoteToken-from-onsite-quote>"},
    "ReceiptRecovery": {"qrCode": "NDR-Ab12Cd34", "vehicleReturned": True, "reason": "Confirmed physical recovery of the vehicle and keys"},
    "Repair": {"vehicleNumber": "DK-TEST-302", "date": "2026-10-03", "reason": "Scheduled maintenance"},
    "Move": {"vehicleNumber": "DK-TEST-301", "spotCode": TEST_SPOT["spotCode"]},
    "BookingAction": {"bookedNo": "BONRTEST-RES-REQ-001", "action": "APPROVE"},
    "BookingLocationCorrection": {"bookedNo": "BONRTEST-RES-APP-001", "changeType": "CORRECTION", "target": "PICKUP",
        "previousLocation": TEST_SPOT["location"],
        "correctedLocation": {**TEST_SPOT["location"], "latitude": -8.65001},
        "reason": "Corrected the map pin for the same shop entrance"},
    "ReservationCancel": {"reservationId": "NRTEST-RES-REQ-001", "reason": "Test cancellation"},
    "RentApprove": {"qrCode": "NDR-Ab12Cd34", "bookedNo": "BONRTEST-RES-APP-001", "receiptRequired": True},
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
        "memo": "Nadree Web Delivery Test Region",
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
        "name": "Nadree Test Representative",
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
    "ReceiptInfo": {"requestType": "ONSITE", "customerReceiptRequired": True,
        "requestDeadline": "2026-11-04T00:00:00+08:00", "handedOverAt": "2026-11-03T15:00:00+08:00",
        "receiptDeadline": "2026-11-04T00:00:00+08:00", "receivedAt": None,
        "canReceive": True, "receiptBlockedReason": None, "vehicleRecoveryRequired": False},
    "CustomerQrLookup": {"status": "success", "vehicleId": "NRTEST-VEHICLE-001", "vehicleNo": "DK-TEST-301",
        "vehicleStatus": "DISABLED", "model": TEST_MODEL_155, "spot": TEST_SPOT,
        "reservationId": "NRTEST-RES-APP-001", "reservationStatus": "HANDOVER_PENDING", "vehicleMatch": "ASSIGNED",
        "requestType": "ADVANCE", "customerReceiptRequired": True,
        "handedOverAt": "2026-11-03T15:00:00+08:00", "receiptDeadline": "2026-11-04T00:00:00+08:00",
        "receivedAt": None, "canReceive": True, "receiptBlockedReason": None, "vehicleRecoveryRequired": False,
        "availableActions": ["CONFIRM_RECEIPT"]},
    "CustomerOnsiteQuote": {"status": "success", "vehicleId": "NRTEST-VEHICLE-001", "spot": TEST_SPOT,
        "startDate": "2026-11-03", "returnDate": "2026-11-05", "price": dict(TEST_PRICE,
            rentalDays=2, rentalFrom=50, rentalTo=50, totalOptions=[50], totalFrom=50, totalTo=50,
            requestedTotal=50, calculatedTotalFrom=50, calculatedTotalTo=50, finalTotal=50),
        "quoteExpiresAt": "2026-11-03T07:10:00+00:00", "quoteToken": "<signed-quote-token>"},
    "CustomerUser": {
        "uidToken": "NRTEST-USER-001",
        "name": "Nadree Test Customer",
        "age": 30,
        "gender": "M",
        "nationality": "KR",
        "ongoingRequests": [TEST_RECORD],
    },
    "CustomerAvailabilityItem": {
        "canRequest": True, "cannotRequestReason": None,
        "shopId": TEST_SPOT["shopId"], "modelId": TEST_WEB_MODEL_125["modelId"],
        "spot": TEST_SPOT, "model": TEST_WEB_MODEL_125, "price": TEST_WEB_PRICE,
    },
    "CustomerAvailability": {
        "status": "success", "items": [{
            "canRequest": True, "cannotRequestReason": None,
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
        "paymentAvailability": "WAITING_APPROVAL", "paymentStatus": None,
        "paymentMethod": "EXTERNAL", "onlinePaymentEnabled": False,
        "paymentDeadline": None, "canPay": False, "canCapture": False,
        "shopId": TEST_SPOT["shopId"], "spotMasterId": TEST_SPOT["spotMasterId"],
        "modelId": TEST_WEB_MODEL_125["modelId"], "totalPrice": 105, "currency": "USD",
        "deliveryRequestType": "START_AND_RETURN", "spot": TEST_SPOT, "model": TEST_WEB_MODEL_125,
        "price": TEST_WEB_REQUEST_PRICE,
    },
    "CustomerPage": {"status": "success", "items": [TEST_RECORD], "page": 1, "pageSize": 20, "totalCount": 1, "hasNext": False},
    "CustomerPayment": {
        "paymentMethod": "PAYPAL", "onlinePaymentEnabled": False,
        "paymentStateSource": "DATABASE", "providerStateChecked": False,
        "status": "success", "paymentId": 2, "reservationId": "NRTEST-RES-HAND-001",
        "bookingId": "NRTEST-RES-HAND-001", "shopId": TEST_SPOT["shopId"],
        "paymentStatus": "PAID", "paypalOrderId": "NRTEST-ORDER-PAID-001",
        "paypalCaptureId": "NRTEST-CAPTURE-PAID-001", "approvalUrl": None,
        "paypalOrderStatus": None, "nextAction": "DONE", "canCapture": False,
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
        "spot_master_id": "00000000-0000-4000-8000-000000000102", "unit_code": "NR_TEST_20260921-ORG01-R01",
        "spot_name": "Nadree Test Child Branch", "hierarchy_level": "region", "org_name": TEST_SPOT["spotName"],
        "region_name": "Nadree Test Child Branch", "is_active": True, "manager_name": None,
        "companyId": "NR_TEST_COMPANY", "parentSpotMasterId": TEST_SPOT["spotMasterId"],
        "canEditProfile": True, "canEditPricing": True, "canEditDelivery": True, "canCreateChild": True,
    },
    "Applicant": {"email": "nadree.test.newmanager@example.com", "name": "Nadree Test Manager"},
}

OPENAPI_EXAMPLES.update({
    "AdminAccountDeletion": {"status": "success", "deleted": True, "scope": "SELF",
        "spotMasterId": TEST_SPOT["spotMasterId"], "deletedAdminCount": 1, "deletedSpotCount": 0},
    "SignedInAdmin": dict(OPENAPI_EXAMPLES["Admin"], spotMasterId=TEST_SPOT["spotMasterId"]),
    "SignedIn": {
        "status": "success", "accessToken": "<nadree-access-token>", "refreshToken": "<nadree-refresh-token>",
        "admin": dict(OPENAPI_EXAMPLES["Admin"], spotMasterId=TEST_SPOT["spotMasterId"]),
    },
    "ProfileResult": {
        "status": "success", "adminId": "00000000-0000-4000-8000-000000000201",
        "name": "Nadree Test Representative", "email": "nadree.test.admin@example.com",
    },
    "SpotResult": {
        "status": "success", "spotMasterId": TEST_SPOT["spotMasterId"],
        "spotName": TEST_SPOT["spotName"], "unitCode": TEST_SPOT["unitCode"], "isDeliverySupported": True,
    },
    "PrimaryResult": {"status": "success", "primaryAdminId": "00000000-0000-4000-8000-000000000202"},
    "Admins": {
        "status": "success", "admin": [OPENAPI_EXAMPLES["Admin"], {
            "adminId": "00000000-0000-4000-8000-000000000202", "name": "Nadree Test Manager",
            "email": "nadree.test.manager@example.com", "role": "rental_manager",
        }],
    },
    "ShopResult": {"spotMasterId": TEST_SPOT["spotMasterId"], "deliveryServiceType": "START_AND_RETURN"},
    "HierarchyItem": {
        "spot_master_id": "00000000-0000-4000-8000-000000000102", "unit_code": "NR_TEST_20260921-ORG01-R01",
        "spot_name": "Nadree Test Child Branch", "hierarchy_level": "region", "org_name": TEST_SPOT["spotName"],
        "region_name": "Nadree Test Child Branch", "is_active": True, "manager_name": None,
        "companyId": "NR_TEST_COMPANY", "parentSpotMasterId": TEST_SPOT["spotMasterId"],
        "canEditProfile": True, "canEditPricing": True, "canEditDelivery": True, "canCreateChild": True,
    },
    "Hierarchy": {"items": [OPENAPI_EXAMPLES["HierarchyItem"]], "total": 1,
                  "currentSpotMasterId": TEST_SPOT["spotMasterId"], "companyId": "NR_TEST_COMPANY", "isCompanyPrimary": True},
    "CreatedSpot": {
        "email": "nadree.test.shop@example.com", "parentSpotMasterId": TEST_SPOT["spotMasterId"],
        "spot_id": "00000000-0000-4000-8000-000000000102", "unit_code": "NR_TEST_20260921-ORG01-R01",
        "spot_name": "Nadree Test Child Branch", "hierarchy_level": "region", "phone": "+62-000-000-002",
        "biz_reg_num": "TEST-BIZ-CHILD-001", "address": "Kuta Test Area", "zip_code": "80361",
        "lat": -8.717, "lng": 115.169, "contract_start": "2026-01-01", "contract_end": "2099-12-31",
        "is_active": True, "inviteCode": "A1B2C3D4",
    },
    "Applicant": {"email": "nadree.test.newmanager@example.com", "name": "Nadree Test Manager"},
    "Applicants": {"status": "success", "admins": [OPENAPI_EXAMPLES["Applicant"]]},
    "AdminSignupResult": {
        "status": "success", "adminId": "<created-admin-uuid>", "requestId": "<request-uuid>",
        "spotMasterId": TEST_SPOT["spotMasterId"], "requestStatus": "REQUESTED", "accountStatus": "PENDING_APPROVAL",
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
            "returnDeliveryFee": 10, "memo": "Nadree Delivery Test Region",
        }, {
            "spotDeliveryRegionId": 990000002, "deliveryRegionId": 990000002,
            "regionName": "Canggu Test Area", "regionCode": "NRTEST-CANGGU",
            "isDeliveryEnabled": True, "startDeliveryFee": 15,
            "returnDeliveryFee": 15, "memo": "Nadree Web Delivery Test Region",
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
        "status": "success", "vehicleId": "<created-vehicle-uuid>",
        "qr": {"qrId": "<qr-id>", "qrStatus": "ACTIVE"},
        "iot": {"sensorId": None, "sensorStatus": "NOT_LINKED"},
        "brand": "Honda", "vehicleName": "Vario 125",
    },
    ("POST", "/nadreego/vehicle/qr/link"): {
        "status": "success", "vehicleId": "NRTEST-VEHICLE-301",
        "qr": {"qrId": "<new-qr-id>", "qrStatus": "ACTIVE"},
    },
    ("POST", "/nadreego/vehicle/qr/validate"): {
        "status": True, "errorCode": None,
        "data": {"vehicleId": "NRTEST-VEHICLE-301", "qrId": "<qr-id>", "qrStatus": "ACTIVE",
                 "equipmentType": "QR_ONLY", "sensorId": None, "sensorStatus": "NOT_LINKED",
                 "vehicle": {"vehicleId": "NRTEST-VEHICLE-301", "vehicleNo": "DK-TEST-301", "vehicleStatus": "AVAILABLE"},
                 "currentBooking": None, "currentRental": None,
                 "availableActions": ["PRICE_CHANGE", "SPOT_CHANGE", "REPAIR", "QR_DELETE"]},
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
             "cc": 155, "modelImageKey": "models/test-nmax-155.jpg", "vehicleCount": 0, "price": 35},
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
        "status": True, "errorCode": None, "message": "success", "currentState": "HANDOVER_PENDING",
        "changedAt": "2026-11-03T15:00:00+08:00", "changedBy": "00000000-0000-4000-8000-000000000201",
        "data": {"bookedNo": "BONRTEST-RES-APP-001", "reservationId": "NRTEST-RES-APP-001",
                 "reservationStatus": "HANDOVER_PENDING", "vehicleAssignmentStatus": "LOCKED",
                 **OPENAPI_EXAMPLES["ReceiptInfo"], "requestType": "ADVANCE", "requestDeadline": None},
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
        "name": "Nadree Test Representative", "totalVehicles": 7, "totalReservations": 2,
        "pending": 1, "awaitingReceipt": 1, "chat": 0, "todayWork": [],
    },
    ("POST", "/nadreego/paypal/webhook"): {"status": True},
}

_ONSITE_RECORD = dict({**TEST_RECORD, **OPENAPI_EXAMPLES["ReceiptInfo"]}, startDate="2026-11-03", returnDate="2026-11-05",
    price=OPENAPI_EXAMPLES["CustomerOnsiteQuote"]["price"], reservationStatus="REQUESTED",
    vehicleAssignmentStatus="SOFT_HOLD", handedOverAt=None, receiptDeadline=None, receivedAt=None,
    canReceive=False, receiptBlockedReason="NOT_AWAITING_RECEIPT")
OPENAPI_RESPONSE_EXAMPLES.update({
    ("POST", "/api/v1/nadree/rental/qr/lookup"): OPENAPI_EXAMPLES["CustomerQrLookup"],
    ("POST", "/api/v1/nadree/rental/onsite/quote"): OPENAPI_EXAMPLES["CustomerOnsiteQuote"],
    ("POST", "/api/v1/nadree/rental/onsite/requests"): {"status": "success", "item": _ONSITE_RECORD,
        **onsite_outcome("11111111-2222-4333-8444-555555555555", "ACCEPTED")},
    ("GET", "/api/v1/nadree/rental/onsite/requests/{client_request_id}"): {"status": "success", "item": _ONSITE_RECORD,
        **onsite_outcome("11111111-2222-4333-8444-555555555555", "ACCEPTED")},
    ("POST", "/api/v1/nadree/rental/reservations/{reservation_id}/receive"): {"status": "success", "item": dict(
        _ONSITE_RECORD, recordType="RENTAL", reservationStatus="HANDED_OVER", rentalStatus="ON_RENT",
        rentalContractId="NRTEST-CONTRACT-RECEIVED", vehicleAssignmentStatus="LOCKED",
        handedOverAt="2026-11-03T15:00:00+08:00", receiptDeadline="2026-11-04T00:00:00+08:00",
        receivedAt="2026-11-03T15:05:00+08:00", actualStartTime="2026-11-03T15:05:00+08:00")},
    ("POST", "/nadreego/booking/{booked_no}/receipt-recovery"): {
        "status": True, "errorCode": None, "message": "success", "currentState": "CANCELED",
        "changedAt": "2026-11-04T09:00:00+08:00", "changedBy": "00000000-0000-4000-8000-000000000201",
        "data": {"bookedNo": "BONRTEST-RES-APP-001", "reservationStatus": "CANCELED", "vehicleStatus": "AVAILABLE"}},
})

OPENAPI_REQUEST_EXAMPLES = {
    ("POST", "/nadreego/paypal/webhook"): {
        "id": "WH-TEST-EVENT-001", "event_version": "1.0", "create_time": "2026-10-01T00:00:00Z",
        "resource_type": "capture", "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "summary": "Test capture completed", "resource": {"id": "NRTEST-CAPTURE-PAID-001", "status": "COMPLETED"},
    },
}

# Named examples show only the state-dependent fields consumers need to bind.
_REQUEST_KEY = "11111111-2222-4333-8444-555555555555"
_CUSTOMER_BASE = "/api/v1/nadree/rental"
_PROCESSING = {"status": "success", "item": None, "errorCode": None, **onsite_outcome(_REQUEST_KEY, "PROCESSING")}
_REJECTED = {"status": "success", "item": None, **onsite_outcome(_REQUEST_KEY, "REJECTED", code="ONSITE_QUOTE_EXPIRED")}
_ADMIN_PENDING = {
    "bookedNo": "BONRTEST-RES-APP-001", "reservationId": "NRTEST-RES-APP-001", "recordType": "RESERVATION",
    "vehicleId": "NRTEST-NDR-ONLY-001", "reservationStatus": "HANDOVER_PENDING", "rentalStatus": None,
    **OPENAPI_EXAMPLES["ReceiptInfo"], "canHandOver": False, "handoverBlockedReason": "RESERVATION_NOT_APPROVED",
    "availableActions": ["RECOVER_VEHICLE"],
    "reservation": {"reservationId": "NRTEST-RES-APP-001", "assignedVehicleId": "NRTEST-NDR-ONLY-001",
        "assignmentStatus": "LOCKED", "startDatetime": "2026-11-03T14:00:00+08:00", "endDatetime": "2026-11-05T23:59:59+08:00"},
    "vehicle": {"vehicleId": "NRTEST-NDR-ONLY-001", "vehicleNo": "DK-NDR-ONLY-001", "vehicleStatus": "DISABLED"},
    "rental": None,
}
_ADMIN_EXPIRED = dict(_ADMIN_PENDING, reservationStatus="EXPIRED", canReceive=False,
    receiptBlockedReason="RECEIPT_DEADLINE_EXPIRED", vehicleRecoveryRequired=True)
_ADMIN_APPROVED = dict(_ADMIN_PENDING, reservationStatus="APPROVED", handedOverAt=None,
    receiptDeadline=None, canReceive=False, receiptBlockedReason="NOT_AWAITING_RECEIPT", canHandOver=True,
    handoverBlockedReason=None, availableActions=["RENT_APPROVE", "CANCEL"],
    reservation=dict(_ADMIN_PENDING["reservation"], assignmentStatus="PROVISIONAL"),
    vehicle=dict(_ADMIN_PENDING["vehicle"], vehicleStatus="AVAILABLE"))
_ADMIN_REQUESTED = dict(_ADMIN_APPROVED, reservationStatus="REQUESTED", vehicleId=None,
    canHandOver=False, handoverBlockedReason="RESERVATION_NOT_APPROVED", availableActions=["APPROVE", "REJECT"],
    reservation=dict(_ADMIN_APPROVED["reservation"], assignedVehicleId=None, assignmentStatus="SOFT_HOLD"), vehicle={})
_ADMIN_RENTAL = dict(_ADMIN_PENDING, reservationStatus="HANDED_OVER", recordType="RENTAL", rentalStatus="ON_RENT",
    receivedAt="2026-11-03T15:05:00+08:00", canReceive=False, receiptBlockedReason="NOT_AWAITING_RECEIPT",
    handoverBlockedReason="RESERVATION_ALREADY_HANDED_OVER", availableActions=["RETURN"],
    vehicle=dict(_ADMIN_PENDING["vehicle"], vehicleStatus="ON_RENT"),
    rental={"rentalContractId": "NRTEST-CONTRACT-RECEIVED", "contractStatus": "ON_RENT",
        "actualStartTime": "2026-11-03T15:05:00+08:00", "actualEndTime": None, "plannedEndDate": "2026-11-05"})


def _page_example(item):
    return {"status": True, "items": [item], "page": 1, "pageSize": 20, "totalCount": 1, "hasNext": False}


def _booking_example(item):
    return {key: item[key] for key in ("bookedNo", "reservationId", "vehicleId", "requestType",
        "requestDeadline", "customerReceiptRequired", "handedOverAt", "receiptDeadline", "receivedAt",
        "canReceive", "receiptBlockedReason", "vehicleRecoveryRequired", "reservationStatus", "canHandOver",
        "handoverBlockedReason", "availableActions")} | {
            "assignmentStatus": "LOCKED", "startDatetime": item["reservation"]["startDatetime"],
            "endDatetime": item["reservation"]["endDatetime"]}


OPENAPI_STATUS_EXAMPLES = {
    ("DELETE", "/nadreego/admin/account"): {
        200: {
            "general": OPENAPI_EXAMPLES["AdminAccountDeletion"],
            "primary": {"status": "success", "deleted": True, "scope": "SUBTREE",
                "spotMasterId": TEST_SPOT["spotMasterId"], "deletedAdminCount": 4, "deletedSpotCount": 2},
        },
        401: {"invalidSession": {"status": "fail", "errorCode": "AUTH_REQUIRED"}},
        403: {"missingDirectScope": {"status": "fail", "errorCode": "SPOT_ACCESS_DENIED"}},
        409: {"unfinishedWorkInSubtree": {"status": "fail", "errorCode": "DELETION_OBLIGATIONS_REMAIN",
                "nextAction": "SETTLE_OUTSTANDING_WORK"},
            "primaryNeededForTransfer": {"status": "fail", "errorCode": "PRIMARY_ADMIN_REQUIRED_FOR_HANDOVER"}},
        503: {"chatRevocationFailed": {"status": "fail", "errorCode": "CHAT_SYNC_FAILED"}},
    },
    ("POST", _CUSTOMER_BASE + "/onsite/requests"): {
        202: {"processing": _PROCESSING},
        409: {code: {"status": "fail", **onsite_outcome(_REQUEST_KEY, "REJECTED", code=code)} for code in
            ("ONSITE_QUOTE_EXPIRED", "ONSITE_QUOTE_CHANGED", "VEHICLE_UNAVAILABLE", "ONSITE_REQUEST_CLOSED")},
        503: {"unavailableOutcomeUnknown": {"status": "fail", "errorCode": "DATABASE_UNAVAILABLE"}},
    },
    ("GET", _CUSTOMER_BASE + "/onsite/requests/{client_request_id}"): {
        200: {"accepted": OPENAPI_RESPONSE_EXAMPLES[("POST", _CUSTOMER_BASE + "/onsite/requests")], "rejected": _REJECTED},
        202: {"processing": _PROCESSING},
        404: {"notFoundIsNotFinal": {"status": "fail", "errorCode": "ONSITE_REQUEST_NOT_FOUND",
            **onsite_outcome(_REQUEST_KEY, "UNKNOWN")}},
        503: {"interruptedAttempt": {"status": "fail", "errorCode": "ONSITE_REQUEST_OUTCOME_UNKNOWN",
            **onsite_outcome(_REQUEST_KEY, "UNKNOWN")}},
    },
    ("POST", _CUSTOMER_BASE + "/onsite/requests/{client_request_id}/close"): {
        200: {"closed": dict(_REJECTED, errorCode="ONSITE_REQUEST_CLOSED"),
            "alreadyAccepted": OPENAPI_RESPONSE_EXAMPLES[("POST", _CUSTOMER_BASE + "/onsite/requests")]},
        202: {"stillProcessing": _PROCESSING},
    },
    ("POST", _CUSTOMER_BASE + "/reservations/{reservation_id}/receive"): {
        409: {code: {"status": "fail", "errorCode": code} for code in
            ("RESERVATION_VEHICLE_MISMATCH", "NOT_AWAITING_RECEIPT", "RECEIPT_DEADLINE_EXPIRED", "QR_INACTIVE", "RECEIPT_HOLD_INCONSISTENT")},
        404: {"notOwnedOrNotFound": {"status": "fail", "errorCode": "RESERVATION_NOT_FOUND"},
            "qrNotFound": {"status": "fail", "errorCode": "QR_NOT_FOUND"}},
        410: {"qrExpired": {"status": "fail", "errorCode": "QR_EXPIRED"}},
    },
    ("POST", "/nadreego/booking/select"): {200: {
        "onsiteRequested": _page_example(_ADMIN_REQUESTED), "approved": _page_example(_ADMIN_APPROVED),
        "awaitingReceipt": _page_example(_ADMIN_PENDING), "expiredNeedsRecovery": _page_example(_ADMIN_EXPIRED),
        "rental": _page_example(_ADMIN_RENTAL)}},
    ("GET", "/nadreego/main"): {200: {"receiptWork": {
        **OPENAPI_RESPONSE_EXAMPLES[("GET", "/nadreego/main")], "todayWork": [
            dict(item, startAt=item["reservation"]["startDatetime"]) for item in (_ADMIN_PENDING, _ADMIN_EXPIRED, _ADMIN_RENTAL)]}}},
    ("POST", "/nadreego/main/calendar"): {200: {"protectedVehicle": {
        **_page_example({**_ADMIN_PENDING["vehicle"], "events": [{
            **{key: _ADMIN_EXPIRED[key] for key in ("bookedNo", "reservationId", "requestType", "receiptDeadline", "canReceive", "vehicleRecoveryRequired", "availableActions")},
            "eventId": _ADMIN_EXPIRED["bookedNo"], "eventType": "RESERVATION", "status": "EXPIRED",
            "startAt": _ADMIN_EXPIRED["handedOverAt"], "endAt": None, "endAtType": "OPEN", "assignmentStatus": "LOCKED",
            "isBlocking": True, "canReassign": False, "canHandOver": False, "handoverBlockedReason": "VEHICLE_RECEIPT_HOLD"}]}),
        "startDate": "2026-11-04", "endDate": "2026-11-06", "timeZone": "Asia/Makassar", "warnings": []}}},
    ("POST", "/nadreego/vehicle/select"): {200: {"awaitingReceipt": _page_example({
        "vehicle": _ADMIN_PENDING["vehicle"], "currentBooking": _booking_example(_ADMIN_PENDING),
        "currentRental": None, "availableActions": []})}},
    ("POST", "/nadreego/vehicle/qr/validate"): {200: {"awaitingReceipt": {
        "status": True, "errorCode": None, "data": {"vehicleId": _ADMIN_PENDING["vehicleId"],
            "qrId": "NRTEST-NDR-QR-001", "qrStatus": "ACTIVE", "equipmentType": "QR_ONLY", "sensorId": None,
            "sensorStatus": "NOT_LINKED", "vehicle": _ADMIN_PENDING["vehicle"],
            "currentBooking": _booking_example(_ADMIN_PENDING), "currentRental": None, "availableActions": ["RECOVER_VEHICLE"]}}}},
    ("POST", "/nadreego/rent/approve"): {409: {
        "oldClient": {"status": "fail", "errorCode": "CLIENT_UPDATE_REQUIRED"},
        "expiredProtectedVehicle": {"status": "fail", "errorCode": "VEHICLE_UNAVAILABLE"},
        "wrongVehicle": {"status": "fail", "errorCode": "RESERVATION_VEHICLE_MISMATCH"}}},
    ("POST", "/nadreego/booking/action"): {409: {"receiptProtected": {"status": "fail", "errorCode": "RESERVATION_STATE_INVALID"}}},
    ("POST", "/nadreego/vehicle/return"): {409: {"receiptProtected": {"status": "fail", "errorCode": "VEHICLE_RECEIPT_HOLD"}}},
    ("POST", "/nadreego/booking/{booked_no}/receipt-recovery"): {409: {code: {"status": "fail", "errorCode": code} for code in
        ("NOT_AWAITING_RECOVERY", "RESERVATION_VEHICLE_MISMATCH", "RECEIPT_HOLD_INCONSISTENT")}},
}

# General administrators withdraw on acceptance; personal-data work continues.
_DELETION = {
    "status": "success", "requestId": "adr_" + "0" * 64, "requestAccepted": True,
    "requestState": "PROCESSING", "scope": "SELF", "receivedAt": "2026-11-06T06:00:00Z",
    "identityVerifiedAt": "2026-11-06T06:00:00Z", "eligibleAt": "2026-11-06T06:00:00Z",
    "processingDueAt": "2026-11-13T06:00:00Z", "completedAt": None,
    "accessState": "REVOKED", "personalDataState": "IN_PROGRESS", "affectedAdminCount": 1,
    "affectedShopCount": 0, "outstandingWork": {name: 0 for name in (
        "pendingReservations", "activeRentals", "pendingReturns", "pendingRecovery", "pendingRefunds", "pendingExternalSettlements")},
    "nextAction": "NONE", "notificationChannel": "REGISTERED_EMAIL", "completionScope": None,
    "retainedData": [], "residualCopies": [], "receiptExpiresAt": None,
    "message": "Your account and personal-data deletion request has been received.",
}
_DELETION_WAITING = dict(_DELETION, scope="SUBTREE", affectedAdminCount=4, affectedShopCount=2,
    requestState="WAITING_OBLIGATIONS", accessState="LIMITED_TO_SETTLEMENT", personalDataState="NOT_STARTED",
    eligibleAt=None, processingDueAt=None,
    nextAction="SETTLE_OUTSTANDING_WORK", outstandingWork=dict(_DELETION["outstandingWork"], pendingReservations=1))
OPENAPI_EXAMPLES.update({
    "DeletionConfirmation": {"confirmationToken": "<server-confirmation-token>", "confirmed": True},
    "AccountDeletionContext": {"status": "success", "scope": "SUBTREE", "directShopName": "Example Shop",
        "affectedAdminCount": 4, "affectedShopCount": 2, "confirmationToken": "<server-confirmation-token>",
        "confirmationExpiresAt": "2026-11-06T06:10:00Z", "outstandingWork": _DELETION_WAITING["outstandingWork"],
        "canSubmitRequest": True, "canExecuteWithdrawal": False, "activeRequestId": None},
    "AccountDeletionRequestResult": _DELETION,
})
OPENAPI_STATUS_EXAMPLES.update({
    ("GET", "/nadreego/admin/account-deletion-context"): {200: {"subtree": OPENAPI_EXAMPLES["AccountDeletionContext"]}},
    ("POST", "/nadreego/admin/account-deletion-requests"): {
        202: {"selfAccepted": _DELETION, "waitingForObligations": _DELETION_WAITING},
        409: {"scopeChanged": {"status": "fail", "errorCode": "DELETION_SCOPE_CHANGED", "requestAccepted": False,
                               "nextAction": "RELOAD_AND_RECONFIRM"}},
        503: {"checkSameReceipt": {"status": "fail", "errorCode": "DELETION_OUTCOME_UNKNOWN"},
            "requestBusy": {"status": "fail", "errorCode": "DELETION_REQUEST_BUSY", "requestAccepted": False}},
    },
    ("GET", "/nadreego/admin/account-deletion-requests/status"): {
        200: {"pending": _DELETION, "waiting": _DELETION_WAITING,
            "completed": dict(_DELETION, requestState="COMPLETED", accessState="REVOKED", personalDataState="COMPLETED",
                completedAt="2026-11-07T06:00:00Z", completionScope="COMPANY_ACTIVE_SYSTEMS",
                receiptExpiresAt="2026-12-07T06:00:00Z"),
            "completedWithRetentionReviewPending": dict(_DELETION, requestState="COMPLETED", accessState="REVOKED",
                personalDataState="COMPLETED", completedAt="2026-11-07T06:00:00Z",
                completionScope="COMPANY_ACTIVE_SYSTEMS", receiptExpiresAt="2026-12-07T06:00:00Z",
                residualCopies=[{"category": "COMPANY_RESTRICTED_BACKUP", "reviewState": "PENDING", "requestedMaxDays": 30},
                    {"category": "COMPANY_LOG_RETENTION", "reviewState": "PENDING", "requestedMaxDays": 30}]),
            "operatorReview": dict(_DELETION, requestState="ACTION_REQUIRED", accessState="REVOKED",
                personalDataState="IN_PROGRESS", nextAction="REVIEW_DATA_AND_RETENTION",
                message="An operator is reviewing unresolved personal information in shared content.")},
        404: {"notFinalEvidenceOfNonAcceptance": {"status": "fail", "errorCode": "DELETION_REQUEST_UNAVAILABLE"}},
    },
    ("POST", "/nadreego/admin/account-deletion-requests/{deletion_id}/reconfirm"): {202: {"sameRequest": _DELETION_WAITING}},
})
