#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-ads>=32,<33"]
# ///
"""Search campaigns, ad groups, and keywords (write path). Auth: ~/google-ads.yaml (OAuth).

  search_campaign.py list         --customer ID [--campaign CAMPAIGN_ID]
  search_campaign.py keywords     --customer ID (--campaign ID | --ad-group ID) [--days 30]
  search_campaign.py geo-suggest  NAME [NAME ...] [--country US]
  search_campaign.py create       --customer ID --spec spec.json [--dry-run]
  search_campaign.py add-keywords --customer ID --ad-group ID KW [KW ...] [--negative] [--dry-run]
  search_campaign.py add-negatives --customer ID --campaign ID KW [KW ...] [--dry-run]
  search_campaign.py set-status   --customer ID (--campaign ID | --ad-group ID) --status ENABLED|PAUSED [--dry-run]
  search_campaign.py spec-template > spec.json

Keywords use Google Ads Editor notation: [exact], "phrase", or bare broad.
The spec (JSON) describes one Search campaign:
  name, daily_budget, bidding {strategy, cpc_ceiling | target_cpa | target_roas},
  networks {search_partners, display_expansion}, locations[geo target IDs],
  location_presence_only, languages[language constant IDs], start, end,
  negative_keywords[], ad_groups[{name, cpc_bid, keywords[], negative_keywords[]}].
The campaign is always created PAUSED, with budget, campaign, targeting, ad groups,
and keywords in one atomic mutate using temporary IDs. Ads come from the
google-ads-rsa skill.
"""
import argparse, json, os, re, sys
from datetime import date
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

def load_client(config):
    path = config or os.path.expanduser("~/google-ads.yaml")
    if not os.path.exists(path):
        sys.exit(f"{path} not found. Run the google-ads-auth skill's scripts/setup_oauth.py once to create it.")
    from google.auth.exceptions import RefreshError
    try:
        return GoogleAdsClient.load_from_storage(path)
    except RefreshError as e:
        why = "expired under Workspace session control (invalid_rapt)" if "rapt" in str(e).lower() or "Reauthentication" in str(e) else "invalid or revoked"
        sys.exit(f"Google Ads refresh token in {path} is {why}. Run the google-ads-auth skill's setup_oauth.py --check for options.")

STRATEGIES = {"MAXIMIZE_CLICKS", "MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE", "MANUAL_CPC"}
KW_MAX_CHARS, KW_MAX_WORDS = 80, 10
KW_BAD_CHARS = re.compile(r"[!@%,*^=;~`<>?\\|]")

def digits(s): return re.sub(r"\D", "", str(s or ""))
def micros(x): return round(float(x) * 100) * 10_000  # whole cents, as USD bids require
def money(m): return round(m / 1_000_000, 2)

def die_on_error(e):
    for err in e.failure.errors:
        loc = ".".join(f.field_name + (f"[{f.index}]" if "index" in f else "") for f in err.location.field_path_elements)
        trig = f" trigger={err.trigger.string_value!r}" if err.trigger.string_value else ""
        print(f"ERROR {err.error_code}: {err.message}{trig}" + (f"  [{loc}]" if loc else ""), file=sys.stderr)
    sys.exit(1)

def query(client, cust, gaql):
    return list(client.get_service("GoogleAdsService").search(customer_id=cust, query=gaql))

def parse_kw(s):
    """'[a b]' -> EXACT, '"a b"' -> PHRASE, 'a b' -> BROAD."""
    s = s.strip()
    if len(s) > 1 and s[0] == "[" and s[-1] == "]": return s[1:-1].strip(), "EXACT"
    if len(s) > 1 and s[0] == '"' and s[-1] == '"': return s[1:-1].strip(), "PHRASE"
    return s, "BROAD"

def fmt_kw(text, match):
    return {"EXACT": f"[{text}]", "PHRASE": f'"{text}"'}.get(match, text)

