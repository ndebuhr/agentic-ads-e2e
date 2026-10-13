"""The google-ads-rsa skill's generate, critique, and lint steps as a fixed loop.

A writer drafts or revises the RSA spec, the real linter runs on it, and a
separate critic checks it against the skill's checklist. The loop repeats until
the critic passes a spec with no lint errors, or MAX_ROUNDS is reached. It
writes the spec file only; validating and creating the ads stays with the
calling agent, behind the dry run and the user's confirmation.
"""
import asyncio
import json

from google.adk import Agent
from google.adk.events import Event
from google.adk.skills import load_skill_from_dir
from google.adk.tools.load_web_page import load_web_page
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.workflow import Workflow, node
from pydantic import BaseModel, Field

from .config import SKILLS_DIR, model
from .google_ads import search_search
from .skill_scripts import run_skill_script, run_skill_script_tool
from .workspace import list_files, read_file, write_file

MAX_ROUNDS = 3
STATE_KEY = "rsa_copywriter"
RSA_SKILL = load_skill_from_dir(SKILLS_DIR / "google-ads-rsa")


class RsaCopyRequest(BaseModel):
    customer_id: str = Field(description="Google Ads customer ID, digits only.")
    brand: str = Field(description="Brand name, as it should appear in headlines.")
    brief: str = Field(description=(
        "Everything the writer needs: each ad group's ID, theme, and final URL, existing ads to "
        "replace or keep, and the user's requests about copy, offers, and claims."))
    spec_path: str = Field(default="media/search/rsa.json", description="Workspace path of the RSA spec to write.")


class Critique(BaseModel):
    passed: bool = Field(description="True only if every ad passes every checklist item and lint reports no errors.")
    issues: list[str] = Field(description="Each problem, naming the ad, the asset text, and the fix. Empty if passed.")


writer = Agent(
    name="rsa_writer",
    model=model(),
    description="Drafts and revises the RSA spec.",
    instruction=f"""\
You write responsive search ad copy by following steps 1, 2, and 4 of this
skill. Paths are workspace-relative; run its scripts with run_skill_script.

<skill name="google-ads-rsa">
{RSA_SKILL.instructions}
</skill>

The request names the ad groups, landing pages, brand, and the spec path.
Gather the inputs (keywords with the search_campaign.py keywords command, the
landing page with load_web_page), then write the complete spec to the spec
path with write_file. If the request includes a critique of an earlier
draft, read the current spec and fix every issue it lists. Do not run the
create command. Finish with a short note on what you wrote or changed.
""",
    tools=[
        run_skill_script_tool({"google-ads-rsa", "google-ads-search-campaigns"}),
        search_search, read_file, write_file, list_files, load_web_page, PreloadMemoryTool(),
    ],
)

critic = Agent(
    name="rsa_critic",
    model=model(),
    description="Checks the RSA spec against the skill's checklist.",
    output_schema=Critique,
    instruction=f"""\
You review responsive search ad copy. You did not write it; be strict.
Read the spec with read_file and every landing page it uses with
load_web_page, then check each ad against step 3 of this skill, item by item:

<skill name="google-ads-rsa">
{RSA_SKILL.instructions}
</skill>

The request includes the linter's report. Every lint error is an issue, and
so is any warning the copy could reasonably fix (low headline count,
near-duplicates, missing top keywords). Accuracy matters most: flag any
claim the landing page does not state.
""",
    tools=[read_file, load_web_page],
)


@node(name="rsa_prepare")
def prepare(ctx, node_input: RsaCopyRequest) -> str:
    request = RsaCopyRequest.model_validate(node_input)
    ctx.state[STATE_KEY] = {"request": request.model_dump(), "round": 1}
    return f"Write the RSA spec.\n\n{request.model_dump_json(indent=2)}"


@node(name="rsa_lint")
async def lint(ctx, node_input) -> str:
    request = RsaCopyRequest.model_validate(ctx.state[STATE_KEY]["request"])
    result = await asyncio.to_thread(run_skill_script, "google-ads-rsa", "rsa.py", [
        "lint", "--spec", request.spec_path, "--customer", request.customer_id, "--brand", request.brand])
    ctx.state[STATE_KEY] = {**ctx.state[STATE_KEY], "lint": result}
    return (f"Review the RSA spec at {request.spec_path}.\n\nBrief:\n{request.brief}\n\n"
            f"Linter report (exit code {result.get('exit_code')}):\n{result.get('stdout') or result.get('error')}\n{result.get('stderr', '')}")


@node(name="rsa_gate")
def gate(ctx, node_input) -> Event:
    critique = Critique.model_validate(node_input)
    loop = ctx.state[STATE_KEY]
    lint_ok = loop.get("lint", {}).get("exit_code") == 0
    done = (critique.passed and lint_ok) or loop["round"] >= MAX_ROUNDS
    if done:
        ctx.state[STATE_KEY] = {**loop, "critique": critique.model_dump()}
        return Event(route="done", output=None)
    ctx.state[STATE_KEY] = {**loop, "round": loop["round"] + 1}
    request = RsaCopyRequest.model_validate(loop["request"])
    issues = "\n".join(f"- {i}" for i in critique.issues) or "- Lint reported errors; fix them."
    return Event(route="revise", output=(
        f"Revise the RSA spec at {request.spec_path}. A reviewer found these issues:\n{issues}\n\n"
        f"Original request:\n{request.model_dump_json(indent=2)}"))


@node(name="rsa_finish")
def finish(ctx, node_input) -> dict:
    loop = ctx.state[STATE_KEY]
    critique = loop.get("critique", {})
    lint_report = loop.get("lint", {})
    try:
        report = json.loads(lint_report.get("stdout") or "{}")
    except json.JSONDecodeError:
        report = lint_report.get("stdout")
    return {
        "spec_path": loop["request"]["spec_path"],
        "rounds": loop["round"],
        "passed_review": bool(critique.get("passed")) and lint_report.get("exit_code") == 0,
        "open_issues": critique.get("issues", []),
        "lint": report,
    }


rsa_copywriter = Workflow(
    name="rsa_copywriter",
    description=(
        "Runs the google-ads-rsa skill's generate, critique, and lint steps (2 to 4) as a loop: a writer drafts the "
        f"spec, the linter checks it, and an independent critic reviews it, for up to {MAX_ROUNDS} rounds. Writes the "
        "spec file and returns the review result. Does not create ads."),
    input_schema=RsaCopyRequest,
    edges=[("START", prepare, writer, lint, critic, gate, {"revise": writer, "done": finish})],
)
