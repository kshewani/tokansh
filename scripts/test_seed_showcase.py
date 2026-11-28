import seed_showcase as seed


def test_supporting_wallet_funding_uses_available_cash_and_stable_key(monkeypatch):
    calls = []

    def fake_api(base, token, path, method="GET", payload=None, key=None):
        calls.append((token, path, method, payload, key))
        if method == "GET":
            return {"balance_minor": "60000", "available_minor": "60000"}
        return {"amount_minor": payload["amount_minor"]}

    monkeypatch.setattr(seed, "login", lambda base, username: (username + "-token", {}))
    monkeypatch.setattr(seed, "api", fake_api)
    seed.fund_investor_to_target("http://api", "Rohan", 67200)
    assert calls[-1] == ("Rohan-token", "/api/v1/demo-wallet/fund", "POST", {"amount_minor": "7200"}, "showcase-wallet-rohan")


def test_lender_resume_only_executes_remaining_transitions(monkeypatch):
    calls = []

    def fake_api(base, token, path, method="GET", payload=None, key=None):
        calls.append((token, path, method))
        action = path.rsplit("/", 1)[-1]
        return {"id": "loan-1", "state": {"repay": "REPAID", "release": "RELEASED"}[action]}

    monkeypatch.setattr(seed, "api", fake_api)
    seed.advance_loan("http://api", "axim-bank", "Rohan", {"id": "loan-1", "state": "DISBURSED"},
                      "rohan-token", "lender-token", "RELEASED")
    assert [call[1] for call in calls] == [
        "/api/v1/financing/applications/loan-1/repay",
        "/api/v1/financing/applications/loan-1/release",
    ]


def test_incompatible_lender_resume_fails_before_api_call():
    try:
        seed.advance_loan("http://api", "axim-bank", "Rohan", {"id": "loan-1", "state": "REJECTED"},
                          "rohan-token", "lender-token", "RELEASED")
    except RuntimeError as error:
        assert "Incompatible lender state transition" in str(error)
    else:
        raise AssertionError("Expected incompatible lender transition to fail closed")
