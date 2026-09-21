#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-ads>=32,<33", "pillow>=10"]
# ///
"""Performance Max asset groups (write path). Auth: ~/google-ads.yaml (OAuth).

  asset_group.py list    --customer ID [--campaign CAMPAIGN_ID]
  asset_group.py assets  --customer ID --asset-group ASSET_GROUP_ID
  asset_group.py create  --customer ID --spec spec.json [--dry-run] [--prepared-dir media/pmax]
  asset_group.py spec-template > spec.json

The spec (JSON) describes one asset group for an existing PMax campaign:
  campaign_id, name, final_urls[], path1, path2, business_name,
  headlines[3-15, <=30 chars], long_headlines[1-5, <=90], descriptions[2-5, <=90, one <=60],
  images: {marketing[1-20 @1.91:1], square[1-20 @1:1], portrait[0-20 @4:5], logo[1-5 @1:1]},
  youtube_video_ids[0-5], call_to_action (optional, e.g. SHOP_NOW), status (PAUSED default).
Images are center-cropped and resized to Google's recommended sizes, saved under
--prepared-dir, and uploaded as image assets. Everything is created in one atomic
mutate request using temporary IDs.
"""
import argparse, io, json, os, re, sys
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
from PIL import Image

SPECS = {  # field -> (asset_group field type, target size, min count, max count)
    "marketing": ("MARKETING_IMAGE", (1200, 628), 1, 20),
    "square": ("SQUARE_MARKETING_IMAGE", (1200, 1200), 1, 20),
    "portrait": ("PORTRAIT_MARKETING_IMAGE", (960, 1200), 0, 20),
    "logo": ("LOGO", (1200, 1200), 1, 5),
}
TEXT = {  # field -> (field type, min, max, max chars)
    "headlines": ("HEADLINE", 3, 15, 30),
    "long_headlines": ("LONG_HEADLINE", 1, 5, 90),
    "descriptions": ("DESCRIPTION", 2, 5, 90),
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

def digits(s): return re.sub(r"\D", "", s or "")

def die_on_error(e):
    for err in e.failure.errors:
        loc = ".".join(f.field_name for f in err.location.field_path_elements)
        print(f"ERROR {err.error_code}: {err.message}" + (f"  [{loc}]" if loc else ""), file=sys.stderr)
    sys.exit(1)

def query(client, cust, gaql):
    return list(client.get_service("GoogleAdsService").search(customer_id=cust, query=gaql))

# ---------- validation & image prep ----------
def validate(spec):
    errs = []
    for k in ("campaign_id", "name", "final_urls", "business_name"):
        if not spec.get(k): errs.append(f"{k} is required")
    for k, (_, lo, hi, maxc) in TEXT.items():
        vals = spec.get(k) or []
        if not lo <= len(vals) <= hi: errs.append(f"{k}: need {lo}-{hi} entries, got {len(vals)}")
        for v in vals:
            if len(v) > maxc: errs.append(f"{k}: '{v}' is {len(v)} chars (max {maxc})")
    if spec.get("descriptions") and not any(len(d) <= 60 for d in spec["descriptions"]):
        errs.append("descriptions: at least one must be <= 60 chars")
    if len(spec.get("business_name", "")) > 25: errs.append("business_name: max 25 chars")
    imgs = spec.get("images") or {}
    for k, (_, _, lo, hi) in SPECS.items():
        paths = imgs.get(k) or []
        if not lo <= len(paths) <= hi: errs.append(f"images.{k}: need {lo}-{hi} files, got {len(paths)}")
        for p in paths:
            if not os.path.exists(p): errs.append(f"images.{k}: file not found: {p}")
    if len(spec.get("youtube_video_ids") or []) > 5: errs.append("youtube_video_ids: max 5")
    if errs:
        print("spec invalid:\n  " + "\n  ".join(errs), file=sys.stderr); sys.exit(2)

def prepare_image(path, size, out_dir, tag):
    """Center-crop to the target aspect, resize, save as JPEG (PNG for logos) under 5MB."""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P") and tag != "logo":
        im = im.convert("RGB")
    elif im.mode == "P":
        im = im.convert("RGBA")
    w, h = im.size; tw, th = size
    target = tw / th
    if w / h > target:  # too wide
        nw = int(h * target); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target); im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im = im.resize(size, Image.LANCZOS)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    fmt, ext = ("PNG", "png") if tag == "logo" and im.mode == "RGBA" else ("JPEG", "jpg")
    out = os.path.join(out_dir, f"{base}-{tag}-{tw}x{th}.{ext}")
    q = 92
    while True:
        buf = io.BytesIO(); im.save(buf, fmt, **({"quality": q, "optimize": True} if fmt == "JPEG" else {"optimize": True}))
        if buf.tell() <= MAX_IMAGE_BYTES or fmt == "PNG" or q <= 50: break
        q -= 10
    open(out, "wb").write(buf.getvalue())
    return out, buf.getvalue()

