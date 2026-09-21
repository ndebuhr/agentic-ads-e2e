---
name: google-ads-asset-groups
description: >-
  Creates and reviews Performance Max asset groups in Google Ads: uploads
  generated images, text, and YouTube videos as assets and links them into a
  paused asset group on an existing PMax campaign via a bundled
  OAuth-authenticated script. Use this skill whenever the user wants to push
  creative into Google Ads, build or inspect an asset group, or check asset
  approval and ad strength.
---

# Google Ads Asset Groups Skill

This skill is the write path from generated creative into a Performance Max
campaign. Reads (campaigns, asset groups, ad strength) can go through
`search_search` on `google-ads-mcp`; all writes go through
`scripts/asset_group.py`, authenticated by `~/google-ads.yaml` (created once
with the `google-ads-auth` skill).

```bash
A=.agents/skills/google-ads-asset-groups/scripts/asset_group.py
```

## Workflow

### 1. Pick the Campaign
`$A list --customer ID` prints PMax campaigns with their asset groups,
primary status, ad strength, and whether brand guidelines are enabled. The
target must be an existing Performance Max campaign; create one in the UI or
with the campaign summary skill's data if none exists.

### 2. Gather Creative
Collect the assets the group needs, generating what is missing with the
image, video, and audio skills:

| Field | Count | Limits |
|---|---|---|
| headlines | 3 to 15 | 30 chars |
| long_headlines | 1 to 5 | 90 chars |
| descriptions | 2 to 5 | 90 chars, one under 60 |
| business_name | 1 | 25 chars |
| images.marketing | 1 to 20 | 1.91:1, resized to 1200x628 |
| images.square | 1 to 20 | 1:1, resized to 1200x1200 |
| images.portrait | 0 to 20 | 4:5, resized to 960x1200 |
| images.logo | 1 to 5 | 1:1, resized to 1200x1200 |
| youtube_video_ids | 0 to 5 | already uploaded to YouTube |

Any image works as input: the script center-crops to the target ratio,
resizes, and writes the prepared copies to `media/pmax/`. Prefer sources
that already match the ratio so the crop doesn't cut the product. Text must
not use ALL CAPS, repeated punctuation, or claims the landing page can't
back. Without a video, Google auto-generates one from the images.

### 3. Write the Spec
`$A spec-template > media/pmax/spec.json`, then fill it in. Include
`call_to_action` (for example `SHOP_NOW`, `LEARN_MORE`) and keep
`status` as `PAUSED`.

### 4. Validate, Then Create
```bash
$A create --customer ID --spec media/pmax/spec.json --dry-run
$A create --customer ID --spec media/pmax/spec.json
```
* The dry run checks counts and lengths locally, then sends the whole
  request with validate-only so Google reports policy or format errors
  without creating anything. Fix and repeat until clean.
* Confirm with the user before the real run. Everything is created in one
  atomic mutate: text assets, image assets, optional video and call to action,
  the asset group, and the links. If brand guidelines are enabled on the
  campaign, business name and logo are linked at campaign level (and skipped
  if already present).
* The output lists the asset group ID and each prepared image.

### 5. Review and Hand Off
* `$A assets --customer ID --asset-group AG_ID` shows every linked asset with
  approval and status. Report anything `DISAPPROVED` or `LIMITED` with the
  policy reason and offer a fix.
* Re-run `list` to read `ad_strength`; aim for GOOD or EXCELLENT by adding
  headlines, a portrait image, or a video.
* The group stays paused. Enabling it is a user action in the UI, or a
  follow-up request once they've reviewed the preview.

## Notes
* Image assets count toward the account's asset limits; reuse existing
  asset IDs for logos across groups when possible.
* Google may take a few hours to review new assets; approval fields show
  `UNDER_REVIEW` until then.
* Scripts run with `uv run`; the Pillow dependency handles resizing.
