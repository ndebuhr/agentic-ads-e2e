"""Ads agent: the .agents/skills Google Ads and ad creative skills, run by ADK on Gemini."""
from google.adk import Agent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
from google.adk.models.google_llm import Gemini
from google.adk.tools.load_web_page import load_web_page
from google.genai import types

from .config import MODEL, SKILLS_DIR, WORKSPACE
from .genmedia import genmedia_toolsets
from .google_ads import customers_list_accessible_customers, search_search
from .skill_scripts import run_skill_script_tool
from .workspace import generate_image_tool, list_files, read_file, write_file

INSTRUCTION = f"""\
You help a small business run Google Ads and produce ad creative, by following
the loaded skills. Load the skill that matches the request before acting, and
follow its workflow.

The skills were written for workstation agents like Antigravity.
Translate their instructions to your tools:
- A shell command running a skill script (`$S create ...`, `$R lint ...`, or a
  path under `.agents/skills/<skill>/scripts/`) -> `run_skill_script` with the
  skill name, the script file name, and the arguments as a list. Shell
  redirects like `> media/search/campaign.json` -> run without the redirect,
  then `write_file` with the output.
- `call_mcp_tool` on `google-ads-mcp` -> call the tool of that name directly
  (`search_search`, `customers_list_accessible_customers`).
- `generate_content` on `geap-generate` -> `generate_image`, which also saves
  the file.
- genmedia-veo, genmedia-omni, and genmedia-avtool tools -> call them directly
  by name, if present.
- Creating or editing a file -> `write_file`; reading one -> `read_file` or
  `list_files`; reading a landing page -> `load_web_page`.
- A command the skill says the user must run themselves (OAuth consent, setup
  scripts) -> tell the user the exact command and wait.
- `view_file` on images or video is not available; say so instead of guessing
  what a file looks like.

Rules:
- Run every write with --dry-run first and report its warnings. Show the user
  the plan and get their approval before the real run; the user will also be
  asked to confirm each write.
- Campaigns and ads are created paused. Never enable one unless the user asks
  for exactly that in this conversation.
- Make no claim in ad copy that the landing page does not back up.
- Paths are relative to the workspace, {WORKSPACE}.
"""

skills = [load_skill_from_dir(d) for d in sorted(SKILLS_DIR.iterdir()) if (d / "SKILL.md").is_file()]

root_agent = Agent(
    # Vertex returns 429 when shared capacity for a model is briefly exhausted; back off and retry.
    model=Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=6, initial_delay=2, max_delay=60, exp_base=2)),
    name="ads_agent",
    description="Builds and maintains Google Ads campaigns and ad creative from the agent skills.",
    instruction=INSTRUCTION,
    tools=[
        skill_toolset.SkillToolset(
            skills=skills,
            # Scripts run through run_skill_script_tool instead, in the workspace.
            tool_filter=["list_skills", "search_skills", "load_skill", "unload_skill", "load_skill_resource"],
        ),
        run_skill_script_tool,
        customers_list_accessible_customers,
        search_search,
        list_files,
        read_file,
        write_file,
        load_web_page,
        generate_image_tool,
        *genmedia_toolsets(),
    ],
)
