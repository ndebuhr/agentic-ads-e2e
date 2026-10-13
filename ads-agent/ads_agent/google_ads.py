"""Read-only Google Ads tools named after the google-ads-mcp tools the skills reference.

The skills call `customers_list_accessible_customers` and `search_search` on the
google-ads-mcp server. These run the same queries in-process with the OAuth
config the skill scripts already use, so no MCP sign-in is needed.
"""
import re
from functools import cache

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.auth.exceptions import RefreshError
from google.protobuf import json_format

from .config import GOOGLE_ADS_CONFIG

MAX_ROWS = 1000
AUTH_HELP = ("Google Ads sign-in expired or is missing. Ask the user to run "
             "`.agents/skills/google-ads-auth/scripts/setup_oauth.py` in a terminal, then retry.")


@cache
def _client() -> GoogleAdsClient:
    return GoogleAdsClient.load_from_storage(GOOGLE_ADS_CONFIG)


def _errors(e: GoogleAdsException) -> dict:
    return {"error": [f"{err.error_code}: {err.message}" for err in e.failure.errors]}


def customers_list_accessible_customers() -> dict:
    """Lists the Google Ads customer IDs the signed-in user can access."""
    try:
        names = _client().get_service("CustomerService").list_accessible_customers().resource_names
    except RefreshError:
        return {"error": AUTH_HELP}
    return {"customer_ids": [n.split("/")[-1] for n in names]}


def search_search(
    customer_id: str,
    resource: str,
    fields: list[str],
    conditions: list[str] | None = None,
    orderings: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Runs a read-only Google Ads Query Language (GAQL) search.

    Args:
      customer_id: The customer ID, digits only.
      resource: The resource to select FROM, for example "campaign".
      fields: Fields to SELECT, for example ["campaign.id", "metrics.clicks"].
      conditions: WHERE clauses, joined with AND, for example
        ["campaign.status != 'REMOVED'", "segments.date DURING LAST_30_DAYS"].
      orderings: ORDER BY clauses, for example ["metrics.clicks DESC"].
      limit: Maximum rows to return (capped at 1000).

    Returns:
      rows, each a dict keyed by resource, or an error.
    """
    query = f"SELECT {', '.join(fields)} FROM {resource}"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    if orderings:
        query += " ORDER BY " + ", ".join(orderings)
    query += f" LIMIT {min(limit or MAX_ROWS, MAX_ROWS)}"
    try:
        stream = _client().get_service("GoogleAdsService").search(customer_id=re.sub(r"\D", "", customer_id), query=query)
        rows = [json_format.MessageToDict(r._pb, preserving_proto_field_name=True) for r in stream]
    except RefreshError:
        return {"error": AUTH_HELP}
    except GoogleAdsException as e:
        return _errors(e)
    return {"query": query, "rows": rows}
