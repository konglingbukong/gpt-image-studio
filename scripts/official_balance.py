"""Record a fresh billing-page observation made by the MCP client's signed-in browser."""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

import gen


BILLING = "https://platform.openai.com/settings/organization/billing/overview"
GENERAL = "https://platform.openai.com/settings/organization/general"
API = "https://api.openai.com/v1"
FIELDS = {
    "amount_usd": {"type": "number", "minimum": -1000, "maximum": 1000000,
                   "description": "USD value displayed next to API credit balance or Credit balance."},
    "billing_url": {"type": "string", "description": "Actual URL of the signed-in billing page you read."},
    "organization_id": {"type": "string", "description": "Organization ID from General settings for that same organization."},
    "observed_at": {"type": "number", "description": "Unix time in seconds at the moment the amount was read (Date.now()/1000)."},
}


def account_key(cfg):
    if (cfg.get("api_url") or API).rstrip("/") != API or cfg.get("balance_source") == "relay":
        raise ValueError("Official balance sync requires the OpenAI API. For a relay, call get_spending.")
    try:
        return gen.load_key(cfg)
    except SystemExit:
        raise ValueError("Set your OpenAI project API key in the local studio's API settings, then retry.") from None


def verify_organization(cfg, key, org):
    # A project key is bound to one organization. A legacy key may allow several,
    # so check the default organization used by the studio's unscoped requests.
    project_key = key.startswith(("sk-proj-", "sk-svcacct-"))
    req = urllib.request.Request(API + "/models")
    req.add_unredirected_header("Authorization", "Bearer " + key)
    if project_key:
        req.add_unredirected_header("OpenAI-Organization", org)
    try:
        with gen.build_opener(cfg).open(req, timeout=15) as response:
            if response.status != 200 or response.geturl() != req.full_url:
                raise ValueError("Unexpected response while verifying the OpenAI organization.")
            reported = response.headers.get("openai-organization")
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError(f"OpenAI could not verify this organization (HTTP {exc.code}). Check the selected "
                         "organization and the project key's Models read permission, then retry.") from None
    except (OSError, json.JSONDecodeError):
        raise ValueError("Could not verify the organization with OpenAI. Check the connection and retry.") from None
    if not isinstance(data, dict) or data.get("object") != "list" or not isinstance(data.get("data"), list):
        raise ValueError("OpenAI did not return the expected model list for organization verification.")
    if (reported is not None or not project_key) and reported != org:
        raise ValueError("Could not match this billing organization to the studio's default organization. "
                         "Select the correct organization or use its project-scoped API key.")


def sync(args):
    cfg = gen.read_config()
    key = account_key(cfg)
    if not args:
        return {"status": "needs_browser", "billing_url": BILLING, "organization_settings_url": GENERAL,
                "instructions": "Continue now with your authorized browser tool or installed browser CLI. Use the user's "
                                "signed-in browser, preferably a background tab. Open a fresh billing overview and read "
                                "only the labeled API credit balance (or Credit balance) in USD. Note the actual URL and "
                                "current Unix time in seconds when you read it. Read Organization ID from General settings "
                                "in the same organization. Call sync_balance again with all four fields. If sign-in or "
                                "browser consent is needed, let the user complete it. If the balance or organization is "
                                "ambiguous, stop. Never substitute a chat message, saved estimate, spending total or budget."}
    if set(args) != set(FIELDS):
        raise ValueError("Call sync_balance with no arguments to start, or provide all four observation fields.")
    url = urlsplit(args["billing_url"] if isinstance(args["billing_url"], str) else "")
    if (url.scheme, url.netloc.lower(), url.path.rstrip("/")) != ("https", "platform.openai.com", urlsplit(BILLING).path):
        raise ValueError("Read the balance from the official OpenAI organization billing overview.")
    org, amount, at = args["organization_id"], args["amount_usd"], args["observed_at"]
    if not isinstance(org, str) or not re.fullmatch(r"org[-_][A-Za-z0-9_-]{1,100}", org):
        raise ValueError("Read the Organization ID from the same organization's General settings.")
    if type(amount) not in (int, float) or not -1000 <= amount <= 1_000_000:
        raise ValueError("The observed balance must be a finite USD amount in the supported range.")
    if type(at) not in (int, float) or not time.time() - 600 <= at <= time.time() + 5:
        raise ValueError("The observation has expired or has an invalid time. Read the billing page again.")
    verify_organization(cfg, key, org)
    baseline = {"amount": round(amount, 4), "at": at, "source": "mcp_browser", "organization_id": org}
    with gen.edit_config() as current:
        if account_key(current) != key:
            raise ValueError("The studio's API account changed during the sync. Start a new sync.")
        previous = current.get("balance") or {}
        latest = max([previous.get("at") or 0] + [v["at"] for v in previous.get("topups", [])])
        if baseline != previous and at <= latest:
            raise ValueError("A newer balance is already recorded. Read the billing page again.")
        current["balance"] = baseline
    return {"status": "synced", "amount_usd": baseline["amount"],
            "observed_at": datetime.fromtimestamp(at, timezone.utc).isoformat(), "source": BILLING}
