#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-ads>=32,<33"]
# ///
"""Responsive search ads (write path). Auth: ~/google-ads.yaml (OAuth).

  rsa.py list        --customer ID (--campaign ID | --ad-group ID)
  rsa.py performance --customer ID --ad AD_GROUP_ID~AD_ID
  rsa.py lint        --spec spec.json [--customer ID] [--brand NAME]
  rsa.py create      --customer ID --spec spec.json [--dry-run]
  rsa.py set-status  --customer ID --ad AD_GROUP_ID~AD_ID --status ENABLED|PAUSED|REMOVED [--dry-run]
  rsa.py spec-template > spec.json

The spec (JSON) holds one or more ads:
  ads[{ad_group_id, final_urls[], path1, path2, status (PAUSED default),
       headlines[3-15, <=30 chars], descriptions[2-4, <=90 chars], keywords[] (optional)}]
A headline or description is a string, or {"text": ..., "pin": 1|2|3} to pin it
(descriptions pin to 1 or 2). lint checks hard limits (errors) and Ad Strength
habits (warnings); with --customer it also loads each ad group's keywords and
reports which ones no headline covers. create runs lint first and refuses on errors.
"""
import argparse, json, os, re, sys
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

LIMITS = {"headlines": (3, 15, 30, 3), "descriptions": (2, 4, 90, 2)}  # min, max, chars, pin slots
PIN_ENUM = {"headlines": "HEADLINE_{}", "descriptions": "DESCRIPTION_{}"}
PATH_MAX = 15
MAX_RSAS_PER_AD_GROUP = 3
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
REPEAT_PUNCT = re.compile(r"([!?.,])\1|[!?]{2,}")
SHOUT = re.compile(r"\b[A-Z]{4,}\b")
URLISH = re.compile(r"\b(?:https?://|www\.)|\.(?:com|net|org)\b", re.I)
PHONE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
STOP = {"a", "an", "the", "for", "and", "or", "to", "of", "in", "on", "with", "your", "my"}

def digits(s): return re.sub(r"\D", "", str(s or ""))

def die_on_error(e):
    for err in e.failure.errors:
        loc = ".".join(f.field_name + (f"[{f.index}]" if "index" in f else "") for f in err.location.field_path_elements)
        trig = f" trigger={err.trigger.string_value!r}" if err.trigger.string_value else ""
        print(f"ERROR {err.error_code}: {err.message}{trig}" + (f"  [{loc}]" if loc else ""), file=sys.stderr)
        pv = err.details.policy_violation_details
        if pv.external_policy_name:
            print(f"  policy: {pv.external_policy_name} on {pv.key.violating_text!r}", file=sys.stderr)
        for t in err.details.policy_finding_details.policy_topic_entries:
            print(f"  policy topic: {t.topic} ({t.type_.name})", file=sys.stderr)
    sys.exit(1)

def query(client, cust, gaql):
    return list(client.get_service("GoogleAdsService").search(customer_id=cust, query=gaql))

def items(vals):
    """Normalize spec entries to (text, pin or None)."""
    out = []
    for v in vals or []:
        out.append((v, None) if isinstance(v, str) else (v.get("text", ""), v.get("pin")))
    return out

def tokens(s):
    words = re.findall(r"[a-z0-9']+", s.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOP}

def strip_match(kw):
    kw = kw.strip()
    return kw[1:-1] if len(kw) > 1 and kw[0] in "[\"" and kw[-1] in "]\"" else kw

