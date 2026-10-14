"""Ads agent: the .agents/skills Google Ads and ad creative skills, run by ADK on Gemini.

A coordinator hands each request to one of two specialists, each holding only
its own skills and tools: ads_ops (the google-ads-* skills) and creative (the
image, video, and audio skills). The App adds context caching, compaction of
long sessions, the write guardrails, Model Armor screening (when configured),
and upload handling for every agent.
"""
from google.adk import Agent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.plugins.save_files_as_artifacts_plugin import SaveFilesAsArtifactsPlugin
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
from google.adk.tools.load_artifacts_tool import load_artifacts_tool
from google.adk.tools.load_web_page import load_web_page
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

from .config import MODEL_ARMOR_TEMPLATE, SKILLS_DIR, WORKSPACE, model
from .genmedia import genmedia_toolsets
from .google_ads import customers_list_accessible_customers, search_search
from .guardrails import AdsWriteGuardrails
from .memory import remember
from .model_armor import model_armor_plugins
from .rsa_workflow import rsa_copywriter
from .skill_scripts import run_skill_script_tool
from .workspace import (DropOldToolMedia, generate_image_tool, list_files, read_file, save_upload, share_file,
                        view_file, write_file)

ADS_SKILL_PREFIX = "google-ads-"

COMMON = f"""\
The skills were written for workstation agents like Antigravity.
Translate their instructions to your tools:
- A shell command running a skill script (`$S create ...`, `$R lint ...`, or a
  path under `.agents/skills/<skill>/scripts/`) -> `run_skill_script` with the
  skill name, the script file name, and the arguments as a list. Shell
  redirects like `> media/search/campaign.json` -> run without the redirect,
  then `write_file` with the output.
- Creating or editing a file -> `write_file`; reading one -> `read_file` or
  `list_files`; reading a landing page -> `load_web_page`.
- `view_file` on an image, video, audio clip, or PDF -> `view_file`, which
  shows it to you. Look at a file before describing or approving it.
- A command the skill says the user must run themselves (OAuth consent, setup
  scripts) -> tell the user the exact command and wait.
- A file the user uploads shows as [Uploaded Artifact: "name"]: look at it
  with `load_artifacts`, and keep it with `save_upload`.

Memory: facts from earlier sessions that match the request are added to your
context; follow them. When the user states or approves a lasting fact (brand
facts, approved URLs, standing rules, a decision and its reason), save it with
`remember`, and say that you did.

Rules:
- Make no claim in ad copy or creative that the landing page does not back up.
- Paths are relative to the workspace, {WORKSPACE}.
- When the request belongs to the other specialist, transfer to it.
"""

ADS_OPS = f"""\
You build and maintain Google Ads campaigns for a small business by following
the loaded skills. Load the skill that matches the request before acting, and
follow its workflow.

{COMMON}
- `call_mcp_tool` on `google-ads-mcp` -> call the tool of that name directly
  (`search_search`, `customers_list_accessible_customers`).
- Steps 2 to 4 of the google-ads-rsa skill (generate, critique, lint) ->
  `rsa_copywriter`, with a brief naming each ad group's ID, theme, and final
  URL and everything the user asked for. It writes the spec and returns the
  review result; show the user the copy and any open issues, then continue
  with step 5 yourself.
- Every write runs with --dry-run first, and the real run must repeat the
  same command and spec. Report the dry run's warnings, show the user the
  plan, and get their approval before the real run; they also confirm each
  write.
- Campaigns and ads are created paused, and you can't enable them: tell the
  user to enable them in Google Ads when they're ready.
"""