def kw_errors(kws, where):
    errs, seen = [], set()
    for raw in kws:
        text, match = parse_kw(raw)
        if not text: errs.append(f"{where}: empty keyword {raw!r}")
        if len(text) > KW_MAX_CHARS: errs.append(f"{where}: {raw!r} is {len(text)} chars (max {KW_MAX_CHARS})")
        if len(text.split()) > KW_MAX_WORDS: errs.append(f"{where}: {raw!r} has more than {KW_MAX_WORDS} words")
        if KW_BAD_CHARS.search(text): errs.append(f"{where}: {raw!r} contains a character keywords can't use")
        key = (text.lower(), match)
        if key in seen: errs.append(f"{where}: duplicate keyword {raw!r}")
        seen.add(key)
    return errs

# ---------- validation ----------
def validate(spec):
    errs = []
    for k in ("name", "daily_budget", "bidding", "locations", "ad_groups"):
        if not spec.get(k): errs.append(f"{k} is required")
    if spec.get("daily_budget") is not None and float(spec["daily_budget"]) <= 0: errs.append("daily_budget must be > 0")
    b = spec.get("bidding") or {}
    if b and b.get("strategy") not in STRATEGIES: errs.append(f"bidding.strategy must be one of {sorted(STRATEGIES)}")
    if b.get("strategy") == "MANUAL_CPC" and any(not g.get("cpc_bid") for g in spec.get("ad_groups") or []):
        errs.append("MANUAL_CPC: every ad group needs cpc_bid")
    for d in ("start", "end"):
        if spec.get(d):
            try: date.fromisoformat(spec[d])
            except ValueError: errs.append(f"{d}: use YYYY-MM-DD")
    errs += kw_errors(spec.get("negative_keywords") or [], "negative_keywords")
    names = set()
    for i, g in enumerate(spec.get("ad_groups") or []):
        where = f"ad_groups[{i}]"
        if not g.get("name"): errs.append(f"{where}.name is required")
        if g.get("name") in names: errs.append(f"{where}: duplicate ad group name {g['name']!r}")
        names.add(g.get("name"))
        if not g.get("keywords"): errs.append(f"{where}.keywords: need at least one")
        errs += kw_errors(g.get("keywords") or [], f"{where}.keywords")
        errs += kw_errors(g.get("negative_keywords") or [], f"{where}.negative_keywords")
    if errs:
        print("spec invalid:\n  " + "\n  ".join(errs), file=sys.stderr); sys.exit(2)

def warnings(client, cust, spec):
    out = []
    strat = spec["bidding"]["strategy"]
    if strat in ("MAXIMIZE_CONVERSIONS", "MAXIMIZE_CONVERSION_VALUE"):
        convs = query(client, cust, """SELECT conversion_action.name FROM conversion_action
            WHERE conversion_action.status = 'ENABLED' AND conversion_action.include_in_conversions_metric = TRUE""")
        if not convs:
            out.append(f"{strat} with no enabled primary conversion actions: Google has nothing to optimize toward. Use MAXIMIZE_CLICKS until conversion tracking is live.")
    if strat == "MAXIMIZE_CLICKS" and not spec["bidding"].get("cpc_ceiling"):
        out.append("MAXIMIZE_CLICKS without cpc_ceiling: a few expensive clicks can use the whole daily budget.")
    broad = sum(1 for g in spec["ad_groups"] for k in g["keywords"] if parse_kw(k)[1] == "BROAD")
    if broad and strat in ("MANUAL_CPC", "MAXIMIZE_CLICKS"):
        out.append(f"{broad} broad-match keywords under {strat}: broad match works best with conversion-based Smart Bidding; prefer phrase/exact here.")
    for g in spec["ad_groups"]:
        if len(g["keywords"]) > 20:
            out.append(f"ad group {g['name']!r} has {len(g['keywords'])} keywords; tighter themes (5-20) make RSA copy more relevant.")
    if spec.get("networks", {}).get("display_expansion"):
        out.append("display_expansion is on: Search budget will also buy Display inventory.")
    return out

# ---------- commands ----------
def cmd_spec_template(client, a):
    print(json.dumps({
        "name": "Example Co - Search - Core products",
        "daily_budget": 20.00,
        "bidding": {"strategy": "MAXIMIZE_CLICKS", "cpc_ceiling": 2.00},
        "networks": {"search_partners": False, "display_expansion": False},
        "locations": ["2840"], "location_presence_only": True,
        "languages": ["1000"],
        "start": None, "end": None,
        "negative_keywords": ["free", "\"how to make\"", "[diy]"],
        "ad_groups": [
            {"name": "Handmade goods", "cpc_bid": 1.50,
             "keywords": ["[handmade goods]", "\"handmade gifts\"", "\"small batch goods\""],
             "negative_keywords": ["wholesale"]},
            {"name": "Gift boxes", "cpc_bid": 1.25,
             "keywords": ["[gift box]", "\"curated gift box\""]},
        ]}, indent=2))