# ---------- lint ----------
def lint_ad(ad, i, keywords, brand):
    errs, warns = [], []
    w = f"ads[{i}]"
    if not ad.get("ad_group_id"): errs.append(f"{w}.ad_group_id is required")
    if not ad.get("final_urls"): errs.append(f"{w}.final_urls is required")
    for u in ad.get("final_urls") or []:
        if not u.startswith("https://"): warns.append(f"{w}.final_urls: {u} is not https")
    for k in ("path1", "path2"):
        v = ad.get(k) or ""
        if len(v) > PATH_MAX: errs.append(f"{w}.{k}: {v!r} is {len(v)} chars (max {PATH_MAX})")
        if " " in v: errs.append(f"{w}.{k}: no spaces allowed ({v!r})")
    if ad.get("path2") and not ad.get("path1"): errs.append(f"{w}: path2 needs path1")

    for field, (lo, hi, maxc, slots) in LIMITS.items():
        vals = items(ad.get(field))
        if not lo <= len(vals) <= hi: errs.append(f"{w}.{field}: need {lo}-{hi}, got {len(vals)}")
        seen = {}
        for text, pin in vals:
            tag = f"{w}.{field} {text!r}"
            if len(text) > maxc: errs.append(f"{tag} is {len(text)} chars (max {maxc})")
            if text != text.strip() or "  " in text: errs.append(f"{tag} has leading/trailing or double spaces")
            if EMOJI.search(text): errs.append(f"{tag} contains emoji or symbols")
            if REPEAT_PUNCT.search(text): errs.append(f"{tag} repeats punctuation")
            if field == "headlines" and "!" in text: errs.append(f"{tag}: headlines can't use '!'")
            if text.isupper() and len(text) > 3: errs.append(f"{tag} is all caps")
            elif SHOUT.search(text): warns.append(f"{tag} has an all-caps word; fine for acronyms, disapproved for emphasis")
            if URLISH.search(text): warns.append(f"{tag} looks like it contains a URL; use final_urls/paths instead")
            if PHONE.search(text): warns.append(f"{tag} contains a phone number; use a call asset instead")
            if pin is not None and pin not in range(1, slots + 1): errs.append(f"{tag}: pin must be 1-{slots}")
            key = text.lower().strip()
            if key in seen: errs.append(f"{tag} duplicates another {field[:-1]}")
            seen[key] = True

        pinned = [p for _, p in vals if p]
        if pinned:
            warns.append(f"{w}.{field}: {len(pinned)} pinned; each pin lowers Ad Strength. Pin only what legal or brand rules require.")
            for slot in set(pinned):
                if pinned.count(slot) == 1 and len(vals) > slots:
                    warns.append(f"{w}.{field}: only one asset pinned to position {slot}; pin 2-3 there so Google can rotate.")
        texts = [t for t, _ in vals]
        for a_i in range(len(texts)):
            for b_i in range(a_i + 1, len(texts)):
                ta, tb = tokens(texts[a_i]), tokens(texts[b_i])
                if ta and tb and len(ta & tb) / len(ta | tb) >= 0.6:
                    warns.append(f"{w}.{field}: {texts[a_i]!r} and {texts[b_i]!r} are near-duplicates; vary them for Ad Strength")

    heads = [t for t, _ in items(ad.get("headlines"))]
    descs = [t for t, _ in items(ad.get("descriptions"))]
    if len(heads) < 10: warns.append(f"{w}: {len(heads)} headlines; 10-15 distinct headlines is what reaches GOOD/EXCELLENT")
    if len(descs) < 4: warns.append(f"{w}: {len(descs)} descriptions; use all 4")
    if heads and sum(len(h) <= 20 for h in heads) < 2: warns.append(f"{w}: add a few short headlines (<=20 chars); mixed lengths serve more often")
    if brand and not any(brand.lower() in h.lower() for h in heads):
        warns.append(f"{w}: no headline mentions {brand!r}")

    coverage = None
    # One entry per keyword text: [exact] and "phrase" versions of the same words count once.
    kws, seen = [], set()
    for k in map(strip_match, ad.get("keywords") or keywords or []):
        if k.lower() not in seen: seen.add(k.lower()); kws.append(k)
    if kws:
        htoks = [tokens(h) for h in heads]
        covered = [k for k in kws if any(tokens(k) and tokens(k) <= ht for ht in htoks)]
        missing = [k for k in kws if k not in covered]
        coverage = {"keywords": len(kws), "in_a_headline": len(covered), "missing": missing}
        if len(covered) < min(3, len(kws)):
            warns.append(f"{w}: only {len(covered)} of {len(kws)} keywords appear in a headline; Ad relevance and Ad Strength both reward keyword headlines")
    return errs, warns, coverage