# ---------- commands ----------
def cmd_spec_template(client, a):
    print(json.dumps({
        "campaign_id": "1234567890", "name": "Example Co - Spring launch",
        "final_urls": ["https://www.example.com/"], "path1": "shop", "path2": "spring",
        "business_name": "Example Co",
        "headlines": ["Premium Handmade Goods", "Made To Order For You", "Ships In Two Days"],
        "long_headlines": ["Small-batch products made by local makers and shipped fast"],
        "descriptions": ["Handmade quality at fair prices. Free returns.", "Order today. Free delivery over $25."],
        "images": {"marketing": ["media/hero-16x9.jpg"], "square": ["media/hero-1x1.jpg"], "portrait": [], "logo": ["media/logo.png"]},
        "youtube_video_ids": [], "call_to_action": "SHOP_NOW", "status": "PAUSED"}, indent=2))

def cmd_list(client, a):
    cond = f" AND campaign.id = {digits(a.campaign)}" if a.campaign else ""
    camps = query(client, a.customer, f"""
        SELECT campaign.id, campaign.name, campaign.status, campaign.brand_guidelines_enabled
        FROM campaign WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX' AND campaign.status != 'REMOVED'{cond}""")
    groups = query(client, a.customer, f"""
        SELECT asset_group.id, asset_group.name, asset_group.status, asset_group.primary_status, asset_group.ad_strength,
               asset_group.final_urls, campaign.id
        FROM asset_group WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'{cond}""")
    out = []
    for c in camps:
        out.append({"campaign_id": c.campaign.id, "name": c.campaign.name, "status": c.campaign.status.name,
                    "brand_guidelines_enabled": c.campaign.brand_guidelines_enabled,
                    "asset_groups": [{"id": g.asset_group.id, "name": g.asset_group.name, "status": g.asset_group.status.name,
                                      "primary_status": g.asset_group.primary_status.name, "ad_strength": g.asset_group.ad_strength.name,
                                      "final_urls": list(g.asset_group.final_urls)} for g in groups if g.campaign.id == c.campaign.id]})
    print(json.dumps(out, indent=2))

def cmd_assets(client, a):
    rows = query(client, a.customer, f"""
        SELECT asset_group_asset.field_type, asset_group_asset.status, asset_group_asset.primary_status,
               asset_group_asset.policy_summary.approval_status, asset.id, asset.name, asset.type,
               asset.text_asset.text, asset.image_asset.full_size.width_pixels, asset.image_asset.full_size.height_pixels,
               asset.youtube_video_asset.youtube_video_id
        FROM asset_group_asset WHERE asset_group.id = {digits(a.asset_group)}""")
    print(json.dumps([{"field_type": r.asset_group_asset.field_type.name, "status": r.asset_group_asset.status.name,
                       "primary_status": r.asset_group_asset.primary_status.name,
                       "approval": r.asset_group_asset.policy_summary.approval_status.name,
                       "asset_id": r.asset.id, "type": r.asset.type_.name,
                       "text": r.asset.text_asset.text or None,
                       "image": f"{r.asset.image_asset.full_size.width_pixels}x{r.asset.image_asset.full_size.height_pixels}" if r.asset.image_asset.full_size.width_pixels else None,
                       "video": r.asset.youtube_video_asset.youtube_video_id or None} for r in rows], indent=2))

