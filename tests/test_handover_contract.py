"""Public contract examples and conditional required values for the new flow."""
from app.handover_inputs import (ClaimHandover, EmptyCommand, FormPatch, PrepareMedia,
    ReplaceVehicle, RespondHandover, ReviewHandover, StartHandover, UntrackedRent)
from app.openapi_examples import OPENAPI_EXAMPLES
from app.responses import (AccommodationHistory, HandoverList, HandoverMediaResult,
    HandoverResult, HandoverUploadResult)


def test_handover_examples_follow_the_public_schema(client):
    models = [ClaimHandover, EmptyCommand, FormPatch, PrepareMedia, ReplaceVehicle, RespondHandover,
        ReviewHandover, StartHandover, UntrackedRent, AccommodationHistory, HandoverList,
        HandoverMediaResult, HandoverResult, HandoverUploadResult]
    for model in models:
        model.model_validate(OPENAPI_EXAMPLES[model.__name__])
    schema = client.get('/openapi.json').json()['components']['schemas']
    assert 'currency' not in schema['BookingAction']['properties']
    assert schema['BookingAction']['additionalProperties'] is False
    assert schema['NadriAvailability']['required'] == ['startDate', 'returnDate', 'minCc', 'maxCc', 'deliveryRequested']
    assert schema['ReviewHandover']['properties']['skipPhotoKinds']['items']['enum'] == ['PASSPORT_PHOTO', 'DRIVER_LICENSE_PHOTO']
    assert schema['HandoverResult']['example']['item']['media']['extraPhoto']['required'] is True