def ad_group_context(client, cust, ag_ids):
    """Keywords, type, campaign channel, and RSA count for each ad group in the spec."""
    if not ag_ids: return {}
    ids = ",".join(sorted(ag_ids))
    ctx = {i: {"keywords": [], "type": None, "rsas": 0} for i in ag_ids}
    for r in query(client, cust, f"""SELECT ad_group.id, ad_group.name, ad_group.type, campaign.name FROM ad_group WHERE ad_group.id IN ({ids})"""):
        ctx[str(r.ad_group.id)].update(type=r.ad_group.type_.name, name=r.ad_group.name, campaign=r.campaign.name)
    for r in query(client, cust, f"""SELECT ad_group.id, ad_group_criterion.keyword.text FROM ad_group_criterion
            WHERE ad_group.id IN ({ids}) AND ad_group_criterion.type = 'KEYWORD'
              AND ad_group_criterion.negative = FALSE AND ad_group_criterion.status != 'REMOVED'"""):
        ctx[str(r.ad_group.id)]["keywords"].append(r.ad_group_criterion.keyword.text)
    for r in query(client, cust, f"""SELECT ad_group.id FROM ad_group_ad WHERE ad_group.id IN ({ids})
            AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD' AND ad_group_ad.status = 'ENABLED'"""):
        ctx[str(r.ad_group.id)]["rsas"] += 1
    return ctx

def run_lint(spec, client=None, cust=None, brand=None, adding=False):
    ads = spec.get("ads") or []
    ctx = ad_group_context(client, cust, {digits(a.get("ad_group_id")) for a in ads if a.get("ad_group_id")}) if client else {}
    report, total_errs = [], 0
    for i, ad in enumerate(ads):
        c = ctx.get(digits(ad.get("ad_group_id")), {})
        errs, warns, cov = lint_ad(ad, i, c.get("keywords"), brand)
        if client:
            if c.get("type") is None: errs.append(f"ads[{i}]: ad group {ad.get('ad_group_id')} not found")
            elif c["type"] != "SEARCH_STANDARD": errs.append(f"ads[{i}]: ad group is {c['type']}, not SEARCH_STANDARD")
            new_here = sum(1 for x in ads if digits(x.get("ad_group_id")) == digits(ad.get("ad_group_id"))
                           and (x.get("status") or "PAUSED") == "ENABLED")
            if adding and c.get("rsas", 0) + new_here > MAX_RSAS_PER_AD_GROUP:
                errs.append(f"ads[{i}]: ad group would have more than {MAX_RSAS_PER_AD_GROUP} enabled RSAs; pause one first")
        total_errs += len(errs)
        report.append({"ad": i, "ad_group_id": ad.get("ad_group_id"), "ad_group": c.get("name"),
                       "headlines": len(ad.get("headlines") or []), "descriptions": len(ad.get("descriptions") or []),
                       "errors": errs, "warnings": warns, "keyword_coverage": cov})
    return report, total_errs

# ---------- commands ----------
def cmd_spec_template(client, a):
    print(json.dumps({"ads": [{
        "ad_group_id": "1234567890",
        "final_urls": ["https://www.example.com/products/gift-box"], "path1": "gifts", "path2": "box",
        "status": "PAUSED",
        "headlines": [{"text": "Example Co Gift Boxes", "pin": 1}, {"text": "Shop Example Co", "pin": 1},
                      "Curated Gift Boxes", "Handmade Gift Boxes",
                      "Small Batch, Big Smiles", "Ships In Two Days", "Gifts Under $40",
                      "Free Shipping Over $50", "Made By Local Makers", "Shop Gift Boxes Today",
                      "Gift Boxes For Every Occasion"],
        "descriptions": ["Curated boxes of handmade goods from local makers. Ships in two days.",
                         "Pick a box or build your own. Free shipping on orders over $50.",
                         "Thoughtful gifts without the guesswork. Order today.",
                         "Every box is packed by hand and ready to give."]}]}, indent=2))

