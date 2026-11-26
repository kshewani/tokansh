from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select

from app.dependencies import DEMO_ACTORS
from app.auth import DemoIdentity
from app.main import create_app
from app.properties.models import ApplicationOperation, Property, PropertyEvent
from app.properties.schemas import NewProperty
from app.properties.service import PropertyService
from client_support import SyncASGIClient


def auth(client, username):
    response = client.post('/api/v1/auth/login', json={'username': username, 'password': 'test-password'})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['data']['access_token']}


def test_create_list_and_get_persistent_draft(client, application, property_payload, issuer_headers):
    response = client.post("/api/v1/properties", json=property_payload, headers=issuer_headers)
    assert response.status_code == 201
    data = response.json()["data"]
    UUID(data["id"])
    assert data["status"] == "DRAFT"
    assert data["approved_supply"] == 0
    assert data["proposed_supply"] == 100000
    assert data["valuation"] == "1000000000.00"
    assert data["unit_price"] == "10000.00"
    assert data["verification_status"] == "NOT_VERIFIED"
    assert data["ledger_registration_status"] == "NOT_REGISTERED"
    assert data["ledger_transaction_id"] is None
    assert response.headers["X-Correlation-ID"] == response.json()["meta"]["correlation_id"] == "test-correlation"
    listing = client.get("/api/v1/properties", headers=auth(client, 'Aarav')).json()["data"]
    assert listing == {"items": [data], "page": 1, "page_size": 20, "total_items": 1, "total_pages": 1}
    assert client.get(f"/api/v1/properties/{data['id']}", headers=issuer_headers).json()["data"] == data
    with application.state.database.sessions() as session:
        record = session.get(Property, data["id"])
        assert record.valuation_minor == 100000000000
        assert record.issue_price_minor == 1000000
        audit = session.scalar(select(PropertyEvent))
        assert audit.event_source == "APPLICATION"
        assert audit.property_id == data["id"]


@pytest.mark.parametrize("field,value", [
    ("name", "  "), ("location", "x"), ("category", ""), ("valuation", "0"),
    ("valuation", "-1"), ("valuation", "NaN"), ("valuation", "Infinity"), ("valuation", "1e9"),
    ("valuation", "999999999999999999999"), ("valuation", 100.1), ("valuation", "10.001"),
    ("issue_price", "0"), ("issue_price", "10.001"), ("issue_price", False),
    ("proposed_supply", 0), ("proposed_supply", -1), ("proposed_supply", 1.5),
    ("proposed_supply", True), ("proposed_supply", "100000"), ("proposed_supply", 9007199254740992),
    ("currency", "USD"), ("status", "APPROVED"), ("ledger_transaction_id", "fake"),
    ("approved_supply", 100000), ("issuer_id", "another-user"),
])
def test_backend_rejects_invalid_or_authoritative_fields(client, property_payload, issuer_headers, field, value):
    response = client.post("/api/v1/properties", json={**property_payload, field: value}, headers=issuer_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert client.get("/api/v1/properties", headers=issuer_headers).json()["data"]["total_items"] == 0


def test_required_fields_and_malformed_json(client, property_payload, issuer_headers):
    for field in property_payload:
        if field == "issue_price":
            continue
        payload = {key: value for key, value in property_payload.items() if key != field}
        assert client.post("/api/v1/properties", json=payload, headers=issuer_headers).status_code == 422
    response = client.post("/api/v1/properties", content="{broken", headers={**issuer_headers, "Content-Type": "application/json"})
    assert response.status_code == 422
    assert "input" not in str(response.json())


def test_decimal_precision_and_normalized_idempotent_replay(client, application, property_payload, issuer_headers):
    payload = {**property_payload, "valuation": "1000000000.01", "issue_price": "0.10"}
    first = client.post("/api/v1/properties", json=payload, headers=issuer_headers)
    second = client.post("/api/v1/properties", json={**payload, "issue_price": "0.1"}, headers={**issuer_headers, "X-Correlation-ID": "retry-correlation"})
    assert first.status_code == second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    assert second.json()["meta"]["correlation_id"] == "retry-correlation"
    with application.state.database.sessions() as session:
        record = session.scalar(select(Property))
        assert record.valuation_minor == 100000000001
        assert record.issue_price_minor == 10
        assert session.scalar(select(func.count()).select_from(ApplicationOperation)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyEvent)) == 1