CREATIVE = f"""\
You produce ad creative (images, video, voiceover, music, end cards) by
following the loaded skills. Load the skill that matches the request before
acting, and follow its workflow.

{COMMON}
- `generate_content` on `geap-generate` -> `generate_image`, which saves the
  file and shares it in the chat.
- genmedia-veo, genmedia-omni, and genmedia-avtool tools -> call them directly
  by name, if present.
- Each finished image, video, or audio file -> `share_file`, so the user can
  preview and download it in the chat.
- Paid generation (images, Veo, Omni, ElevenLabs) asks the user to confirm
  each call; plan the prompts first so few calls are needed.
"""

COORDINATOR = """\
You coordinate two specialists for a small business's advertising:
- ads_ops: Google Ads campaigns, ad groups, keywords, search ads, Performance
  Max asset groups, experiments, and performance summaries.
- creative: ad images, video, voiceover and music, end cards, and video QA.
Transfer each request to the specialist it belongs to. Answer directly only
for greetings, questions about what you can do, or saving a lasting fact the
user gives you with `remember`.
"""

SUMMARY_PROMPT = """\
Summarize this conversation between a user and an advertising agent so the
agent can continue it. It may start from an earlier summary. Keep, exactly:
the user's open requests and approvals; every Google Ads customer, campaign,
ad group, ad, asset, and experiment ID with its name and status; spec and
media file paths; decisions and their reasons; and dry runs passed or
writes made. Drop raw query rows and tool output that has been acted on.
List the tools used.

{conversation_history}"""

skills = [load_skill_from_dir(d) for d in sorted(SKILLS_DIR.iterdir()) if (d / "SKILL.md").is_file()]
ads_skills = [s for s in skills if s.name.startswith(ADS_SKILL_PREFIX)]
creative_skills = [s for s in skills if not s.name.startswith(ADS_SKILL_PREFIX)]


def _skill_tools(group: list) -> list:
    return [
        skill_toolset.SkillToolset(
            skills=group,
            # Scripts run through run_skill_script_tool instead, in the workspace.
            tool_filter=["list_skills", "search_skills", "load_skill", "unload_skill", "load_skill_resource"],
        ),
        run_skill_script_tool({s.name for s in group}),
    ]


FILE_TOOLS = [list_files, read_file, write_file, view_file, share_file, save_upload, load_artifacts_tool, load_web_page]
MEMORY_TOOLS = [PreloadMemoryTool(), remember]

ads_ops = Agent(
    model=model(),
    name="ads_ops",
    description="Builds and maintains Google Ads campaigns: Search, RSAs, Performance Max asset groups, experiments, and summaries.",
    instruction=ADS_OPS,
    tools=[*_skill_tools(ads_skills), customers_list_accessible_customers, search_search, rsa_copywriter,
           *FILE_TOOLS, *MEMORY_TOOLS],
)

creative = Agent(
    model=model(),
    name="creative",
    description="Produces ad creative: images, video, voiceover, music, end cards, and video QA.",
    instruction=CREATIVE,
    tools=[*_skill_tools(creative_skills), generate_image_tool, *genmedia_toolsets(), *FILE_TOOLS, *MEMORY_TOOLS],
)

root_agent = Agent(
    model=model(),
    name="ads_agent",
    description="Builds and maintains Google Ads campaigns and ad creative from the agent skills.",
    instruction=COORDINATOR,
    tools=MEMORY_TOOLS,
    sub_agents=[ads_ops, creative],
)

app = App(
    name="ads_agent",
    root_agent=root_agent,
    plugins=[AdsWriteGuardrails(), *model_armor_plugins(MODEL_ARMOR_TEMPLATE), SaveFilesAsArtifactsPlugin(), DropOldToolMedia()],
    # The instruction, loaded skills, and tool declarations repeat on every call; cache them.
    context_cache_config=ContextCacheConfig(ttl_seconds=1800, cache_intervals=10),
    # Query results make long sessions large; summarize older turns past this size.
    events_compaction_config=EventsCompactionConfig(
        token_threshold=200_000, event_retention_size=20,
        summarizer=LlmEventSummarizer(llm=model(), prompt_template=SUMMARY_PROMPT)),
)
