from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.customer_rentals import _delivery
from app.errors import Problem
from app.rental_schema import metadata


def test_delivery_uses_explicit_fee_region_not_address_text(setup):
    metadata.create_all(setup["engine"])
    regions = metadata.tables["MSP_DELIVERY_REGION"]
    links = metadata.tables["MSP_SPOT_DELIVERY_REGION"]
    with setup["engine"].begin() as conn:
        for ident in (1, 2):
            conn.execute(regions.insert().values(delivery_region_id=ident, country_code="ID", region_name="Region" + str(ident), region_level="CITY"))
            conn.execute(links.insert().values(spot_master_id="root", delivery_region_id=ident,
                is_delivery_enabled=1, start_delivery_fee=10, return_delivery_fee=10))
    request = SimpleNamespace(app=setup["app"])
    spot = {"spot_master_id": "root", "rent": {"delivery_service_type": "START_AND_RETURN"}}
    model = {"is_delivery_supported": 1}
    with Session(setup["engine"]) as session:
        with pytest.raises(Problem) as error:
            _delivery(request, session, spot, model, "Region1 hotel", "Region1 hotel", required=True)
        assert error.value.code == "DELIVERY_REGION_REQUIRED"
        value = _delivery(request, session, spot, model, "arbitrary address", None,
                          required=True, region_id=2, delivery_type="START_ONLY")
        assert value["deliveryRegionId"] == 2 and value["deliveryReturnFee"] == 0 and value["deliveryTotalFee"] == 10
        value = _delivery(request, session, spot, model, "address one", "address two",
                          required=True, region_id=1, delivery_type="START_AND_RETURN")
        assert value["deliveryTotalFee"] == 20
        spot["rent"]["delivery_service_type"] = "START_ONLY"
        with pytest.raises(Problem) as error:
            _delivery(request, session, spot, model, "address", "address", required=True,
                      region_id=1, delivery_type="START_AND_RETURN")
        assert error.value.code == "DELIVERY_NOT_SUPPORTED"
