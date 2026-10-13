# ads-agent

An [ADK](https://adk.dev/) agent that runs every skill in `../.agents/skills/` (Google Ads Search, responsive search ads, Performance Max asset groups, experiments, campaign summaries, and the image, video, and audio creative skills) on Gemini through Vertex AI. It is the same skill set that Antigravity uses, behind ADK's web UI.

## How the skills map to ADK

The skills are loaded unchanged with ADK's `SkillToolset`. Their workstation-specific steps map to these tools:

| Skill step | Tool here |
|---|---|
| A shell command for a skill script (`$S create ...`) | `run_skill_script(skill, script, args)`, which runs the real script with the workspace as its working directory |
| `search_search`, `customers_list_accessible_customers` on `google-ads-mcp` | Native tools of the same name, using `~/google-ads.yaml` |
| `generate_content` on `geap-generate` | `generate_image`, which saves the file |
| `genmedia-veo`, `genmedia-omni`, `genmedia-avtool` | The same local MCP servers, over stdio |
| Writing specs, reading pages and landing pages | `write_file`, `read_file`, `list_files`, `load_web_page` |

ADK's built-in `run_skill_script` is turned off. It copies a script into a temp directory and runs it in-process, which breaks the workspace-relative paths and the `uv` shebangs the scripts depend on.

### Confirmation

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
uv run adk web          # web UI at http://127.0.0.1:8000, pick ads_agent
uv run adk run ads_agent  # terminal chat
```

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
- The model can't view images or video, so skills that inspect a frame or a storyboard report the file instead.
- ADK Skills and tool confirmation are both experimental in ADK.
