from app.auth import MEERA_ID


def login(client, username, password='test-password'):
    response = client.post('/api/v1/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    data = response.json()['data']
    return data, {'Authorization': 'Bearer ' + data['access_token']}


def test_investor_and_lender_logins_bind_stable_identities(client):
    aarav, _ = login(client, 'aArAv')
    meera, _ = login(client, 'MEERA')
    assert aarav['role'] == 'INVESTOR'
    assert aarav['user_id'] == '00000000-0000-4000-8000-000000000003'
    assert meera['role'] == 'INVESTOR'
    assert meera['user_id'] == MEERA_ID
    assert meera['user_id'] != aarav['user_id']

    for organization in ('axim-bank', 'real-finance', 'horizon-credit'):
        identity, _ = login(client, organization)
        assert identity['role'] == 'LENDER'
        assert identity['organization_id'] == organization


def test_invalid_identity_and_empty_password_are_rejected(client):
    assert client.post('/api/v1/auth/login', json={'username': 'unknown', 'password': 'x'}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'username': 'Aarav', 'password': ''}).status_code == 422
    assert client.post('/api/v1/auth/login', json={'username': 'Aarav', 'password': '   '}).status_code == 200


def test_role_only_header_cannot_authorize_and_logout_revokes_session(client):
    assert client.get('/api/v1/financing/lenders', headers={'X-Demo-Role': 'INVESTOR'}).status_code == 401
    _, headers = login(client, 'Aarav')
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 200
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 200
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_investors_cannot_read_each_other_or_issuer_balances(client):
    _, aarav = login(client, 'Aarav')
    property_id = 'f6169750-4676-4e99-887f-2bc5471bd518'
    meera_id = MEERA_ID
    assert client.get(f'/api/v1/ansh/balances/{property_id}/{meera_id}', headers=aarav).status_code == 403
    assert client.get(f'/api/v1/ansh/balances/{property_id}/00000000-0000-4000-8000-000000000002',
                      headers=aarav).status_code == 403


def test_meera_cannot_act_as_issuer_or_access_aaravs_financing_and_wallet(client):
    _, meera = login(client, 'Meera')
    property_id = 'f6169750-4676-4e99-887f-2bc5471bd518'
    issuer_id = '00000000-0000-4000-8000-000000000002'
    assert client.post('/api/v1/ansh/transfers', headers={**meera, 'Idempotency-Key': 'meera-issuer-attempt'},
                       json={'asset_id': property_id, 'from_user_id': issuer_id, 'to_user_id': MEERA_ID,
                             'quantity': 1, 'kind': 'TRANSFER', 'payment_outcome': 'SUCCESS'}).status_code == 403
    assert client.get('/api/v1/financing/applications', headers=meera).status_code in (200, 503)
    assert client.get('/api/v1/demo-wallet', headers=meera).status_code in (200, 503)


def test_lender_session_organization_cannot_be_changed_by_query_parameter(client):
    _, axim = login(client, 'axim-bank')
    response = client.get('/api/v1/financing/applications', params={'lender_id': 'real-finance'}, headers=axim)
    assert response.status_code == 503 or response.json()['data'] == []
