"""Account-id based classification (no off-chain labels): used by the money-trail fetcher and the ledgers."""

from __future__ import annotations

import re

REVENUE_WALLETS = ["fefundsadmin.sputnik-dao.near", "1csfundsadmin.sputnik-dao.near", "buybacks.multisignature.near"]
TREASURY = "treasury.near"
WALLETS = [TREASURY] + REVENUE_WALLETS
INTENTS = "intents.near"
WRAP = "wrap.near"


def classify(acc: str) -> str:
    """Counterparty class from the account id alone."""
    if acc in REVENUE_WALLETS:
        return "revenue_wallet"
    if acc == TREASURY:
        return "treasury"
    if acc == INTENTS:
        return "intents"
    if acc == "system":
        return "protocol"
    if acc == WRAP:
        return "wrap_near"
    if acc.endswith(".omft.near") or acc.endswith(".factory.bridge.near") or acc.endswith(".bridge.near"):
        return "token_or_bridge"
    if re.search(r"\.(poolv1|pool)\.near$", acc) or ".pool." in acc:
        return "staking_pool"
    if acc.endswith(".lockup.near"):
        return "lockup"
    if acc.endswith(".sputnik-dao.near"):
        return "sputnik_dao"
    if acc.endswith(".multisignature.near") or acc.endswith(".multisig.near"):
        return "multisig"
    if re.fullmatch(r"[0-9a-f]{64}", acc):
        return "implicit_near"
    if re.fullmatch(r"0x[0-9a-f]{40}", acc):
        return "implicit_eth"
    if acc == "":
        return "none"
    return "named_other"
