---
name: google-ads-rsa
description: >-
  Writes, lints, critiques, creates, and reviews responsive search ads (RSAs)
  for Google Search campaigns: drafts headlines and descriptions from the ad
  group's keywords and landing page, runs a generate-then-critique pass, lints
  limits and Ad Strength habits, and creates paused ads via a bundled
  OAuth-authenticated script. Use this skill whenever the user wants search ad
  copy, RSA headlines or descriptions, Ad Strength improvements, or to replace
  low-performing search ad assets.
---

# Google Ads Responsive Search Ads Skill

Each Search ad group needs at least one RSA. Google mixes up to 15 headlines
and 4 descriptions at serving time, so the goal is a varied set of assets that
each work alone. All writes go through `scripts/rsa.py`, authenticated by
`~/google-ads.yaml`. Campaign and ad group structure comes from the
`google-ads-search-campaigns` skill.

```bash
R=.agents/skills/google-ads-rsa/scripts/rsa.py
```

`$W` is the project's workspace for specs and media: a Cloud Storage path such as
`gs://my-bucket`, or a local folder such as `.`. The project's `AGENTS.md` says which.
The scripts read and write `gs://` paths directly; to save a command's output to
one from a shell, pipe it: `... | gcloud storage cp - $W/specs/example.json`.

Run the script directly (`$R ...`), not with `python3 $R`: its shebang runs
`uv`, which installs the `google-ads` dependency. Start with
`.agents/skills/google-ads-auth/scripts/setup_oauth.py --check`, which also
lists the accessible customer IDs; on `invalid_rapt` or `invalid_grant`,
follow the `google-ads-auth` skill.

## Workflow

### 1. Gather Inputs
* The ad group ID and its keywords:
  `search_campaign.py keywords --customer ID --ad-group AG_ID`.
* The landing page. Read the product page itself (price, shipping, materials,
  guarantees) so every claim in the copy is something the page backs up.
* Existing ads: `$R list --customer ID --ad-group AG_ID`. An ad group can have
  at most 3 enabled RSAs.

### 2. Generate
Draft 12 to 15 headlines (30 chars) and 4 descriptions (90 chars):

| Angle | Headlines |
|---|---|
| Keyword headlines, using the ad group's top keywords verbatim | 3 to 5 |
| Brand | 1 to 2 |
| Product benefits and features from the page | 3 to 4 |
| Offer, price, or shipping | 1 to 2 |
| Call to action | 1 to 2 |

Mix lengths: include some headlines of 20 characters or fewer. Descriptions
should expand on the headlines rather than repeat them, and at least one
should end with a call to action. Pin nothing by default. If the brand must
always show, pin 2 or 3 brand headlines to position 1, never just one.

### 3. Critique, Then Revise
Review the draft against this checklist before linting, rewriting anything
that fails:

1. **Accuracy.** Every claim (price, shipping speed, "organic", "made in USA",
   health or safety effects) is stated on the landing page. Health,
   supplement, and pet products must not make medical or therapeutic claims.
2. **Standalone sense.** Any headline still reads correctly next to any
   other one, in any order.
3. **No keyword stuffing.** Keywords read naturally, and no two headlines
   say the same thing in different words.
4. **Search intent.** A searcher typing the ad group's keywords would see
   their words and a reason to click.
5. **Policy style.** No all caps for emphasis, no `!` in headlines, no
   repeated punctuation, emoji, phone numbers, or URLs in the text.
6. **No unproven superlatives.** "Best", "#1", "top-rated", and similar
   comparative claims need third-party verification on the landing page,
   so leave them out otherwise.

### 4. Lint
Save the output of `$R spec-template` as `$W/specs/search/rsa.json`, fill in the ads, then:
```bash
$R lint --spec $W/specs/search/rsa.json --customer ID --brand "Brand Name"
```
* `errors` are hard limits Google will reject. `warnings` are what drags Ad
  Strength down: fewer than 10 headlines, near-duplicate assets, pins, and
  keywords that appear in no headline.
* With `--customer`, lint loads each ad group's live keywords and lists
  `keyword_coverage.missing`. Work the top missing keywords into headlines,
  but only where the page backs up what the keyword says. If a keyword
  implies a claim the page doesn't make ("organic", "handmade", "best"),
  leave it out of the copy and suggest removing the keyword with the
  `google-ads-search-campaigns` skill, or adding the claim to the page if
  it is true.
  Without `--customer`, set `keywords` on the ad in the spec for an offline
  check.
* Repeat steps 3 and 4 until there are no errors and every remaining warning
  is deliberate.

### 5. Validate, Then Create
```bash
$R create --customer ID --spec $W/specs/search/rsa.json --dry-run
$R create --customer ID --spec $W/specs/search/rsa.json
```
* `create` re-runs lint and refuses to send anything if lint finds errors.
  The dry run then has Google check text, policy, and URLs without creating
  anything. Policy errors print the policy name and the offending text.
* Show the user the final copy and confirm before the real run. Give the
  final URL on its own line, and label `path1`/`path2` as the display path:
  it only changes the URL shown in the ad, needn't exist as a page, and
  every click goes to the final URL. Don't write it as a link. Ads are
  created **PAUSED** unless the spec says `"status": "ENABLED"`.

### 6. Review and Iterate
* `$R list --customer ID --campaign ID` shows Ad Strength, `action_items`
  (Google's own suggestions), approval, and policy topics. Right after
  creation, Ad Strength shows `PENDING` and approval `UNKNOWN`, then
  `UNDER_REVIEW`, for a few hours. That is normal, not an error.
* After roughly two weeks of traffic,
  `$R performance --customer ID --ad AG_ID~AD_ID` labels each asset `BEST`,
  `GOOD`, or `LOW`. Ads can't be edited, so to replace `LOW` assets, create a
  new RSA with the improved set, then retire the old one with
  `$R set-status --customer ID --ad AG_ID~AD_ID --status PAUSED`. Use
  `--status REMOVED` only when the user asks for it.
* To test a new copy direction properly, run it through the
  `google-ads-experiments` skill instead of swapping ads in place.

## Notes
* Limits: headlines 3 to 15 at 30 chars, descriptions 2 to 4 at 90 chars,
  path1 and path2 at 15 chars each. Headlines pin to positions 1 to 3,
  descriptions to 1 or 2.
* Lint counts characters the simple way. Google counts some double-width
  characters as 2, and the dry run catches those.
