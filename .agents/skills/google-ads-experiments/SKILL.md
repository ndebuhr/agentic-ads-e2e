---
name: google-ads-experiments
description: >-
  Lists, analyzes, creates, schedules, and concludes Google Ads campaign
  experiments (A/B tests): reads go through the google-ads-mcp server, writes
  through a bundled OAuth-authenticated script. Use this skill whenever the
  user asks about experiments, trials, A/B tests, treatment vs control
  performance, lift, significance, or wants to promote, graduate, or end one.
---

# Google Ads Experiments Skill

Experiments split a campaign's traffic between a control arm and one or more
treatment arms. The `google-ads-mcp` server is read-only (GAQL search), so
analysis uses it and every mutation goes through
`scripts/experiments.py`, which authenticates with the OAuth client in
`~/google-ads.yaml` (no developer token; access is project-based).

## Workflow

### 1. Identify Customer ID
Same as the campaign summary skill: normalize to digits, or call
`customers_list_accessible_customers` on `google-ads-mcp` and ask if several.

### 2. List Experiments (read)
`search_search` on `google-ads-mcp`, resource `experiment`, fields
`experiment.experiment_id`, `experiment.name`, `experiment.type`,
`experiment.status`, `experiment.start_date`, `experiment.end_date`,
`experiment.suffix`, `experiment.promote_status`. Filter with
`experiment.status = 'ENABLED'` for running tests. Then resource
`experiment_arm` with `experiment_arm.name`, `experiment_arm.control`,
`experiment_arm.traffic_split`, `experiment_arm.campaigns`,
`experiment_arm.in_design_campaigns`, condition
`experiment_arm.experiment = '<experiment resource_name>'`.

* Types: `SEARCH_CUSTOM`, `DISPLAY_CUSTOM`, `YOUTUBE_CUSTOM`, `HOTEL_CUSTOM`,
  `PMAX_REPLACEMENT_SHOPPING` (separate treatment campaign);
  `ADOPT_AI_MAX`, `ADOPT_BROAD_MATCH_KEYWORDS`,
  `PMAX_TEXT_CUSTOMIZATION_FINAL_URL_EXPANSION` (intra-campaign, one campaign).
* Statuses: `SETUP` → `INITIATED` (scheduled) → `ENABLED` (serving) →
  `HALTED`, `PROMOTED`, `GRADUATED`, or `REMOVED`.

### 3. Analyze Results (read)
Query the `experiment` resource for one experiment. Treatment metrics are
plain (`metrics.clicks`, `metrics.conversions`, `metrics.cost_micros`,
`metrics.conversions_value`); control metrics are prefixed
(`metrics.control_clicks`, `metrics.control_conversions`,
`metrics.control_cost_micros`, `metrics.control_conversion_value`). Significance fields come in triples of
`*_p_value`, `*_point_estimate` (lift, as a fraction), `*_margin_of_error`:
`clicks_*`, `impressions_*`, `cost_micros_*`, `conversions_absolute_change_*`,
`cost_per_conversion_*`, `conversion_value_per_cost_*`.

Decision rule (matches Google's reference example, p ≤ 0.05):
* Conversions lift minus margin > 0 → recommend **promote**.
* Conversions lift plus margin < 0 → recommend **end**.
* Only clicks significantly up → recommend **graduate** for further study
  (not available for intra-campaign types).
* Otherwise → keep running; suggest at least 4 weeks and a 50/50 split.

Present two tables: Experiment (name, type, status, dates, split) and
Results (metric, control, treatment, lift %, p-value, verdict).

### 4. Create and Launch (write)
```bash
S=.agents/skills/google-ads-experiments/scripts
$S/experiments.py create --customer ID --base-campaign CAMPAIGN_ID \
  --name "Headline test" --type SEARCH_CUSTOM --split 50 --start 2026-10-01 --end 2026-10-29
$S/experiments.py rename-treatment --customer ID --experiment EXP_ID --name "Headline test [treatment]"
$S/experiments.py schedule --customer ID --experiment EXP_ID
```
* `create` makes the experiment plus a control arm (base campaign) and a
  treatment arm, and prints the treatment's in-design campaign.
* System-managed types require at least one change to the in-design campaign
  before scheduling. `rename-treatment` is the minimal change; substantive
  edits (bids, ads, keywords) go through the normal campaign tools on that
  in-design campaign resource.
* `schedule` waits on the long-running operation; on failure run
  `errors` to list async errors.
* Every write accepts `--dry-run` (validate only). Confirm with the user
  before any non-dry-run `create`, `schedule`, `end`, `promote`, or `graduate`.

### 5. Conclude (write)
* `end`: stop the treatment, keep the base campaign as is.
* `promote`: copy treatment changes into the base campaign (async; waits).
  Not allowed for `PMAX_REPLACEMENT_SHOPPING`.
* `graduate --daily-budget 50`: make the treatment campaign standalone with a
  new budget. Not allowed for intra-campaign types.
* `status` prints the same metrics as step 3 as JSON when the MCP is not
  available.

## Setup
Writes need `~/google-ads.yaml`. If it is missing, follow the
`google-ads-auth` skill once; its `scripts/setup_oauth.py --check` confirms
the token works.