def test_conflicting_key_is_rejected_without_modification(client, property_payload, issuer_headers):
    first = client.post("/api/v1/properties", json=property_payload, headers=issuer_headers)
    response = client.post("/api/v1/properties", json={**property_payload, "proposed_supply": 200000}, headers=issuer_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert client.get("/api/v1/properties", headers=issuer_headers).json()["data"]["items"] == [first.json()["data"]]


def test_restart_preserves_property_and_replay(application, settings, property_payload, issuer_headers):
    with SyncASGIClient(application) as first_client:
        original = first_client.post("/api/v1/properties", json=property_payload, headers=issuer_headers)
    restarted = create_app(settings)
    with SyncASGIClient(restarted) as second_client:
        token = restarted.state.sessions.create(DemoIdentity("issuer", "Issuer", "ISSUER",
                                                              DEMO_ACTORS["ISSUER"].user_id))
        restarted_headers = {"Authorization": "Bearer " + token,
                             "Idempotency-Key": issuer_headers["Idempotency-Key"],
                             "X-Correlation-ID": issuer_headers["X-Correlation-ID"]}
        replay = second_client.post("/api/v1/properties", json=property_payload, headers=restarted_headers)
        assert replay.json()["data"] == original.json()["data"]
        assert second_client.get("/api/v1/properties", headers=restarted_headers).json()["data"]["total_items"] == 1


def test_concurrent_duplicate_requests_create_one_property(application, property_payload):
    command = NewProperty(**property_payload)
    actor = DEMO_ACTORS["ISSUER"].user_id

    def create(_):
        with application.state.database.sessions() as session:
            return PropertyService(session).create(command, actor, "concurrent-key", "concurrent-correlation")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(create, range(12)))
    assert len({result["id"] for result in results}) == 1
    with application.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Property)) == 1
        assert session.scalar(select(func.count()).select_from(PropertyEvent)) == 1


def test_transaction_rolls_back_property_and_operation_when_audit_fails(application, property_payload):
    engine = application.state.database.engine

    def fail_event(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO property_events"):
            raise RuntimeError("injected isolated test failure")

    event.listen(engine, "before_cursor_execute", fail_event)
    try:
        with application.state.database.sessions() as session:
            with pytest.raises(RuntimeError):
                PropertyService(session).create(NewProperty(**property_payload), DEMO_ACTORS["ISSUER"].user_id, "rollback-key", "test")
    finally:
        event.remove(engine, "before_cursor_execute", fail_event)
    with application.state.database.sessions() as session:
        for model in (Property, ApplicationOperation, PropertyEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with application.state.database.sessions() as session:
        assert PropertyService(session).create(NewProperty(**property_payload), DEMO_ACTORS["ISSUER"].user_id, "rollback-key", "retry")["status"] == "DRAFT"


def test_pagination_and_not_found(client, property_payload, issuer_headers):
    assert client.get("/api/v1/properties", headers=issuer_headers).json()["data"]["total_pages"] == 0
    for index in range(3):
        assert client.post("/api/v1/properties", json=property_payload, headers={**issuer_headers, "Idempotency-Key": f"new-{index}"}).status_code == 201
    page = client.get("/api/v1/properties?page=2&page_size=2", headers=issuer_headers).json()["data"]
    assert len(page["items"]) == 1
    assert page["total_items"] == 3 and page["total_pages"] == 2
    for query in ["page=0", "page_size=101", "page_size=0"]:
        assert client.get("/api/v1/properties?" + query, headers=issuer_headers).status_code == 422
    assert client.get(f"/api/v1/properties/{uuid4()}", headers=issuer_headers).status_code == 404
    assert client.get("/api/v1/properties/not-a-uuid", headers=issuer_headers).status_code == 422


def test_permissions_and_required_idempotency(client, property_payload, issuer_headers):
    assert client.post("/api/v1/properties", json=property_payload).status_code == 401
    for role in ["INVESTOR", "LENDER", "INVALID"]:
        response = client.post("/api/v1/properties", json=property_payload, headers={"X-Demo-Role": role, "Idempotency-Key": "test"})
        assert response.status_code == 401
    investor_response = client.post("/api/v1/properties", json=property_payload,
                                    headers={**auth(client, 'Aarav'), "Idempotency-Key": "aarav-issuance"})
    assert investor_response.status_code == 201
    assert investor_response.json()["data"]["issuer_id"] == "00000000-0000-4000-8000-000000000003"
    assert client.post("/api/v1/properties", json=property_payload,
                       headers={**issuer_headers, "Idempotency-Key": "admin-operation"}).status_code == 201


def test_authenticated_investors_can_initiate_property_issuance(client, property_payload):
    for username, user_id in [
        ("Meera", "00000000-0000-4000-8000-000000000006"),
        ("Aarav", "00000000-0000-4000-8000-000000000003"),
    ]:
        response = client.post(
            "/api/v1/properties",
            json={**property_payload, "name": f"{username} Issuance Property"},
            headers={**auth(client, username), "Idempotency-Key": f"{username.lower()}-property"},
        )
        assert response.status_code == 201
        assert response.json()["data"]["issuer_id"] == user_id


def test_lender_cannot_initiate_property_issuance(client, property_payload):
    response = client.post(
        "/api/v1/properties",
        json=property_payload,
        headers={**auth(client, "axim-bank"), "Idempotency-Key": "lender-property"},
    )
    assert response.status_code == 403


def test_unresolved_operation_does_not_create_another_property(client, application, property_payload, issuer_headers):
    client.post("/api/v1/properties", json=property_payload, headers=issuer_headers)
    with application.state.database.sessions.begin() as session:
        operation = session.scalar(select(ApplicationOperation))
        operation.status = "PROCESSING"
        operation.response_json = None
    response = client.post("/api/v1/properties", json=property_payload, headers=issuer_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECONCILIATION_REQUIRED"
    assert response.json()["error"]["details"]["operation_id"] == operation.id
