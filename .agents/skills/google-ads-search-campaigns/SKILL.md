---
name: google-ads-search-campaigns
description: >-
  Builds and maintains standard (non-Performance Max) Google Search campaigns:
  creates a paused campaign with budget, bidding, locations, ad groups,
  keywords, and negatives in one atomic request, then adds keywords and
  negatives, reviews Quality Score, and pauses or enables via a bundled
  OAuth-authenticated script. Use this skill whenever the user wants a Search
  campaign, ad groups, keywords, match types, negative keywords, geo
  targeting, or keyword Quality Score.
---

# Google Ads Search Campaigns Skill

This skill covers campaign structure: the campaign, its ad groups, and the
keywords that trigger them. Ad copy is the `google-ads-rsa` skill's job; an ad
group with no ads won't serve. Reads can also go through `search_search` on
`google-ads-mcp`. All writes go through `scripts/search_campaign.py`,
authenticated by `~/google-ads.yaml` (created once with the `google-ads-auth`
skill).

```bash
S=.agents/skills/google-ads-search-campaigns/scripts/search_campaign.py
```

`$W` is the project's workspace for specs and media: a Cloud Storage path such as
`gs://my-bucket`, or a local folder such as `.`. The project's `AGENTS.md` says which.
The scripts read and write `gs://` paths directly; to save a command's output to
one from a shell, pipe it: `... | gcloud storage cp - $W/specs/example.json`.

Run the script directly (`$S ...`), not with `python3 $S`: its shebang runs
`uv`, which installs the `google-ads` dependency.

## Workflow

### 0. Check Auth
Run `.agents/skills/google-ads-auth/scripts/setup_oauth.py --check` before
anything else. It prints `OK` and the accessible customer IDs. On
`invalid_rapt` or `invalid_grant`, follow the `google-ads-auth` skill; the
consent flow opens a browser, so ask the user to run it with `! <command>`.

### 1. Identify Customer and Existing Coverage
Normalize the customer ID to digits. If the user didn't give one, use the IDs
from the auth check (or `customers_list_accessible_customers` on
`google-ads-mcp` if it is connected), and ask if there are several. Don't
grep the repo for 10-digit numbers; lock files and hashes match. Run
`$S list --customer ID` to see the Search campaigns and ad groups that already
exist, so the new campaign doesn't bid against them on the same keywords.

### 2. Plan Themes and Keywords
Group products or services into ad groups of 5 to 20 closely related keywords.
One theme per ad group lets the RSA headlines repeat the keywords. Start from
the landing pages: each ad group should have one obvious final URL.

* Write keywords in Editor notation: `[exact]`, `"phrase"`, or bare broad.
  Under `MANUAL_CPC` or `MAXIMIZE_CLICKS`, stick to phrase and exact. Broad
  match only behaves with conversion-based Smart Bidding.
* Add negatives up front: job seekers, DIY and how-to searches, free,
  wholesale, and competitor or unrelated meanings of ambiguous words.
  Campaign-level negatives cover every ad group; ad group negatives keep
  sibling ad groups from overlapping.

### 3. Pick Locations, Budget, and Bidding
* Get location IDs from the `google-ads-geo-targets` skill, which looks them
  up offline with no sign-in or API call. `2840` is the whole US. Use
  `$S geo-suggest "Austin, TX" 78701` only for reach estimates, or for US DMA
  (metro) regions, which the offline list leaves out.
* `location_presence_only: true` (the default) skips people who are only
  researching the area.
* Bidding: `MAXIMIZE_CLICKS` with a `cpc_ceiling` for a new account with no
  conversion data. `MAXIMIZE_CONVERSIONS` (optional `target_cpa`) or
  `MAXIMIZE_CONVERSION_VALUE` (optional `target_roas`) once primary conversion
  actions are recording. Use `MANUAL_CPC` with `cpc_bid` per ad group only for
  tight control. Under `MAXIMIZE_CLICKS`, ad groups without `cpc_bid` get
  the `cpc_ceiling` as their default bid (otherwise the UI shows Google's
  $0.01 default, which Smart Bidding ignores). The script warns if a
  conversion strategy has no enabled conversions to optimize toward.
* Keep `search_partners` and `display_expansion` off unless the user asks.

### 4. Write the Spec
Save the output of `$S spec-template` as `$W/specs/search/campaign.json`, then fill it in. Languages
default to English (`1000`).

### 5. Validate, Then Create
```bash
$S create --customer ID --spec $W/specs/search/campaign.json --dry-run
$S create --customer ID --spec $W/specs/search/campaign.json
```
* The dry run checks keyword syntax and limits locally, then Google
  validates the whole request without creating anything. Fix errors and
  read the `warnings` list back to the user.
* Confirm the budget, bidding, and locations with the user before the real
  run. Budget, campaign, targeting, ad groups, keywords, and negatives are
  created together, or none are if anything fails. The campaign is always
  created **PAUSED**.
* The output has the campaign ID and each ad group ID. Hand those to the
  `google-ads-rsa` skill to write at least one RSA per ad group.

### 6. Maintain
* `$S keywords --customer ID --campaign ID` lists keywords with status,
  approval, Quality Score and its three parts, and last-30-day metrics.
  `BELOW_AVERAGE` ad relevance means the RSA headlines need the keyword.
  `BELOW_AVERAGE` landing page experience points at the page.
* `$S add-keywords --customer ID --ad-group ID '"new phrase"' '[new exact]'`
  adds keywords. Add `--negative` to add ad group negatives instead.
  `$S add-negatives --customer ID --campaign ID free "how to"` adds
  campaign-level negatives. Mine candidates from the search terms report
  (`search_term_view` via `search_search`).
* `$S set-status --customer ID --campaign ID --status ENABLED` turns the
  campaign on. Only do this after the user has explicitly approved it, every
  ad group has an approved RSA, and conversion tracking is in place. Works
  with `--ad-group` too.
* Every write command accepts `--dry-run`.

## Notes
* Changing the budget or bidding strategy, ad schedules, device bid
  adjustments, and assets (sitelinks, callouts) are not scripted yet. Use the
  UI, or extend the script.
* To A/B test a bidding or keyword change, use the `google-ads-experiments`
  skill with type `SEARCH_CUSTOM` on the base campaign.
* New keywords show `UNDER_REVIEW` for a few hours, and Quality Score stays
  null until the keyword has had impressions.