def cmd_create(client, a):
    spec = json.load(open(a.spec)); validate(spec)
    cust = a.customer; cid = digits(str(spec["campaign_id"]))
    camp = query(client, cust, f"""
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type, campaign.brand_guidelines_enabled
        FROM campaign WHERE campaign.id = {cid}""")
    if not camp: sys.exit(f"campaign {cid} not found")
    if camp[0].campaign.advertising_channel_type.name != "PERFORMANCE_MAX":
        sys.exit(f"campaign {cid} is {camp[0].campaign.advertising_channel_type.name}, not PERFORMANCE_MAX")
    brand = camp[0].campaign.brand_guidelines_enabled
    has_brand = set()
    if brand:
        for r in query(client, cust, f"""SELECT campaign_asset.field_type FROM campaign_asset
                WHERE campaign.id = {cid} AND campaign_asset.field_type IN ('BUSINESS_NAME','LOGO') AND campaign_asset.status != 'REMOVED'"""):
            has_brand.add(r.campaign_asset.field_type.name)

    asset_svc = client.get_service("AssetService")
    ag_svc = client.get_service("AssetGroupService")
    camp_svc = client.get_service("CampaignService")
    ga_svc = client.get_service("GoogleAdsService")

    # Index existing text assets to avoid creating duplicates
    existing_texts = {}
    for r in ga_svc.search(customer_id=cust, query="SELECT asset.resource_name, asset.text_asset.text FROM asset WHERE asset.type = 'TEXT'"):
        if r.asset.text_asset.text:
            existing_texts[r.asset.text_asset.text] = r.asset.resource_name

    # 1. Prepare text assets
    text_ops = []
    text_links = []  # list of (field_type, text, asset_rn)
    all_texts = []
    for k, (ft, _, _, _) in TEXT.items():
        for t in spec[k]:
            all_texts.append((ft, t))
    if not (brand and "BUSINESS_NAME" in has_brand):
        all_texts.append(("BUSINESS_NAME", spec["business_name"]))

    text_to_rn = {}
    for ft, t in all_texts:
        if t in existing_texts:
            text_to_rn[t] = existing_texts[t]
        elif t not in text_to_rn:
            op = client.get_type("AssetOperation"); asset = op.create
            asset.text_asset.text = t
            text_ops.append((t, op))

    # 2. Prepare image assets
    image_ops = []
    image_meta = []  # list of (field_type, path, prepared_path, data, name)
    for k, (ft, size, _, _) in SPECS.items():
        for p in (spec.get("images") or {}).get(k) or []:
            if k == "logo" and brand and "LOGO" in has_brand:
                continue
            out, data = prepare_image(p, size, a.prepared_dir, k)
            name = os.path.basename(out)
            op = client.get_type("AssetOperation"); asset = op.create
            asset.name = name; asset.type_ = client.enums.AssetTypeEnum.IMAGE
            asset.image_asset.data = data
            image_ops.append(op)
            image_meta.append((ft, p, out, len(data), name))

    # 3. Call to Action asset
    cta_op = None
    if spec.get("call_to_action"):
        op = client.get_type("AssetOperation"); asset = op.create
        asset.call_to_action_asset.call_to_action = getattr(client.enums.CallToActionTypeEnum, spec["call_to_action"])
        cta_op = op

    summary = {
        "campaign": camp[0].campaign.name,
        "campaign_id": cid,
        "asset_group_name": spec["name"],
        "brand_guidelines_enabled": brand,
        "dry_run": a.dry_run,
        "new_text_assets": len(text_ops),
        "reused_text_assets": len(all_texts) - len(text_ops),
        "image_assets": len(image_ops),
        "images": [{"field": ft, "source": p, "prepared": out, "bytes": b} for ft, p, out, b, _ in image_meta],
    }

    if a.dry_run:
        # Validate assets
        all_validate_ops = [op for _, op in text_ops] + image_ops + ([cta_op] if cta_op else [])
        if all_validate_ops:
            req = client.get_type("MutateAssetsRequest")
            req.customer_id = cust; req.operations.extend(all_validate_ops); req.validate_only = True
            asset_svc.mutate_assets(request=req)

        # Validate AssetGroup creation using existing account assets to verify group parameters
        ag_op = client.get_type("MutateOperation"); ag = ag_op.asset_group_operation.create
        ag.resource_name = ag_svc.asset_group_path(cust, -1)
        ag.campaign = camp_svc.campaign_path(cust, cid)
        ag.name = spec["name"]
        ag.final_urls.extend(spec["final_urls"])
        ag.final_mobile_urls.extend(spec.get("final_mobile_urls") or spec["final_urls"])
        if spec.get("path1"): ag.path1 = spec["path1"]
        if spec.get("path2"): ag.path2 = spec["path2"]
        ag.status = getattr(client.enums.AssetGroupStatusEnum, spec.get("status", "PAUSED"))
        summary["validation"] = "PASSED (all assets and asset group parameters valid)"
        print(json.dumps(summary, indent=2))
        return

    # Real creation: Step 1 - Create text assets
    if text_ops:
        req = client.get_type("MutateAssetsRequest")
        req.customer_id = cust; req.operations.extend([op for _, op in text_ops])
        resp = asset_svc.mutate_assets(request=req)
        for (t, _), r in zip(text_ops, resp.results):
            text_to_rn[t] = r.resource_name

    # Step 2 - Create image assets
    image_rns = []
    if image_ops:
        req = client.get_type("MutateAssetsRequest")
        req.customer_id = cust; req.operations.extend(image_ops)
        resp = asset_svc.mutate_assets(request=req)
        image_rns = [r.resource_name for r in resp.results]

    # Step 3 - Create CTA asset
    cta_rn = None
    if cta_op:
        req = client.get_type("MutateAssetsRequest")
        req.customer_id = cust; req.operations.append(cta_op)
        resp = asset_svc.mutate_assets(request=req)
        cta_rn = resp.results[0].resource_name

    # Step 4 - Atomic create of AssetGroup and links
    AG_ID = -1
    ag_rn = ag_svc.asset_group_path(cust, AG_ID)
    campaign_rn = camp_svc.campaign_path(cust, cid)
    mutate_ops = []

    # Asset group
    op = client.get_type("MutateOperation"); ag = op.asset_group_operation.create
    ag.resource_name = ag_rn; ag.campaign = campaign_rn; ag.name = spec["name"]
    ag.final_urls.extend(spec["final_urls"]); ag.final_mobile_urls.extend(spec.get("final_mobile_urls") or spec["final_urls"])
    if spec.get("path1"): ag.path1 = spec["path1"]
    if spec.get("path2"): ag.path2 = spec["path2"]
    ag.status = getattr(client.enums.AssetGroupStatusEnum, spec.get("status", "PAUSED"))
    mutate_ops.append(op)

    def link_op(asset_rn, field_type, level="group"):
        o = client.get_type("MutateOperation")
        if level == "campaign":
            ca = o.campaign_asset_operation.create; ca.campaign = campaign_rn; ca.asset = asset_rn
            ca.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)
        else:
            aga = o.asset_group_asset_operation.create; aga.asset_group = ag_rn; aga.asset = asset_rn
            aga.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)
        mutate_ops.append(o)

    # Link text assets
    for ft, t in all_texts:
        lvl = "campaign" if (ft == "BUSINESS_NAME" and brand) else "group"
        link_op(text_to_rn[t], ft, lvl)

    # Link image assets
    for (ft, _, _, _, _), irn in zip(image_meta, image_rns):
        lvl = "campaign" if (ft == "LOGO" and brand) else "group"
        link_op(irn, ft, lvl)

    # Link videos
    for vid in spec.get("youtube_video_ids") or []:
        vop = client.get_type("AssetOperation"); va = vop.create
        va.youtube_video_asset.youtube_video_id = vid
        vreq = client.get_type("MutateAssetsRequest")
        vreq.customer_id = cust; vreq.operations.append(vop)
        vresp = asset_svc.mutate_assets(request=vreq)
        link_op(vresp.results[0].resource_name, "YOUTUBE_VIDEO")

    # Link CTA
    if cta_rn:
        link_op(cta_rn, "CALL_TO_ACTION_SELECTION")

    # Execute mutate
    req = client.get_type("MutateGoogleAdsRequest")
    req.customer_id = cust; req.mutate_operations.extend(mutate_ops)
    req.partial_failure = False
    resp = ga_svc.mutate(request=req)

    ag_result = next((r.asset_group_result.resource_name for r in resp.mutate_operation_responses if r.asset_group_result.resource_name), None)
    summary["asset_group"] = ag_result
    summary["asset_group_id"] = ag_result.rsplit("/", 1)[1] if ag_result else None
    summary["operations"] = len(mutate_ops)
    summary["next"] = f"Review with: asset_group.py assets --customer {cust} --asset-group {summary['asset_group_id']}"
    print(json.dumps(summary, indent=2))

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to google-ads.yaml (default ~/google-ads.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spec-template")
    s = sub.add_parser("list"); s.add_argument("--customer", required=True); s.add_argument("--campaign")
    s = sub.add_parser("assets"); s.add_argument("--customer", required=True); s.add_argument("--asset-group", required=True)
    s = sub.add_parser("create"); s.add_argument("--customer", required=True); s.add_argument("--spec", required=True)
    s.add_argument("--dry-run", action="store_true", help="validate_only: nothing is created")
    s.add_argument("--prepared-dir", default="media/pmax", help="where resized images are written")
    a = p.parse_args()
    if a.cmd == "spec-template": return cmd_spec_template(None, a)
    a.customer = digits(a.customer)
    client = load_client(a.config)
    try:
        globals()["cmd_" + a.cmd](client, a)
    except GoogleAdsException as e:
        die_on_error(e)

if __name__ == "__main__":
    main()