def cmd_lint(client, a):
    spec = json.load(open(a.spec))
    report, n = run_lint(spec, client, a.customer, a.brand)
    print(json.dumps(report, indent=2))
    if n: sys.exit(2)

def build_ops(client, cust, spec):
    ops, E = [], client.enums
    ag_svc = client.get_service("AdGroupService")
    for ad in spec["ads"]:
        op = client.get_type("AdGroupAdOperation"); aga = op.create
        aga.ad_group = ag_svc.ad_group_path(cust, digits(ad["ad_group_id"]))
        aga.status = getattr(E.AdGroupAdStatusEnum, ad.get("status") or "PAUSED")
        aga.ad.final_urls.extend(ad["final_urls"])
        rsa = aga.ad.responsive_search_ad
        if ad.get("path1"): rsa.path1 = ad["path1"]
        if ad.get("path2"): rsa.path2 = ad["path2"]
        for field in ("headlines", "descriptions"):
            for text, pin in items(ad[field]):
                asset = client.get_type("AdTextAsset"); asset.text = text
                if pin: asset.pinned_field = getattr(E.ServedAssetFieldTypeEnum, PIN_ENUM[field].format(pin))
                getattr(rsa, field).append(asset)
        ops.append(op)
    return ops

def cmd_create(client, a):
    spec = json.load(open(a.spec))
    report, n = run_lint(spec, client, a.customer, a.brand, adding=True)
    if n:
        print(json.dumps(report, indent=2)); print(f"{n} lint error(s); nothing sent.", file=sys.stderr); sys.exit(2)
    req = client.get_type("MutateAdGroupAdsRequest")
    req.customer_id = a.customer; req.operations.extend(build_ops(client, a.customer, spec)); req.validate_only = a.dry_run
    resp = client.get_service("AdGroupAdService").mutate_ad_group_ads(request=req)
    out = {"dry_run": a.dry_run, "ads": [{"ad_group_id": r["ad_group_id"], "ad_group": r["ad_group"],
                                         "warnings": r["warnings"], "keyword_coverage": r["keyword_coverage"]} for r in report]}
    if a.dry_run:
        out["validation"] = "PASSED (Google validated text, policy, and URLs; nothing was created)"
    else:
        for o, res in zip(out["ads"], resp.results):
            o["ad"] = res.resource_name.rsplit("/", 1)[1]
        out["next"] = f"Ad Strength and approval settle within hours: rsa.py list --customer {a.customer} --ad-group <id>"
    print(json.dumps(out, indent=2))

def cmd_list(client, a):
    if not (a.campaign or a.ad_group): sys.exit("pass --campaign or --ad-group")
    cond = f"ad_group.id = {digits(a.ad_group)}" if a.ad_group else f"campaign.id = {digits(a.campaign)}"
    rows = query(client, a.customer, f"""
        SELECT ad_group.id, ad_group.name, ad_group_ad.ad.id, ad_group_ad.status, ad_group_ad.primary_status,
               ad_group_ad.ad_strength, ad_group_ad.policy_summary.approval_status,
               ad_group_ad.policy_summary.policy_topic_entries, ad_group_ad.ad.final_urls,
               ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions,
               ad_group_ad.ad.responsive_search_ad.path1, ad_group_ad.ad.responsive_search_ad.path2,
               ad_group_ad.action_items
        FROM ad_group_ad WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD' AND ad_group_ad.status != 'REMOVED' AND {cond}""")
    def txt(assets):
        return [a.text + (f"  [pin {a.pinned_field.name}]" if a.pinned_field.name not in ("UNSPECIFIED", "UNKNOWN") else "") for a in assets]
    print(json.dumps([{
        "ad": f"{r.ad_group.id}~{r.ad_group_ad.ad.id}", "ad_group": r.ad_group.name,
        "status": r.ad_group_ad.status.name, "primary_status": r.ad_group_ad.primary_status.name,
        "ad_strength": r.ad_group_ad.ad_strength.name, "action_items": list(r.ad_group_ad.action_items),
        "approval": r.ad_group_ad.policy_summary.approval_status.name,
        "policy_topics": [p.topic for p in r.ad_group_ad.policy_summary.policy_topic_entries],
        "final_urls": list(r.ad_group_ad.ad.final_urls),
        "path": "/".join(p for p in (r.ad_group_ad.ad.responsive_search_ad.path1, r.ad_group_ad.ad.responsive_search_ad.path2) if p),
        "headlines": txt(r.ad_group_ad.ad.responsive_search_ad.headlines),
        "descriptions": txt(r.ad_group_ad.ad.responsive_search_ad.descriptions)} for r in rows], indent=2))

