"""File and image tools scoped to the workspace, standing in for a workstation agent's own."""
from pathlib import Path

from google import genai
from google.adk.tools import FunctionTool
from google.genai import types

from .config import GOOGLE_CLOUD_PROJECT, WORKSPACE

MAX_READ_CHARS = 100_000
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


def generate_image(prompt: str, output_path: str, aspect_ratio: str = "1:1") -> dict:
    """Generates an ad image with Gemini on Vertex AI and saves it in the workspace.

    Use it where the gcp-image-generation skill calls generate_content on
    geap-generate; it decodes and saves the image for you.

    Args:
      prompt: The full image prompt.
      output_path: Where to save it, for example media/hero-16x9.png.
      aspect_ratio: "1:1", "16:9", "4:5", "9:16", and similar.
    """
    try:
        out = _path(output_path)
        client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location="global")
        resp = client.models.generate_content(
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
    return {"saved": str(out.relative_to(WORKSPACE)), "bytes": len(part.inline_data.data), "mime_type": part.inline_data.mime_type}


generate_image_tool = FunctionTool(generate_image, require_confirmation=True)