def cmd_list(client, a):
    cond = f" AND campaign.id = {digits(a.campaign)}" if a.campaign else ""
    camps = query(client, a.customer, f"""
        SELECT campaign.id, campaign.name, campaign.status, campaign.primary_status, campaign.bidding_strategy_type,
               campaign_budget.amount_micros, campaign.network_settings.target_search_network,
               campaign.network_settings.target_content_network
        FROM campaign WHERE campaign.advertising_channel_type = 'SEARCH' AND campaign.status != 'REMOVED'{cond}""")
    groups = query(client, a.customer, f"""
        SELECT ad_group.id, ad_group.name, ad_group.status, ad_group.primary_status, ad_group.cpc_bid_micros, campaign.id
        FROM ad_group WHERE campaign.advertising_channel_type = 'SEARCH' AND ad_group.status != 'REMOVED'{cond}""")
    kw_n, ad_n = {}, {}
    for r in query(client, a.customer, f"""SELECT ad_group.id FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE
              AND ad_group_criterion.status != 'REMOVED' AND campaign.advertising_channel_type = 'SEARCH'{cond}"""):
        kw_n[r.ad_group.id] = kw_n.get(r.ad_group.id, 0) + 1
    for r in query(client, a.customer, f"""SELECT ad_group.id, ad_group_ad.ad_strength FROM ad_group_ad
            WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD' AND ad_group_ad.status != 'REMOVED'
              AND campaign.advertising_channel_type = 'SEARCH'{cond}"""):
        ad_n.setdefault(r.ad_group.id, []).append(r.ad_group_ad.ad_strength.name)
    out = []
    for c in camps:
        out.append({"campaign_id": c.campaign.id, "name": c.campaign.name, "status": c.campaign.status.name,
                    "primary_status": c.campaign.primary_status.name, "bidding": c.campaign.bidding_strategy_type.name,
                    "daily_budget": money(c.campaign_budget.amount_micros),
                    "search_partners": c.campaign.network_settings.target_search_network,
                    "display_expansion": c.campaign.network_settings.target_content_network,
                    "ad_groups": [{"id": g.ad_group.id, "name": g.ad_group.name, "status": g.ad_group.status.name,
                                   "primary_status": g.ad_group.primary_status.name,
                                   "cpc_bid": money(g.ad_group.cpc_bid_micros) if g.ad_group.cpc_bid_micros else None,
                                   "keywords": kw_n.get(g.ad_group.id, 0), "rsa_ad_strength": ad_n.get(g.ad_group.id, [])}
                                  for g in groups if g.campaign.id == c.campaign.id]})
    print(json.dumps(out, indent=2))

def cmd_keywords(client, a):
    if not (a.campaign or a.ad_group): sys.exit("pass --campaign or --ad-group")
    cond = f"ad_group.id = {digits(a.ad_group)}" if a.ad_group else f"campaign.id = {digits(a.campaign)}"
    rows = query(client, a.customer, f"""
        SELECT ad_group.id, ad_group.name, ad_group_criterion.criterion_id, ad_group_criterion.keyword.text,
               ad_group_criterion.keyword.match_type, ad_group_criterion.negative, ad_group_criterion.status,
               ad_group_criterion.approval_status, ad_group_criterion.primary_status,
               ad_group_criterion.quality_info.quality_score, ad_group_criterion.quality_info.search_predicted_ctr,
               ad_group_criterion.quality_info.creative_quality_score, ad_group_criterion.quality_info.post_click_quality_score
        FROM ad_group_criterion WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.status != 'REMOVED' AND {cond}""")
    stats = {}
    for r in query(client, a.customer, f"""
            SELECT ad_group.id, ad_group_criterion.criterion_id, metrics.impressions, metrics.clicks,
                   metrics.cost_micros, metrics.conversions
            FROM keyword_view WHERE segments.date DURING LAST_{a.days}_DAYS AND {cond}"""):
        stats[(r.ad_group.id, r.ad_group_criterion.criterion_id)] = r.metrics
    out = []
    for r in rows:
        c, q = r.ad_group_criterion, r.ad_group_criterion.quality_info
        m = stats.get((r.ad_group.id, c.criterion_id))
        out.append({"ad_group": r.ad_group.name, "ad_group_id": r.ad_group.id, "criterion_id": c.criterion_id,
                    "keyword": fmt_kw(c.keyword.text, c.keyword.match_type.name), "negative": c.negative,
                    "status": c.status.name, "primary_status": c.primary_status.name, "approval": c.approval_status.name,
                    "quality_score": q.quality_score or None,
                    "qs_parts": None if c.negative else {"expected_ctr": q.search_predicted_ctr.name,
                                                         "ad_relevance": q.creative_quality_score.name,
                                                         "landing_page": q.post_click_quality_score.name},
                    f"last_{a.days}d": {"impressions": m.impressions, "clicks": m.clicks, "cost": money(m.cost_micros),
                                        "conversions": round(m.conversions, 2)} if m else None})
    print(json.dumps(out, indent=2))

