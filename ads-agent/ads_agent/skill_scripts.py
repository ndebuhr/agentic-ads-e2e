"""Runs skill scripts the way a workstation agent would: as commands in the workspace.

ADK's built-in run_skill_script copies a script into a temp directory and runs it
in-process, which breaks workspace-relative paths (media/..., specs) and the uv
shebangs that install each script's dependencies. This runner executes the real
file from the skills directory with the workspace as its working directory, and
asks the user to confirm anything that writes to an ad account or spends money.
"""
import os
import subprocess
from pathlib import Path

from google.adk.tools import FunctionTool

from .config import SKILLS_DIR, WORKSPACE

TIMEOUT_SECONDS = 900
MAX_OUTPUT_CHARS = 40_000

# Subcommands that change a live Google Ads account. A --dry-run of any of them
# only validates, so it runs without confirmation.
ADS_WRITE_COMMANDS = {
    "google-ads-search-campaigns/search_campaign.py": {"create", "add-keywords", "add-negatives", "set-status"},
    "google-ads-rsa/rsa.py": {"create", "set-status"},
    "google-ads-asset-groups/asset_group.py": {"create"},
    "google-ads-experiments/experiments.py": {
        "create", "rename-treatment", "schedule", "end", "promote", "graduate"},
}
# Scripts that only read inputs and write local files.
LOCAL_SCRIPTS = {
    "ad-video-assembler/assemble_ad.py",
    "ad-video-qa/qa_video_ad.py",
    "brand-endcard-animator/animate_endcard.py",
}
# Scripts that need a person at a terminal (browser consent, software installs).
TERMINAL_ONLY = {
    "google-ads-auth/setup_oauth.py": "--check",
    "genmedia-video-editing/setup.sh": None,
}


def _key(skill: str, script: str) -> str:
    return f"{skill}/{script}"


def _resolve(skill: str, script: str) -> Path:
    scripts_dir = (SKILLS_DIR / skill / "scripts").resolve()
    path = (scripts_dir / script).resolve()
    if path.parent != scripts_dir or not path.is_file():
        raise ValueError(f"No script {script!r} in skill {skill!r}")
    return path


def needs_confirmation(skill: str, script: str, args: list[str]) -> bool:
    """Confirm account writes and paid generation; everything else runs directly."""
    key = _key(skill, script)
    if key in ADS_WRITE_COMMANDS:
        return bool(args) and args[0] in ADS_WRITE_COMMANDS[key] and "--dry-run" not in args
    if key in LOCAL_SCRIPTS or key in TERMINAL_ONLY:
        return False
    if key == "genmedia-video-editing/mcp_call.py":
        return "--list" not in args
    # veo_extend_rest.py, and any script not classified above.
    return True


def run_skill_script(skill: str, script: str, args: list[str]) -> dict:
    """Runs a skill's script, as the skill's own instructions show it.

    Use this wherever a skill shows a shell command for one of its scripts, for
    example `$S create --customer ID --spec media/search/campaign.json --dry-run`.
    Relative paths in args resolve against the workspace.

    Args:
      skill: The skill name, for example "google-ads-search-campaigns".
      script: The file name in the skill's scripts/ directory, for example
        "search_campaign.py".
      args: The command-line arguments, one list item per argument, without
        shell quoting. For example ["create", "--customer", "1234567890",
        "--spec", "media/search/campaign.json", "--dry-run"].

    Returns:
      exit_code, stdout, and stderr. Scripts print JSON on stdout.
    """
    try:
        path = _resolve(skill, script)
    except ValueError as e:
        return {"error": str(e)}
    key = _key(skill, script)
    if key in TERMINAL_ONLY and (TERMINAL_ONLY[key] is None or TERMINAL_ONLY[key] not in args):
        rel = path.relative_to(SKILLS_DIR.parent.parent)
        return {"error": f"{key} needs a person at a terminal. Ask the user to run: {rel} {' '.join(args)}"}
    cmd = [str(path), *args] if os.access(path, os.X_OK) else ["bash" if path.suffix == ".sh" else "python3", str(path), *args]
    try:
        r = subprocess.run(cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {"error": f"Timed out after {TIMEOUT_SECONDS}s"}
    return {"exit_code": r.returncode, "stdout": r.stdout[-MAX_OUTPUT_CHARS:], "stderr": r.stderr[-MAX_OUTPUT_CHARS // 4:]}


def run_skill_script_tool(skills: set[str]) -> FunctionTool:
    """A run_skill_script tool limited to the scripts of the given skills."""
    def run_allowed(skill: str, script: str, args: list[str]) -> dict:
        if skill not in skills:
            return {"error": f"Skill {skill!r} is not available to this agent. Available: {sorted(skills)}"}
        return run_skill_script(skill, script, args)

    run_allowed.__name__ = run_skill_script.__name__
    run_allowed.__doc__ = run_skill_script.__doc__
    return FunctionTool(run_allowed, require_confirmation=needs_confirmation)
