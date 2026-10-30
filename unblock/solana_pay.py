"""Solana Pay (USDC) as a second way to buy the Friction Map report.

Flow: create a random reference key -> build a `solana:` transfer-request link
(wallets like Phantom open it) -> the buyer pays -> look up the transaction by
its reference with getSignaturesForAddress -> confirm with getTransaction that
the recipient's USDC balance went up by at least the price and the transaction
succeeded. Only then is the report released.

SOLANA_RECIPIENT   your wallet address (required to turn this on)
SOLANA_RPC_URL     default https://api.devnet.solana.com
SOLANA_USDC_MINT   default devnet USDC 4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
                   (mainnet USDC is EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)
SOLANA_PRICE_USDC  default 0.5
"""
import os
from decimal import Decimal
from urllib.parse import quote

import httpx

from .config import env

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DEVNET_USDC = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out


def enabled() -> bool:
    return bool(env("SOLANA_RECIPIENT"))


def settings() -> dict:
    return {"recipient": env("SOLANA_RECIPIENT"), "rpc": env("SOLANA_RPC_URL", "https://api.devnet.solana.com"),
            "mint": env("SOLANA_USDC_MINT", DEVNET_USDC), "price": env("SOLANA_PRICE_USDC", "0.5")}


def new_reference() -> str:
    """A random 32-byte public key, used only to find this payment on-chain."""
    return b58encode(os.urandom(32))


def payment_url(reference: str, label: str = "TeamReady", message: str = "Friction Map full report") -> str:
    s = settings()
    return (f"solana:{s['recipient']}?amount={s['price']}&spl-token={s['mint']}&reference={reference}"
            f"&label={quote(label)}&message={quote(message)}")


def _rpc(client: httpx.Client, url: str, method: str, params: list):
    r = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{method}: {data['error'].get('message', data['error'])}")
    return data["result"]


def _balance(entries: list, owner: str, mint: str) -> Decimal:
    total = Decimal(0)
    for e in entries or []:
        if e.get("owner") == owner and e.get("mint") == mint:
            total += Decimal(e["uiTokenAmount"].get("uiAmountString") or "0")
    return total


def check_payment(reference: str, client: httpx.Client | None = None) -> tuple[bool, str]:
    """(paid, explanation). Never raises for a normal 'not yet paid'."""
    s = settings()
    client = client or httpx.Client()
    try:
        sigs = _rpc(client, s["rpc"], "getSignaturesForAddress", [reference, {"limit": 5, "commitment": "confirmed"}])
        if not sigs:
            return False, "No payment found for this reference yet. It can take a few seconds after you approve in your wallet."
        for sig in sigs:
            if sig.get("err"):
                continue
            tx = _rpc(client, s["rpc"], "getTransaction",
                      [sig["signature"], {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}])
            if not tx or tx["meta"].get("err"):
                continue
            received = _balance(tx["meta"].get("postTokenBalances"), s["recipient"], s["mint"]) - \
                _balance(tx["meta"].get("preTokenBalances"), s["recipient"], s["mint"])
            if received >= Decimal(s["price"]):
                return True, f"Confirmed on Solana: {received} USDC received in transaction {sig['signature'][:12]}…"
            return False, f"Found a transaction, but it sent {received} USDC instead of {s['price']}."
        return False, "The transaction for this reference failed on-chain."
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
        return False, f"Couldn't check Solana right now ({exc}). Try again in a moment."