def split_ad(s):
    ag, _, ad = s.partition("~")
    if not (digits(ag) and digits(ad)): sys.exit("--ad must be AD_GROUP_ID~AD_ID (as printed by list)")
    return digits(ag), digits(ad)

def cmd_performance(client, a):
    ag, ad = split_ad(a.ad)
    rows = query(client, a.customer, f"""
        SELECT ad_group_ad_asset_view.field_type, ad_group_ad_asset_view.performance_label,
               ad_group_ad_asset_view.pinned_field, ad_group_ad_asset_view.enabled,
               ad_group_ad_asset_view.policy_summary.approval_status, asset.text_asset.text,
               metrics.impressions, metrics.clicks
        FROM ad_group_ad_asset_view
        WHERE ad_group.id = {ag} AND ad_group_ad.ad.id = {ad} AND segments.date DURING LAST_30_DAYS""")
    print(json.dumps([{
        "field": r.ad_group_ad_asset_view.field_type.name, "text": r.asset.text_asset.text,
        "label": r.ad_group_ad_asset_view.performance_label.name,
        "pinned": r.ad_group_ad_asset_view.pinned_field.name, "enabled": r.ad_group_ad_asset_view.enabled,
        "approval": r.ad_group_ad_asset_view.policy_summary.approval_status.name,
        "impressions_30d": r.metrics.impressions, "clicks_30d": r.metrics.clicks} for r in rows], indent=2))

def cmd_set_status(client, a):
    ag, ad = split_ad(a.ad)
    op = client.get_type("AdGroupAdOperation")
    rn = client.get_service("AdGroupAdService").ad_group_ad_path(a.customer, ag, ad)
    if a.status == "REMOVED":
        op.remove = rn
    else:
        op.update.resource_name = rn
        op.update.status = getattr(client.enums.AdGroupAdStatusEnum, a.status)
        op.update_mask.paths.append("status")
    req = client.get_type("MutateAdGroupAdsRequest")
    req.customer_id = a.customer; req.operations.append(op); req.validate_only = a.dry_run
    client.get_service("AdGroupAdService").mutate_ad_group_ads(request=req)
    print(json.dumps({"ad": f"{ag}~{ad}", "status": a.status, "dry_run": a.dry_run}, indent=2))

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to google-ads.yaml (default ~/google-ads.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spec-template")
    s = sub.add_parser("list"); s.add_argument("--customer", required=True); s.add_argument("--campaign"); s.add_argument("--ad-group")
    s = sub.add_parser("performance"); s.add_argument("--customer", required=True); s.add_argument("--ad", required=True)
    s = sub.add_parser("lint"); s.add_argument("--spec", required=True); s.add_argument("--customer"); s.add_argument("--brand")
    s = sub.add_parser("create"); s.add_argument("--customer", required=True); s.add_argument("--spec", required=True)
    s.add_argument("--brand"); s.add_argument("--dry-run", action="store_true", help="validate_only: nothing is created")
    s = sub.add_parser("set-status"); s.add_argument("--customer", required=True); s.add_argument("--ad", required=True)
    s.add_argument("--status", required=True, choices=["ENABLED", "PAUSED", "REMOVED"]); s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.cmd == "spec-template": return cmd_spec_template(None, a)
    if a.cmd == "lint" and not a.customer: return cmd_lint(None, a)
    a.customer = digits(a.customer)
    client = load_client(a.config)
    try:
        globals()["cmd_" + a.cmd.replace("-", "_")](client, a)
    except GoogleAdsException as e:
        die_on_error(e)

if __name__ == "__main__":
    main()