def cmd_geo_suggest(client, a):
    svc = client.get_service("GeoTargetConstantService")
    req = client.get_type("SuggestGeoTargetConstantsRequest")
    req.locale = "en"; req.country_code = a.country; req.location_names.names.extend(a.names)
    resp = svc.suggest_geo_target_constants(request=req)
    print(json.dumps([{"search_term": s.search_term, "id": s.geo_target_constant.id,
                       "name": s.geo_target_constant.canonical_name, "type": s.geo_target_constant.target_type,
                       "status": s.geo_target_constant.status.name, "reach": s.reach}
                      for s in resp.geo_target_constant_suggestions], indent=2))

def mutate(client, cust, ops, dry_run):
    req = client.get_type("MutateGoogleAdsRequest")
    req.customer_id = cust; req.mutate_operations.extend(ops); req.validate_only = dry_run
    return client.get_service("GoogleAdsService").mutate(request=req)

def kw_op(client, ag_rn, raw, negative=False, cpc=None):
    text, match = parse_kw(raw)
    op = client.get_type("MutateOperation"); c = op.ad_group_criterion_operation.create
    c.ad_group = ag_rn; c.keyword.text = text
    c.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, match)
    if negative: c.negative = True
    else:
        c.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        if cpc: c.cpc_bid_micros = micros(cpc)
    return op

def campaign_neg_op(client, camp_rn, raw):
    text, match = parse_kw(raw)
    op = client.get_type("MutateOperation"); c = op.campaign_criterion_operation.create
    c.campaign = camp_rn; c.negative = True; c.keyword.text = text
    c.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, match)
    return op

