"""File, media, and artifact tools scoped to the workspace, standing in for a workstation agent's own."""
import mimetypes
from pathlib import Path

from google import genai
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.plugins import BasePlugin
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types

from .config import GOOGLE_CLOUD_PROJECT, WORKSPACE

MAX_READ_CHARS = 100_000
# Gemini takes at most about 20 MB of inline data per request.
MAX_VIEW_BYTES = 15 * 1024 * 1024
VIEWABLE_TYPES = ("image/", "video/", "audio/", "application/pdf")
IMAGE_MODEL = "gemini-2.5-flash-image"


def _path(rel: str) -> Path:
    p = (WORKSPACE / rel).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError(f"{rel} is outside the workspace")
    return p


def list_files(directory: str = ".") -> dict:
    """Lists files and folders in a workspace directory (relative path)."""
    try:
        d = _path(directory)
        return {"entries": sorted(f"{e.name}/" if e.is_dir() else e.name for e in d.iterdir() if not e.name.startswith("."))}
    except (ValueError, OSError) as e:
        return {"error": str(e)}


def read_file(path: str) -> dict:
    """Reads a text file in the workspace, such as a spec or a site page."""
    try:
        return {"content": _path(path).read_text()[:MAX_READ_CHARS]}
    except (ValueError, OSError, UnicodeDecodeError) as e:
        return {"error": str(e)}


def write_file(path: str, content: str) -> dict:
    """Writes a text file in the workspace, creating folders as needed.

    Use it for the JSON specs the skills fill in, for example
    media/search/campaign.json. Overwrites an existing file.
    """
    try:
        p = _path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return {"written": str(p.relative_to(WORKSPACE)), "bytes": len(content.encode())}
    except (ValueError, OSError) as e:
        return {"error": str(e)}


def _mime_type(path: str) -> str | None:
    return mimetypes.guess_type(path)[0]


def view_file(path: str) -> dict:
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
    try:
        p = _path(path)
        size = p.stat().st_size
        if size > MAX_VIEW_BYTES:
            return {"error": f"{path} is {size / 2**20:.1f} MB; the limit is {MAX_VIEW_BYTES // 2**20} MB. View a storyboard or extracted frames instead."}
        return {"file": path, "media": types.Part.from_bytes(data=p.read_bytes(), mime_type=mime)}
    except (ValueError, OSError) as e:
        return {"error": str(e)}


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


async def _save_artifact(tool_context: ToolContext, rel: str, data: bytes, mime: str) -> int:
    return await tool_context.save_artifact(rel, types.Part.from_bytes(data=data, mime_type=mime))


async def share_file(path: str, tool_context: ToolContext) -> dict:
    """Shares a workspace file with the user in the chat, where they can preview and download it.

    Call it for each finished image, video, or audio file you produce, so the
    user can review it without opening the workspace. Sharing a file again
    after a change adds a new version.
    """
    try:
        p = _path(path)
        rel = str(p.relative_to(WORKSPACE))
        version = await _save_artifact(tool_context, rel, p.read_bytes(), _mime_type(rel) or "application/octet-stream")
    except (ValueError, OSError) as e:
        return {"error": str(e)}
    return {"shared": rel, "version": version}


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
    try:
        p = _path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(part.inline_data.data)
    except (ValueError, OSError) as e:
        return {"error": str(e)}
    return {"saved": str(p.relative_to(WORKSPACE)), "bytes": len(part.inline_data.data), "mime_type": part.inline_data.mime_type}


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
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(part.inline_data.data)
    rel = str(out.relative_to(WORKSPACE))
    version = await _save_artifact(tool_context, rel, part.inline_data.data, part.inline_data.mime_type)
    return {"saved": rel, "shared_version": version, "bytes": len(part.inline_data.data), "mime_type": part.inline_data.mime_type}


generate_image_tool = FunctionTool(generate_image, require_confirmation=True)
