#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["google-ads>=32,<33"]
# ///
"""Google Ads experiments CLI (write path). Auth comes from ~/google-ads.yaml
(OAuth client id/secret/refresh token, created by the google-ads-auth skill).

  experiments.py list      --customer ID [--status ENABLED]
  experiments.py status    --customer ID --experiment EXP_ID
  experiments.py create    --customer ID --base-campaign CAMPAIGN_ID --name NAME
                           [--type SEARCH_CUSTOM] [--suffix "[exp]"] [--split 50]
                           [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--description TEXT]
  experiments.py rename-treatment --customer ID --experiment EXP_ID --name NAME
  experiments.py schedule  --customer ID --experiment EXP_ID [--no-wait]
  experiments.py errors    --customer ID --experiment EXP_ID
  experiments.py end       --customer ID --experiment EXP_ID
  experiments.py promote   --customer ID --experiment EXP_ID [--no-wait]
  experiments.py graduate  --customer ID --experiment EXP_ID --daily-budget 50.00

All mutating commands accept --dry-run (validate_only). Customer IDs may
contain dashes. Intra-campaign types (ADOPT_AI_MAX, ADOPT_BROAD_MATCH_KEYWORDS)
use the base campaign in both arms and cannot be graduated.
"""
import argparse, json, os, re, sys, time, uuid
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

SYSTEM_MANAGED = {"SEARCH_CUSTOM", "DISPLAY_CUSTOM", "HOTEL_CUSTOM", "YOUTUBE_CUSTOM", "PMAX_REPLACEMENT_SHOPPING"}
INTRA_CAMPAIGN = {"ADOPT_AI_MAX", "ADOPT_BROAD_MATCH_KEYWORDS", "PMAX_TEXT_CUSTOMIZATION_FINAL_URL_EXPANSION"}

def digits(s): return re.sub(r"\D", "", s or "")
def exp_rn(client, cust, exp_id): return client.get_service("ExperimentService").experiment_path(cust, exp_id)

def query(client, cust, gaql):
    return list(client.get_service("GoogleAdsService").search(customer_id=cust, query=gaql))

def req(client, type_name, **fields):
    """Build a request proto; flattened service kwargs don't accept validate_only."""
    r = client.get_type(type_name)
    for k, v in fields.items():
        if isinstance(v, list): getattr(r, k).extend(v)
        else: setattr(r, k, v)
    return r

def die_on_error(e: GoogleAdsException):
    for err in e.failure.errors:
        print(f"ERROR {err.error_code}: {err.message}", file=sys.stderr)
        for fp in err.location.field_path_elements:
            print(f"  at {fp.field_name}", file=sys.stderr)
    sys.exit(1)

# ---------- read ----------
def cmd_list(client, a):
    cond = f" WHERE experiment.status = '{a.status}'" if a.status else ""
    rows = query(client, a.customer, f"""
        SELECT experiment.experiment_id, experiment.name, experiment.type, experiment.status,
               experiment.start_date, experiment.end_date, experiment.suffix, experiment.promote_status
        FROM experiment{cond} ORDER BY experiment.start_date DESC""")
    print(json.dumps([{"id": r.experiment.experiment_id, "name": r.experiment.name, "type": r.experiment.type_.name,
                       "status": r.experiment.status.name, "start": r.experiment.start_date, "end": r.experiment.end_date,
                       "promote_status": r.experiment.promote_status.name} for r in rows], indent=2))

def cmd_status(client, a):
    # treatment field -> control field (control_* naming differs for conversion value)
    m = {"clicks": "control_clicks", "impressions": "control_impressions", "cost_micros": "control_cost_micros",
         "conversions": "control_conversions", "conversions_value": "control_conversion_value"}
    fields = ", ".join(f"metrics.{t}, metrics.{c}" for t, c in m.items()) + \
        ", metrics.clicks_p_value, metrics.clicks_point_estimate, metrics.clicks_margin_of_error" \
        ", metrics.conversions_absolute_change_p_value, metrics.conversions_absolute_change_point_estimate, metrics.conversions_absolute_change_margin_of_error" \
        ", metrics.cost_per_conversion_p_value, metrics.cost_per_conversion_change_point_estimate, metrics.cost_per_conversion_margin_of_error"
    rows = query(client, a.customer, f"""
        SELECT experiment.experiment_id, experiment.name, experiment.type, experiment.status, experiment.start_date,
               experiment.end_date, experiment.promote_status, {fields}
        FROM experiment WHERE experiment.experiment_id = {a.experiment}""")
    if not rows: sys.exit("experiment not found")
    r = rows[0]; mt = r.metrics
    arms = query(client, a.customer, f"""
        SELECT experiment_arm.name, experiment_arm.control, experiment_arm.traffic_split,
               experiment_arm.campaigns, experiment_arm.in_design_campaigns
        FROM experiment_arm WHERE experiment_arm.experiment = '{r.experiment.resource_name}'""")
    out = {
        "experiment": {"id": r.experiment.experiment_id, "name": r.experiment.name, "type": r.experiment.type_.name,
                        "status": r.experiment.status.name, "start": r.experiment.start_date, "end": r.experiment.end_date,
                        "promote_status": r.experiment.promote_status.name},
        "arms": [{"name": x.experiment_arm.name, "control": x.experiment_arm.control, "traffic_split": x.experiment_arm.traffic_split,
                  "campaigns": list(x.experiment_arm.campaigns), "in_design_campaigns": list(x.experiment_arm.in_design_campaigns)} for x in arms],
        "treatment": {t: getattr(mt, t) for t in m},
        "control": {t: getattr(mt, c) for t, c in m.items()},
        "significance": {
            "clicks": {"p_value": mt.clicks_p_value, "lift": mt.clicks_point_estimate, "moe": mt.clicks_margin_of_error},
            "conversions_abs_change": {"p_value": mt.conversions_absolute_change_p_value, "lift": mt.conversions_absolute_change_point_estimate, "moe": mt.conversions_absolute_change_margin_of_error},
            "cost_per_conversion": {"p_value": mt.cost_per_conversion_p_value, "lift": mt.cost_per_conversion_change_point_estimate, "moe": mt.cost_per_conversion_margin_of_error},
        },
    }
    print(json.dumps(out, indent=2, default=str))

