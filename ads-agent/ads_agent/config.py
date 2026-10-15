"""Settings from the environment (ADK loads ads-agent/.env before importing the agent)."""
import os
import shutil
from pathlib import Path

from google.adk.models.google_llm import Gemini
from google.genai import types

PROJECT_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = Path(os.environ.get("ADS_AGENT_SKILLS_DIR", PROJECT_DIR / ".agents" / "skills"))
# The skills' paths (.agents/skills/...) are relative to the workspace; specs and media live in STORAGE.
WORKSPACE = Path(os.path.expanduser(os.environ.get("ADS_AGENT_WORKSPACE", PROJECT_DIR))).resolve()
# Cloud Storage location for specs, media, brand assets, and uploads ($W in the skills), e.g. gs://bucket.
# Unset to keep everything in the local workspace.
STORAGE = (os.environ.get("ADS_AGENT_STORAGE") or "").rstrip("/") or None
MODEL = os.environ.get("ADS_AGENT_MODEL", "gemini-3.8-flash")
GOOGLE_ADS_CONFIG = os.path.expanduser(os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE_PATH", "~/google-ads.yaml"))
_veo = shutil.which("mcp-veo-go")
GENMEDIA_BIN_DIR = Path(os.path.expanduser(os.environ.get("GENMEDIA_BIN_DIR") or (Path(_veo).parent if _veo else "~/.local/bin")))
GENMEDIA_BUCKET = os.environ.get("GENMEDIA_BUCKET")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
# projects/PROJECT/locations/LOCATION/templates/TEMPLATE; unset turns Model Armor screening off.
MODEL_ARMOR_TEMPLATE = os.environ.get("ADS_AGENT_MODEL_ARMOR_TEMPLATE")


def model() -> Gemini:
    # Vertex returns 429 when shared capacity for a model is briefly exhausted; back off and retry.
    return Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=6, initial_delay=2, max_delay=60, exp_base=2))


if google_ads_yaml := os.environ.get("GOOGLE_ADS_YAML"):
    # A deployment gets google-ads.yaml from Secret Manager as this variable; the
    # read tools and the skill scripts all read ~/google-ads.yaml.
    path = Path.home() / "google-ads.yaml"
    path.write_text(google_ads_yaml)
    path.chmod(0o600)
