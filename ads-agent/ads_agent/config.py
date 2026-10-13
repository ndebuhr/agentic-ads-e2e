"""Settings from the environment (ADK loads ads-agent/.env before importing the agent)."""
import os
from pathlib import Path

SKILLS_DIR = Path(os.environ.get("ADS_AGENT_SKILLS_DIR", Path(__file__).resolve().parents[2] / ".agents" / "skills"))
WORKSPACE = Path(os.path.expanduser(os.environ.get("ADS_AGENT_WORKSPACE", "."))).resolve()
MODEL = os.environ.get("ADS_AGENT_MODEL", "gemini-3.8-flash")
GOOGLE_ADS_CONFIG = os.path.expanduser(os.environ.get("GOOGLE_ADS_CONFIGURATION_FILE_PATH", "~/google-ads.yaml"))
GENMEDIA_BIN_DIR = Path(os.path.expanduser(os.environ.get("GENMEDIA_BIN_DIR", "~/.local/bin")))
GENMEDIA_BUCKET = os.environ.get("GENMEDIA_BUCKET")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