# ---------- write ----------
def cmd_create(client, a):
    if a.type not in SYSTEM_MANAGED | INTRA_CAMPAIGN:
        sys.exit(f"unsupported type {a.type}; use one of {sorted(SYSTEM_MANAGED | INTRA_CAMPAIGN)}")
    svc = client.get_service("ExperimentService")
    op = client.get_type("ExperimentOperation"); e = op.create
    e.name = a.name; e.type_ = getattr(client.enums.ExperimentTypeEnum, a.type)
    e.status = client.enums.ExperimentStatusEnum.SETUP
    if a.suffix: e.suffix = a.suffix
    if a.description: e.description = a.description
    if a.start: e.start_date = a.start
    if a.end: e.end_date = a.end
    resp = svc.mutate_experiments(request=req(client, "MutateExperimentsRequest", customer_id=a.customer, operations=[op], validate_only=a.dry_run))
    if a.dry_run: print("dry-run: experiment valid"); return
    exp = resp.results[0].resource_name
    base = client.get_service("CampaignService").campaign_path(a.customer, digits(a.base_campaign))
    ops = []
    for control, name, split in ((True, "control", 100 - a.split), (False, "treatment", a.split)):
        o = client.get_type("ExperimentArmOperation"); arm = o.create
        arm.experiment = exp; arm.name = name; arm.control = control; arm.traffic_split = split
        if control or a.type in INTRA_CAMPAIGN: arm.campaigns.append(base)
        ops.append(o)
    req = client.get_type("MutateExperimentArmsRequest")
    req.customer_id = a.customer; req.operations = ops
    req.response_content_type = client.enums.ResponseContentTypeEnum.MUTABLE_RESOURCE
    arms = client.get_service("ExperimentArmService").mutate_experiment_arms(request=req)
    treatment = arms.results[1].experiment_arm
    out = {"experiment": exp, "experiment_id": exp.rsplit("/", 1)[1], "control_arm": arms.results[0].resource_name,
           "treatment_arm": treatment.resource_name, "in_design_campaigns": list(treatment.in_design_campaigns)}
    if a.type in SYSTEM_MANAGED:
        out["next"] = "Modify the in-design campaign (at least one change, e.g. rename-treatment), then schedule."
    else:
        out["next"] = "Intra-campaign: the feature is applied to the base campaign for the treatment split; schedule when ready."
    print(json.dumps(out, indent=2))

def _treatment_draft(client, a):
    rows = query(client, a.customer, f"""
        SELECT experiment_arm.in_design_campaigns, experiment_arm.campaigns FROM experiment_arm
        WHERE experiment_arm.experiment = '{exp_rn(client, a.customer, a.experiment)}' AND experiment_arm.control = FALSE""")
    for r in rows:
        if r.experiment_arm.in_design_campaigns: return r.experiment_arm.in_design_campaigns[0]
    sys.exit("no in-design campaign on the treatment arm (already scheduled, or intra-campaign type)")

def cmd_rename_treatment(client, a):
    from google.api_core import protobuf_helpers
    draft = _treatment_draft(client, a)
    op = client.get_type("CampaignOperation"); c = op.update
    c.resource_name = draft; c.name = a.name
    client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))
    client.get_service("CampaignService").mutate_campaigns(request=req(client, "MutateCampaignsRequest", customer_id=a.customer, operations=[op], validate_only=a.dry_run))
    print(json.dumps({"campaign": draft, "name": a.name, "dry_run": a.dry_run}))

def _wait(client, lro_name, label, timeout):
    ops = client.get_service("ExperimentService").transport.operations_client
    deadline = time.time() + timeout
    while time.time() < deadline:
        op = ops.get_operation(lro_name)
        if op.done:
            if op.HasField("error"): sys.exit(f"{label} failed: {op.error.message}")
            print(f"{label} complete"); return
        print(f"{label} running..."); time.sleep(10)
    sys.exit(f"{label} still running after {timeout}s; check later with: experiments.py errors")

