"""Hard rules for Google Ads writes, enforced in code for every agent in the app.

The instructions already ask for a dry run before each write and forbid
enabling anything, and the user confirms each write. This plugin makes both
rules hold even when the model and a hurried confirmation click both slip:

- Nothing is enabled: `set-status --status ENABLED`, and a create spec that
  sets any "status" to "ENABLED", are refused outright. The user enables
  campaigns and ads in Google Ads, or runs the script themselves.
- No write without a matching dry run: a real write runs only after the same
  command, with the same spec file contents, passed with --dry-run in this
  session. Each dry run allows one real run.

It runs before the confirmation prompt, so a refused call never asks.
"""
import hashlib
import json
from typing import Any

from google.adk.plugins import BasePlugin
from google.adk.tools import BaseTool, ToolContext

from .config import WORKSPACE
from .skill_scripts import ads_write_command

DRY_RUNS_KEY = "guardrails:dry_runs"
TOOL = "run_skill_script"


def _write_command(args: dict) -> tuple[str, list[str]] | None:
    """Returns (script key, argv) for a Google Ads write command, else None."""
    argv = [str(a) for a in args.get("args") or []]
    key = ads_write_command(str(args.get("skill")), str(args.get("script")), argv)
    return (key, argv) if key else None


def _flag(argv: list[str], name: str) -> str | None:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _spec_bytes(argv: list[str]) -> bytes | None:
    spec = _flag(argv, "--spec")
    if spec is None:
        return None
    try:
        return (WORKSPACE / spec).read_bytes()
    except OSError:
        return None


def _enables(value: Any) -> bool:
    if isinstance(value, dict):
        return any((k == "status" and v == "ENABLED") or _enables(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_enables(v) for v in value)
    return False


def _fingerprint(key: str, argv: list[str]) -> str:
    spec = _spec_bytes(argv)
    payload = json.dumps([key, [a for a in argv if a != "--dry-run"], hashlib.sha256(spec).hexdigest() if spec else None])
    return hashlib.sha256(payload.encode()).hexdigest()


class AdsWriteGuardrails(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="ads_write_guardrails")

    async def before_tool_callback(self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext) -> dict | None:
        if tool.name != TOOL or not (cmd := _write_command(tool_args)):
            return None
        key, argv = cmd
        if argv[0] == "set-status" and _flag(argv, "--status") == "ENABLED":
            return {"error": "Refused: this agent never enables campaigns, ad groups, or ads. "
                             "Tell the user to enable it in Google Ads, or to run the command themselves."}
        spec = _spec_bytes(argv)
        if spec is not None:
            try:
                if _enables(json.loads(spec)):
                    return {"error": "Refused: the spec sets a status to ENABLED. Set it to PAUSED; "
                                     "the user enables it in Google Ads after reviewing it."}
            except json.JSONDecodeError:
                pass  # The script reports the bad spec itself.
        if "--dry-run" in argv:
            return None
        if _fingerprint(key, argv) not in tool_context.state.get(DRY_RUNS_KEY, []):
            return {"error": "Refused: no successful --dry-run of this exact command (and spec file contents) "
                             "in this session. Run it with --dry-run first, report the result, then retry."}
        return None

    async def after_tool_callback(self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext, result: dict) -> dict | None:
        if tool.name != TOOL or not (cmd := _write_command(tool_args)) or not isinstance(result, dict) or "exit_code" not in result:
            return None
        key, argv = cmd
        fp = _fingerprint(key, argv)
        dry_runs = list(tool_context.state.get(DRY_RUNS_KEY, []))
        if "--dry-run" in argv:
            if result["exit_code"] == 0 and fp not in dry_runs:
                tool_context.state[DRY_RUNS_KEY] = [*dry_runs, fp]
        elif fp in dry_runs:
            # One real run per dry run, so a repeated create needs a fresh check.
            dry_runs.remove(fp)
            tool_context.state[DRY_RUNS_KEY] = dry_runs
        return None
