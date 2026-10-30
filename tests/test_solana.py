import json

import httpx

from unblock import solana_pay

RECIPIENT = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
REF = "9aE476sH92Vz7DMPyq5WLPkrKWivxeuTKEFKd2sZZcde"


def env(monkeypatch):
    monkeypatch.setenv("SOLANA_RECIPIENT", RECIPIENT)
    monkeypatch.setenv("SOLANA_PRICE_USDC", "0.5")


def rpc(sigs, received="0.5", err=None):
    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "getSignaturesForAddress":
            assert body["params"][0] == REF
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": sigs})
        mint = solana_pay.DEVNET_USDC
        meta = {"err": err,
                "preTokenBalances": [{"owner": RECIPIENT, "mint": mint, "uiTokenAmount": {"uiAmountString": "1"}}],
                "postTokenBalances": [{"owner": RECIPIENT, "mint": mint, "uiTokenAmount": {"uiAmountString": str(1 + float(received))}}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"meta": meta}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_payment_url(monkeypatch):
    env(monkeypatch)
    url = solana_pay.payment_url(REF)
    assert url.startswith(f"solana:{RECIPIENT}?amount=0.5&spl-token={solana_pay.DEVNET_USDC}&reference={REF}")


def test_reference_is_a_32_byte_key():
    ref = solana_pay.new_reference()
    assert 32 <= len(ref) <= 44 and all(c in solana_pay.ALPHABET for c in ref)
    assert solana_pay.b58encode(b"\0\x01") == "12"


def test_confirmed_payment(monkeypatch):
    env(monkeypatch)
    ok, detail = solana_pay.check_payment(REF, rpc([{"signature": "5sig" * 10, "err": None}]))
    assert ok and "Confirmed" in detail


def test_not_paid_yet_underpaid_and_failed(monkeypatch):
    env(monkeypatch)
    assert solana_pay.check_payment(REF, rpc([]))[0] is False
    ok, detail = solana_pay.check_payment(REF, rpc([{"signature": "s", "err": None}], received="0.1"))
    assert not ok and "instead of 0.5" in detail
    assert solana_pay.check_payment(REF, rpc([{"signature": "s", "err": None}], err={"InstructionError": 1}))[0] is False


def test_rpc_down_is_a_clear_message(monkeypatch):
    env(monkeypatch)
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    ok, detail = solana_pay.check_payment(REF, down)
    assert not ok and "Couldn't check Solana" in detail