def cmd_schedule(client, a):
    rn = exp_rn(client, a.customer, a.experiment)
    op = client.get_service("ExperimentService").schedule_experiment(request=req(client, "ScheduleExperimentRequest", resource_name=rn, validate_only=a.dry_run))
    if a.dry_run: print("dry-run: schedule valid"); return
    print(json.dumps({"experiment": rn, "operation": op.operation.name}))
    if not a.no_wait: _wait(client, op.operation.name, "schedule", a.timeout)

def cmd_errors(client, a):
    rn = exp_rn(client, a.customer, a.experiment)
    errs = client.get_service("ExperimentService").list_experiment_async_errors(resource_name=rn)
    n = 0
    for st in errs:
        n += 1; print(json.dumps({"code": st.code, "message": st.message}))
    print(f"{n} async error(s)")

def cmd_end(client, a):
    rn = exp_rn(client, a.customer, a.experiment)
    client.get_service("ExperimentService").end_experiment(request=req(client, "EndExperimentRequest", experiment=rn, validate_only=a.dry_run))
    print(json.dumps({"experiment": rn, "ended": not a.dry_run, "dry_run": a.dry_run}))

def cmd_promote(client, a):
    rn = exp_rn(client, a.customer, a.experiment)
    op = client.get_service("ExperimentService").promote_experiment(request=req(client, "PromoteExperimentRequest", resource_name=rn, validate_only=a.dry_run))
    if a.dry_run: print("dry-run: promote valid"); return
    print(json.dumps({"experiment": rn, "operation": op.operation.name}))
    if not a.no_wait: _wait(client, op.operation.name, "promote", a.timeout)

def cmd_graduate(client, a):
    rn = exp_rn(client, a.customer, a.experiment)
    rows = query(client, a.customer, f"""
        SELECT experiment_arm.campaigns FROM experiment_arm
        WHERE experiment_arm.experiment = '{rn}' AND experiment_arm.control = FALSE""")
    treat = next((r.experiment_arm.campaigns[0] for r in rows if r.experiment_arm.campaigns), None)
    if not treat: sys.exit("no treatment campaign found (unscheduled, or intra-campaign type which cannot graduate)")
    bop = client.get_type("CampaignBudgetOperation"); b = bop.create
    b.name = f"{a.budget_name or 'Graduated experiment budget'} {uuid.uuid4().hex[:8]}"
    b.amount_micros = int(round(a.daily_budget * 1_000_000))
    b.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    if a.dry_run:
        client.get_service("CampaignBudgetService").mutate_campaign_budgets(request=req(client, "MutateCampaignBudgetsRequest", customer_id=a.customer, operations=[bop], validate_only=True))
        print("dry-run: budget valid; graduate not validated (needs a real budget)"); return
    budget = client.get_service("CampaignBudgetService").mutate_campaign_budgets(customer_id=a.customer, operations=[bop]).results[0].resource_name
    mapping = client.get_type("CampaignBudgetMapping"); mapping.experiment_campaign = treat; mapping.campaign_budget = budget
    client.get_service("ExperimentService").graduate_experiment(experiment=rn, campaign_budget_mappings=[mapping])
    print(json.dumps({"experiment": rn, "graduated_campaign": treat, "budget": budget}))

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to google-ads.yaml (default ~/google-ads.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    def common(sp, exp=True, mut=False):
        sp.add_argument("--customer", required=True)
        if exp: sp.add_argument("--experiment", required=True, help="experiment ID (digits)")
        if mut: sp.add_argument("--dry-run", action="store_true", help="validate_only")
    s = sub.add_parser("list"); common(s, exp=False); s.add_argument("--status")
    s = sub.add_parser("status"); common(s)
    s = sub.add_parser("create"); common(s, exp=False, mut=True)
    s.add_argument("--base-campaign", required=True); s.add_argument("--name", required=True)
    s.add_argument("--type", default="SEARCH_CUSTOM"); s.add_argument("--suffix", default="[experiment]")
    s.add_argument("--split", type=int, default=50, help="treatment traffic %%"); s.add_argument("--start"); s.add_argument("--end")
    s.add_argument("--description")
    s = sub.add_parser("rename-treatment"); common(s, mut=True); s.add_argument("--name", required=True)
    for name in ("schedule", "promote"):
        s = sub.add_parser(name); common(s, mut=True); s.add_argument("--no-wait", action="store_true"); s.add_argument("--timeout", type=int, default=600)
    s = sub.add_parser("errors"); common(s)
    s = sub.add_parser("end"); common(s, mut=True)
    s = sub.add_parser("graduate"); common(s, mut=True); s.add_argument("--daily-budget", type=float, required=True, help="new budget for the graduated campaign, in account currency")
    s.add_argument("--budget-name")
    a = p.parse_args()
    a.customer = digits(a.customer)
    if getattr(a, "experiment", None): a.experiment = digits(a.experiment)
    client = load_client(a.config)
    try:
        globals()["cmd_" + a.cmd.replace("-", "_")](client, a)
    except GoogleAdsException as e:
        die_on_error(e)

if __name__ == "__main__":
    main()
