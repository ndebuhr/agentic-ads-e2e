# ads-agent

An [ADK](https://adk.dev/) agent that runs every skill in `../.agents/skills/` (Google Ads Search, responsive search ads, Performance Max asset groups, experiments, campaign summaries, and the image, video, and audio creative skills) on Gemini through Vertex AI. It is the same skill set that Antigravity uses, behind ADK's web UI.

## How it's organized

A coordinator agent hands each request to one of two specialists, each holding only its own skills and tools:

- `ads_ops`: the `google-ads-*` skills.
- `creative`: the image, video, and audio skills.

`ads_agent/agent.py` wraps them in an ADK `App`, which adds context caching (the instructions, loaded skills, and tool declarations repeat on every call), compaction of long sessions into a summary that keeps IDs, paths, and decisions, and the plugins below.

## How the skills map to ADK

The skills are loaded unchanged with ADK's `SkillToolset`. Their workstation-specific steps map to these tools:

| Skill step | Tool here |
|---|---|
| A shell command for a skill script (`$S create ...`) | `run_skill_script(skill, script, args)`, which runs the real script with the workspace as its working directory |
| `search_search`, `customers_list_accessible_customers` on `google-ads-mcp` | Native tools of the same name, using `~/google-ads.yaml` |
| `generate_content` on `geap-generate` | `generate_image`, which saves the file and shares it in the chat |
| `genmedia-veo`, `genmedia-omni`, `genmedia-avtool` | The same local MCP servers, over stdio |
| `view_file` on an image, video, audio clip, or PDF | `view_file`, which shows the file to the model (up to 15 MB; local or `gs://`) |
| Writing specs, reading pages and landing pages | `write_file`, `read_file`, `list_files`, `load_web_page` |
| google-ads-rsa steps 2 to 4 (generate, critique, lint) | `rsa_copywriter`, a workflow described below |

ADK's built-in `run_skill_script` is turned off. It copies a script into a temp directory and runs it in-process, which breaks the workspace-relative paths and the `uv` shebangs the scripts depend on.

### RSA copywriting loop

`rsa_copywriter` (`ads_agent/rsa_workflow.py`) runs the RSA skill's draft and review as an ADK `Workflow` graph instead of leaving the loop to the model: a writer drafts the spec, the real `rsa.py lint` checks it, and a separate critic reviews it against the skill's checklist. It repeats until the critic passes a spec with no lint errors, for up to 3 rounds, then returns the spec path, open issues, and the lint report. It never creates ads; `ads_ops` does that with a dry run and your confirmation.

### Files in the chat

- `share_file` puts a workspace file in the chat's artifacts panel, where you can preview and download it. Generated images are shared automatically.
- Files you upload in the chat are saved as artifacts. The agent can look at them, and `save_upload` copies one into the workspace, for example into `brand_assets/`.
- Media from `view_file` is sent to the model once; later requests keep only the file path, so viewing a file doesn't make every following call bigger.

### Memory

The agent saves lasting facts you state or approve (brand facts, approved URLs, standing rules, decisions and their reasons) with `remember`, and adds the ones that match each request to its context. It saves only these explicit facts, not whole conversations or account data. Memories last only until the server stops unless you pass a memory service (see Run).

### Guardrails and confirmation

`ads_agent/guardrails.py` enforces two rules in code for every agent, before any confirmation prompt:

- Nothing gets enabled. `set-status --status ENABLED`, and any create spec that sets a status to `ENABLED`, are refused. Enable campaigns and ads yourself in Google Ads.
- No write without a matching dry run. A real write runs only after the same command, with the same spec file contents, passed with `--dry-run` in the same session. Each dry run allows one real run.

The web UI asks before any of these run:

- Google Ads writes: `create`, `set-status`, `add-keywords`, `add-negatives`, and the experiment lifecycle commands. A `--dry-run` of any of them runs without asking.
- Paid generation: Veo and Omni MCP calls, `generate_image`, `veo_extend_rest.py`, and `mcp_call.py`.
- Any script not classified in `ads_agent/skill_scripts.py`.

Setup commands that need a browser or install software (`setup_oauth.py` without `--check`, `setup.sh`) are refused, and the agent tells you the command to run yourself.

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/), the `gcloud` CLI, and a Google Cloud project with Vertex AI enabled.

1. Sign in for Vertex AI (Gemini, image generation, genmedia):
   ```bash
   gcloud auth application-default login
   ```
2. Sign in for Google Ads (writes `~/google-ads.yaml`):
   ```bash
   ../.agents/skills/google-ads-auth/scripts/setup_oauth.py
   ```
3. Configure the agent:
   ```bash
   cp .env.example .env   # set GOOGLE_CLOUD_PROJECT and ADS_AGENT_WORKSPACE
   uv sync
   ```
   `ADS_AGENT_WORKSPACE` is the directory the skills read and write (`media/`, `brand_assets/`, specs), usually the repo that holds this one as a submodule.
4. Optional: install the genmedia MCP servers with `../.agents/skills/genmedia-video-editing/scripts/setup.sh` and set `GENMEDIA_BUCKET`. Without it, the agent runs without the video tools.

## Run

```bash
uv run adk web --memory_service_uri "sqlite:///ads_agent/.adk/memory.db"   # web UI at http://127.0.0.1:8000, pick ads_agent
uv run adk run ads_agent  # terminal chat
```

`--memory_service_uri` keeps memories across restarts in a local SQLite file, which is git-ignored like the rest of `.adk/`. Leave it off for memories that last until the server stops, or use `agentengine://AGENT_ENGINE_ID` for Vertex AI Memory Bank (this needs an Agent Engine instance in your project).

On a cloud IDE or workstation that forwards the port to another hostname, the UI's scripts fail with 403 because ADK only allows localhost origins by default. Allow the forwarded origin, keeping the server bound to localhost:

```bash
uv run adk web --allow_origins "https://8000-your-workstation.example.dev"
uv run adk web --allow_origins "regex:^https://8000-.*\.cloudworkstations\.dev$"
```

Type into the chat box. The microphone and camera buttons start a live (streaming audio) session, which only works with Gemini Live models.

The default model is `gemini-3.8-flash` (set `ADS_AGENT_MODEL` to change it). Vertex has no `-latest` aliases. When Vertex returns 429 for a busy model, the agent backs off and retries up to six times, so a reply can take a few minutes.

If `gcloud auth application-default login` warns that no quota project is set, run `gcloud auth application-default set-quota-project YOUR_PROJECT`; Vertex rejects ADC calls without one.

Both sign-ins can expire under Google Workspace session control (`invalid_rapt` or "Reauthentication is needed"). Repeat steps 1 or 2 when that happens.

## Limits

- Runs locally, as you, with your Google Ads and Google Cloud credentials. A deployed version needs a service account or per-user OAuth instead of `~/google-ads.yaml`.
- `view_file` takes files up to 15 MB. For larger images or long videos, view a resized copy, a storyboard, or extracted frames.
- Context caching starts on a session's second turn, once the repeated prefix reaches the model's minimum (4,096 tokens for Gemini 3).
- ADK Skills, tool confirmation, compaction, and `Workflow` are experimental in ADK.