def cmd_create(client, a):
    spec = json.load(open(a.spec)); validate(spec)
    cust, E = a.customer, client.enums
    ga = client.get_service("GoogleAdsService")
    budget_rn = ga.campaign_budget_path(cust, -1)
    camp_rn = ga.campaign_path(cust, -2)
    ops = []

    op = client.get_type("MutateOperation"); bud = op.campaign_budget_operation.create
    bud.resource_name = budget_rn; bud.name = f"{spec['name']} budget"
    bud.amount_micros = micros(spec["daily_budget"])
    bud.delivery_method = E.BudgetDeliveryMethodEnum.STANDARD; bud.explicitly_shared = False
    ops.append(op)

    op = client.get_type("MutateOperation"); c = op.campaign_operation.create
    c.resource_name = camp_rn; c.name = spec["name"]; c.campaign_budget = budget_rn
    c.advertising_channel_type = E.AdvertisingChannelTypeEnum.SEARCH
    c.status = E.CampaignStatusEnum.PAUSED
    c.contains_eu_political_advertising = E.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    net = spec.get("networks") or {}
    c.network_settings.target_google_search = True
    c.network_settings.target_search_network = bool(net.get("search_partners", False))
    c.network_settings.target_content_network = bool(net.get("display_expansion", False))
    c.network_settings.target_partner_search_network = False
    c.geo_target_type_setting.positive_geo_target_type = (
        E.PositiveGeoTargetTypeEnum.PRESENCE if spec.get("location_presence_only", True)
        else E.PositiveGeoTargetTypeEnum.PRESENCE_OR_INTEREST)
    b = spec["bidding"]
    # copy_from selects the bidding oneof even when every field is left at its default
    if b["strategy"] == "MAXIMIZE_CLICKS":
        ts = client.get_type("TargetSpend")
        if b.get("cpc_ceiling"): ts.cpc_bid_ceiling_micros = micros(b["cpc_ceiling"])
        client.copy_from(c.target_spend, ts)
    elif b["strategy"] == "MAXIMIZE_CONVERSIONS":
        mc = client.get_type("MaximizeConversions")
        if b.get("target_cpa"): mc.target_cpa_micros = micros(b["target_cpa"])
        client.copy_from(c.maximize_conversions, mc)
    elif b["strategy"] == "MAXIMIZE_CONVERSION_VALUE":
        mv = client.get_type("MaximizeConversionValue")
        if b.get("target_roas"): mv.target_roas = float(b["target_roas"])
        client.copy_from(c.maximize_conversion_value, mv)
    else:
        client.copy_from(c.manual_cpc, client.get_type("ManualCpc"))
    if spec.get("start"): c.start_date_time = f"{spec['start']} 00:00:00"
    if spec.get("end"): c.end_date_time = f"{spec['end']} 23:59:59"
    ops.append(op)

    for loc in spec["locations"]:
        op = client.get_type("MutateOperation"); cc = op.campaign_criterion_operation.create
        cc.campaign = camp_rn; cc.location.geo_target_constant = f"geoTargetConstants/{digits(loc)}"
        ops.append(op)
    for lang in spec.get("languages") or ["1000"]:
        op = client.get_type("MutateOperation"); cc = op.campaign_criterion_operation.create
        cc.campaign = camp_rn; cc.language.language_constant = f"languageConstants/{digits(lang)}"
        ops.append(op)
    for raw in spec.get("negative_keywords") or []:
        ops.append(campaign_neg_op(client, camp_rn, raw))

    for i, g in enumerate(spec["ad_groups"]):
        ag_rn = ga.ad_group_path(cust, -(10 + i))
        op = client.get_type("MutateOperation"); ag = op.ad_group_operation.create
        ag.resource_name = ag_rn; ag.campaign = camp_rn; ag.name = g["name"]
        ag.type_ = E.AdGroupTypeEnum.SEARCH_STANDARD; ag.status = E.AdGroupStatusEnum.ENABLED
        # Without a bid, Google defaults the ad group to $0.01, which Maximize Clicks ignores but the UI shows.
        bid = g.get("cpc_bid") or (b.get("cpc_ceiling") if b.get("strategy") == "MAXIMIZE_CLICKS" else None)
        if bid: ag.cpc_bid_micros = micros(bid)
        ops.append(op)
        for raw in g["keywords"]: ops.append(kw_op(client, ag_rn, raw))
        for raw in g.get("negative_keywords") or []: ops.append(kw_op(client, ag_rn, raw, negative=True))

    summary = {"campaign": spec["name"], "dry_run": a.dry_run, "status": "PAUSED",
               "daily_budget": spec["daily_budget"], "bidding": b["strategy"],
               "locations": len(spec["locations"]), "campaign_negatives": len(spec.get("negative_keywords") or []),
               "ad_groups": [{"name": g["name"], "keywords": len(g["keywords"]),
                              "negatives": len(g.get("negative_keywords") or [])} for g in spec["ad_groups"]],
               "operations": len(ops), "warnings": warnings(client, cust, spec)}
    resp = mutate(client, cust, ops, a.dry_run)
    if a.dry_run:
        summary["validation"] = "PASSED (Google validated the full request; nothing was created)"
    else:
        rs = resp.mutate_operation_responses
        crn = next(r.campaign_result.resource_name for r in rs if r.campaign_result.resource_name)
        ag_rns = [r.ad_group_result.resource_name for r in rs if r.ad_group_result.resource_name]
        summary["campaign_id"] = crn.rsplit("/", 1)[1]
        for g, rn in zip(summary["ad_groups"], ag_rns): g["ad_group_id"] = rn.rsplit("/", 1)[1]
        summary["next"] = ("Write RSAs for each ad group with the google-ads-rsa skill, then review with: "
                           f"search_campaign.py list --customer {cust} --campaign {summary['campaign_id']}")
    print(json.dumps(summary, indent=2))

