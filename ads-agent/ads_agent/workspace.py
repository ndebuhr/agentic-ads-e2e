"""File, media, and artifact tools scoped to the workspace, standing in for a workstation agent's own."""
import json
import mimetypes
import re
from pathlib import Path

from google import genai
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.plugins import BasePlugin
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types

from .config import GOOGLE_CLOUD_PROJECT, SKILLS_DIR, WORKSPACE

MAX_READ_CHARS = 100_000
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_SEARCH_MATCHES = 200
# Any tool result larger than this is withheld from the model (for example a 23 MB skill asset).
MAX_RESULT_CHARS = 200_000
# Gemini takes at most about 20 MB of inline data per request.
MAX_VIEW_BYTES = 15 * 1024 * 1024
VIEWABLE_TYPES = ("image/", "video/", "audio/", "application/pdf")
IMAGE_MODEL = "gemini-2.5-flash-image"


def _path(rel: str) -> Path:
    p = (WORKSPACE / rel).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError(f"{rel} is outside the workspace")
    if ".git" in p.parts or ".git" in Path(rel).parts:
        raise ValueError(f"{rel} is inside a .git folder, which these tools don't open")
    return p


def _rel(p: Path) -> str:
    return str(p.relative_to(WORKSPACE))


def _write(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


async def list_files(directory: str = ".") -> dict:
    """Lists files and folders in a workspace directory (relative path)."""
    return {"entries": sorted(f"{e.name}/" if e.is_dir() else e.name for e in _path(directory).iterdir() if not e.name.startswith("."))}


async def read_file(path: str) -> dict:
    """Reads a text file in the workspace, such as a spec or a site page."""
    p = _path(path)
    if (size := p.stat().st_size) > MAX_READ_BYTES:
        return {"error": f"{path} is {size / 2**20:.1f} MB, too large to read. Query it with a skill script instead."}
    return {"content": p.read_text()[:MAX_READ_CHARS]}


async def search_file(path: str, pattern: str, max_matches: int = 50) -> dict:
    """Returns the lines of a workspace file that match a pattern, like `grep -i PATTERN FILE`.

    Use it wherever a skill shows a grep one-liner, and to search files too
    large to read, such as a skill's CSV data.

    Args:
      path: Workspace-relative path of the file.
      pattern: A regular expression, matched case-insensitively against each
        line, for example '"Boulder County,Colorado,'.
      max_matches: How many matching lines to return (at most 200).
    """
    regex = re.compile(pattern, re.IGNORECASE)
    limit = min(max_matches, MAX_SEARCH_MATCHES)
    matches, total = [], 0
    with _path(path).open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if regex.search(line):
                total += 1
                if len(matches) < limit:
                    matches.append(line.rstrip("\n"))
    return {"matches": matches, "total": total}


async def write_file(path: str, content: str) -> dict:
    """Writes a text file in the workspace, creating folders as needed.

    Use it for the JSON specs the skills fill in, for example
    media/search/campaign.json. Overwrites an existing file.
    """
    p = _path(path)
    data = content.encode()
    _write(p, data)
    return {"written": _rel(p), "bytes": len(data)}


def _mime_type(path: str) -> str | None:
    return mimetypes.guess_type(path)[0]


async def view_file(path: str) -> dict:
    """Shows you an image, video, audio clip, or PDF so you can judge it yourself.

    Use it to check generated creative, storyboards and contact sheets, end
    cards, and brand assets. Files must be under 15 MB; for a longer video,
    view its storyboard or extract a few frames first.

    Args:
      path: A workspace-relative path, or a gs:// URI for a file in Cloud Storage.
    """
    mime = _mime_type(path)
    if not mime or not mime.startswith(VIEWABLE_TYPES):
        return {"error": f"Can't view {path}: not an image, video, audio, or PDF file. Use read_file for text."}
    if path.startswith("gs://"):
        return {"file": path, "media": types.Part.from_uri(file_uri=path, mime_type=mime)}
    p = _path(path)
    size = p.stat().st_size
    if size > MAX_VIEW_BYTES:
        return {"error": f"{path} is {size / 2**20:.1f} MB; the limit is {MAX_VIEW_BYTES // 2**20} MB. View a storyboard or extracted frames instead."}
    return {"file": path, "media": types.Part.from_bytes(data=p.read_bytes(), mime_type=mime)}


class DropOldToolMedia(BasePlugin):
    """Sends media returned by view_file to the model once, not on every later call.

    ADK keeps tool-returned media in the session, so without this each image
    or clip viewed would be re-sent with every request for the rest of the
    session. The model keeps the text part of the result (the file path) and
    can view the file again if it needs to.
    """

    def __init__(self) -> None:
        super().__init__(name="drop_old_tool_media")

    async def before_model_callback(self, *, callback_context: CallbackContext, llm_request: LlmRequest) -> None:
        # Copies, not edits: the contents can share objects with the session's events.
        for i, content in enumerate(llm_request.contents[:-1]):
            if not any(p.function_response and p.function_response.parts for p in content.parts or []):
                continue
            llm_request.contents[i] = content.model_copy(update={"parts": [
                p.model_copy(update={"function_response": p.function_response.model_copy(update={"parts": None})})
                if p.function_response and p.function_response.parts else p
                for p in content.parts]})


class CapToolResults(BasePlugin):
    """Withholds any tool result too large for the model's context.

    Skills can bundle large assets (the geo targets CSV is 23 MB), and
    load_skill_resource would return one whole. Media parts, which the
    framework sends separately, aren't counted.
    """

    def __init__(self) -> None:
        super().__init__(name="cap_tool_results")

    async def before_tool_callback(self, *, tool, tool_args: dict, tool_context: ToolContext) -> dict | None:
        # Checked before loading too: ADK attaches a binary asset to the next model request
        # itself, so a large non-UTF-8 file would get past the result check below.
        if tool.name != "load_skill_resource":
            return None
        p = SKILLS_DIR / str(tool_args.get("skill_name")) / str(tool_args.get("file_path"))
        if p.is_file() and p.stat().st_size > MAX_RESULT_CHARS:
            return {"error": f"{tool_args.get('file_path')} is {p.stat().st_size:,} bytes, too large to show you. "
                             "Search it with search_file instead of loading it."}
        return None

    async def after_tool_callback(self, *, tool, tool_args: dict, tool_context: ToolContext, result) -> dict | None:
        size = len(json.dumps(result, default=lambda _: ""))
        if size <= MAX_RESULT_CHARS:
            return None
        return {"error": f"{tool.name} returned {size:,} characters, too large to show you. "
                         "Search the file with search_file instead of loading it."}


async def _share(tool_context: ToolContext, p: Path, data: bytes, mime: str | None = None) -> int:
    mime = mime or _mime_type(p.name) or "application/octet-stream"
    return await tool_context.save_artifact(_rel(p), types.Part.from_bytes(data=data, mime_type=mime))


async def share_file(path: str, tool_context: ToolContext) -> dict:
    """Shares a workspace file with the user in the chat, where they can preview and download it.

    Call it for each finished image, video, or audio file you produce, so the
    user can review it without opening the workspace. Sharing a file again
    after a change adds a new version.
    """
    p = _path(path)
    return {"shared": _rel(p), "version": await _share(tool_context, p, p.read_bytes())}


async def save_upload(artifact_name: str, path: str, tool_context: ToolContext) -> dict:
    """Saves a file the user uploaded in the chat into the workspace.

    Uploads appear in the conversation as [Uploaded Artifact: "name"]. Use this
    to keep one as a brand asset or as source material, for example
    brand_assets/logo.png. Overwrites an existing file.

    Args:
      artifact_name: The name shown in the upload placeholder.
      path: Workspace-relative destination path.
    """
    part = await tool_context.load_artifact(artifact_name)
    if part is None or part.inline_data is None or part.inline_data.data is None:
        return {"error": f"No uploaded file named {artifact_name!r} in this session"}
    p = _path(path)
    _write(p, part.inline_data.data)
    return {"saved": _rel(p), "bytes": len(part.inline_data.data), "mime_type": part.inline_data.mime_type}


async def generate_image(prompt: str, output_path: str, tool_context: ToolContext, aspect_ratio: str = "1:1") -> dict:
    """Generates an ad image with Gemini on Vertex AI, saves it in the workspace, and shares it in the chat.

    Use it where the gcp-image-generation skill calls generate_content on
    geap-generate; it decodes and saves the image for you. Check the result
    with view_file.

    Args:
      prompt: The full image prompt.
      output_path: Where to save it, for example media/hero-16x9.png.
      aspect_ratio: "1:1", "16:9", "4:5", "9:16", and similar.
    """
    try:
        out = _path(output_path)
        client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")
        resp = await client.aio.models.generate_content(
            model=IMAGE_MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"], image_config=types.ImageConfig(aspect_ratio=aspect_ratio)))
        part = next(p for p in resp.candidates[0].content.parts if p.inline_data)
    except StopIteration:
        return {"error": "The model returned no image"}
    except Exception as e:  # API and auth errors go back to the model as text.
        return {"error": str(e)}
    image = part.inline_data
    _write(out, image.data)
    version = await _share(tool_context, out, image.data, image.mime_type)
    return {"saved": _rel(out), "shared_version": version, "bytes": len(image.data), "mime_type": image.mime_type}


generate_image_tool = FunctionTool(generate_image, require_confirmation=True)
