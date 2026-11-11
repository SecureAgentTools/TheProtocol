# SPDX-License-Identifier: Apache-2.0
"""The registry side of onboarding, with the agent's own credentials (the download's .env and .env.secret).

    python onboard.py check   the credentials work: an agent token from the registry
    python onboard.py card    the registry checks the card this agent serves (POST /api/v1/utils/validate-card)
    python onboard.py bond    the reputation bond a provider needs before it is found and paid, from the agent's balance
    python onboard.py all     the three, in that order

Inside the container: docker compose exec <service> python onboard.py all. Every step prints the registry's own answer
and exits non-zero when the registry refused it.
"""
import json
import os
import sys

import httpx

from card import build_card, load_card, price_of

TIMEOUT = 20.0


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set (see .env and .env.secret)")
    return value


def _registry() -> str:
    return _env("REGISTRY_URL").rstrip("/")


def _answer(r: httpx.Response):
    try:
        return r.json()
    except ValueError:
        return r.text[:300]


def agent_token() -> str:
    """POST /api/v1/auth/agent/token, form-encoded: username = the client id, password = the client secret."""
    r = httpx.post(f"{_registry()}/api/v1/auth/agent/token", timeout=TIMEOUT,
                   data={"username": _env("CLIENT_ID"), "password": _env("CLIENT_SECRET")})
    if r.status_code != 200:
        sys.exit(f"the registry refused the agent's credentials ({r.status_code}): {_answer(r)}")
    return r.json()["access_token"]


def check() -> None:
    agent_token()
    print(f"credentials: the registry at {_registry()} issued an agent token for {_env('AGENT_DID')}")


def card() -> None:
    served = build_card(load_card(), name=os.getenv("AGENT_NAME", "My Agent"),
                        public_url=os.getenv("PUBLIC_URL", "").rstrip("/") or "http://localhost:8055",
                        price=price_of(os.getenv("PRICE")), currency=os.getenv("CURRENCY", ""),
                        payment_required=os.getenv("PAYMENT_REQUIRED", "true").strip().lower() != "false")
    r = httpx.post(f"{_registry()}/api/v1/utils/validate-card", json={"card_data": served}, timeout=TIMEOUT)
    body = _answer(r)
    if r.status_code != 200 or not (isinstance(body, dict) and body.get("is_valid")):
        sys.exit(f"the registry does not accept the card ({r.status_code}): "
                 f"{body.get('detail') if isinstance(body, dict) else body}")
    print(f"card: the registry accepts the card this agent serves ({served['supportedInterfaces'][0]['url']})")


def bond() -> None:
    cfg = httpx.get(f"{_registry()}/api/v1/reputation-bond/config", timeout=TIMEOUT)
    policy = _answer(cfg)
    if cfg.status_code != 200 or not isinstance(policy, dict):
        sys.exit(f"the registry's bond policy could not be read ({cfg.status_code}): {policy}")
    if str(policy.get("mode", "")).lower() == "off":
        print("bond: this registry asks no bond of a provider")
        return
    # the registry's own amount (the policy's): an agent already bonded gets its bond back
    r = httpx.post(f"{_registry()}/api/v1/agents/reputation-bond/deposit", json={}, timeout=TIMEOUT,
                   headers={"Authorization": f"Bearer {agent_token()}"})
    body = _answer(r)
    if r.status_code != 200:
        sys.exit(f"the registry refused the bond ({r.status_code}): "
                 f"{body.get('detail') if isinstance(body, dict) else body}")
    print(f"bond: {body.get('status')}, {body.get('amount')} {body.get('currency')} "
          f"(the registry asks {policy.get('amount')} {policy.get('currency')}, mode {policy.get('mode')})")


STEPS = {"check": [check], "card": [card], "bond": [bond], "all": [check, card, bond]}

if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step not in STEPS:
        sys.exit(f"usage: python onboard.py {'|'.join(STEPS)}")
    for fn in STEPS[step]:
        fn()
    if step == "all":
        print(json.dumps({"ready": True}))