def cmd_add_keywords(client, a):
    errs = kw_errors(a.keywords, "keywords")
    if errs: print("\n".join(errs), file=sys.stderr); sys.exit(2)
    ag_rn = client.get_service("GoogleAdsService").ad_group_path(a.customer, digits(a.ad_group))
    ops = [kw_op(client, ag_rn, k, negative=a.negative, cpc=a.cpc) for k in a.keywords]
    mutate(client, a.customer, ops, a.dry_run)
    print(json.dumps({"ad_group_id": digits(a.ad_group), "negative": a.negative, "dry_run": a.dry_run,
                      "added": [fmt_kw(*parse_kw(k)) for k in a.keywords]}, indent=2))

def cmd_add_negatives(client, a):
    errs = kw_errors(a.keywords, "keywords")
    if errs: print("\n".join(errs), file=sys.stderr); sys.exit(2)
    camp_rn = client.get_service("GoogleAdsService").campaign_path(a.customer, digits(a.campaign))
    mutate(client, a.customer, [campaign_neg_op(client, camp_rn, k) for k in a.keywords], a.dry_run)
    print(json.dumps({"campaign_id": digits(a.campaign), "dry_run": a.dry_run,
                      "negatives_added": [fmt_kw(*parse_kw(k)) for k in a.keywords]}, indent=2))

def cmd_set_status(client, a):
    if bool(a.campaign) == bool(a.ad_group): sys.exit("pass exactly one of --campaign or --ad-group")
    ga, E = client.get_service("GoogleAdsService"), client.enums
    op = client.get_type("MutateOperation")
    if a.campaign:
        obj = op.campaign_operation.update
        obj.resource_name = ga.campaign_path(a.customer, digits(a.campaign))
        obj.status = getattr(E.CampaignStatusEnum, a.status)
        op.campaign_operation.update_mask.paths.append("status")
    else:
        obj = op.ad_group_operation.update
        obj.resource_name = ga.ad_group_path(a.customer, digits(a.ad_group))
        obj.status = getattr(E.AdGroupStatusEnum, a.status)
        op.ad_group_operation.update_mask.paths.append("status")
    mutate(client, a.customer, [op], a.dry_run)
    print(json.dumps({"resource": obj.resource_name, "status": a.status, "dry_run": a.dry_run}, indent=2))

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to google-ads.yaml (default ~/google-ads.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spec-template")
    s = sub.add_parser("list"); s.add_argument("--customer", required=True); s.add_argument("--campaign")
    s = sub.add_parser("keywords"); s.add_argument("--customer", required=True)
    s.add_argument("--campaign"); s.add_argument("--ad-group"); s.add_argument("--days", type=int, choices=[7, 14, 30], default=30)
    s = sub.add_parser("geo-suggest"); s.add_argument("names", nargs="+"); s.add_argument("--country", default="US")
    s = sub.add_parser("create"); s.add_argument("--customer", required=True); s.add_argument("--spec", required=True)
    s.add_argument("--dry-run", action="store_true", help="validate_only: nothing is created")
    s = sub.add_parser("add-keywords"); s.add_argument("--customer", required=True); s.add_argument("--ad-group", required=True)
    s.add_argument("keywords", nargs="+"); s.add_argument("--negative", action="store_true")
    s.add_argument("--cpc", type=float, help="keyword-level max CPC (manual bidding only)")
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("add-negatives"); s.add_argument("--customer", required=True); s.add_argument("--campaign", required=True)
    s.add_argument("keywords", nargs="+"); s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("set-status"); s.add_argument("--customer", required=True)
    s.add_argument("--campaign"); s.add_argument("--ad-group")
    s.add_argument("--status", required=True, choices=["ENABLED", "PAUSED"]); s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.cmd == "spec-template": return cmd_spec_template(None, a)
    if hasattr(a, "customer"): a.customer = digits(a.customer)
    client = load_client(a.config)
    try:
        globals()["cmd_" + a.cmd.replace("-", "_")](client, a)
    except GoogleAdsException as e:
        die_on_error(e)

if __name__ == "__main__":
    main()
