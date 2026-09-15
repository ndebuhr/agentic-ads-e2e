---
name: gcp-image-generation
description: >-
  Generates commercial advertising and marketing images for ad campaigns using
  the GEAP MCP (Google Enterprise Agent Platform) or generative image models.
  Use this skill whenever the user asks to create, generate, design, or produce
  ad creative images, product photography, or marketing visuals.
---

# Google Ads Image Generation Skill

This skill provides a runbook for generating high-converting commercial advertising images, product photos, and campaign creative assets using the `geap-generate` MCP tool.

## Workflow

### 1. Determine Project ID & Model Endpoint
* Determine the target Google Cloud Project ID (from workspace configuration, environment variables, or user prompt).
* Construct the fully qualified publisher model path using the **global** endpoint:
  `projects/{PROJECT_ID}/locations/global/publishers/google/models/{MODEL_ID}`
* **Recommended Models:**
  * `gemini-2.5-flash-image`: Fast, high-fidelity commercial imagery and product shots.
  * `gemini-3.1-flash-image`: Next-generation detail and complex visual prompt adherence.
  * `gemini-3-pro-image`: Maximum quality for hero marketing assets and high-res print/display.

### 2. Formulate Ad-Optimized Prompts
Tailor the visual prompt to the target ad placement and audience:

* **Aspect Ratio Guidelines for Google Ads:**
  * **Landscape (`1.91:1` or `16:9`):** Primary format for Performance Max, Google Display Network (GDN), and YouTube overlays.
  * **Square (`1:1`):** Required for Performance Max, Shopping feeds, and universal ad units.
  * **Portrait (`4:5` or `9:16`):** Vertical video feeds, YouTube Shorts, and mobile placements.
* **Prompt Ingredients:**
  * **Subject & Product:** Define packaging, textures, materials, and placement clearly.
  * **Lighting & Mood:** Specify lighting style (e.g., golden hour, studio tabletop, warm cinematic backlight).
  * **Background & Context:** Realistic, complementary surroundings with natural depth of field.
  * **Copy Space:** Leave uncluttered negative space if headline or CTA text overlays are needed.

### 3. Generate the Image via MCP
Invoke `call_mcp_tool` on `geap-generate`:
* **ServerName**: `geap-generate`
* **ToolName**: `generate_content`
* **Arguments**:
  ```json
  {
    "model": "projects/{PROJECT_ID}/locations/global/publishers/google/models/gemini-2.5-flash-image",
    "generationConfig": {
      "responseModalities": ["IMAGE"]
    },
    "contents": [
      {
        "role": "user",
        "parts": [
          {
            "text": "{AD_IMAGE_PROMPT}"
          }
        ]
      }
    ]
  }
  ```

### 4. Decode and Save the Image File
1. Extract the base64-encoded image payload from the response:
   `response.candidates[0].content.parts[0].inlineData.data`
2. Decode the base64 string and save it as a PNG/JPEG file in the `media/` directory (create the directory if it does not already exist).
3. Confirm the file size and verify that the image is non-empty.

### 5. Review & Deliver Asset
1. Inspect the resulting image file using `view_file` to verify image fidelity, branding consistency, and composition.
2. Embed or link the saved image in your response using clickable GitHub-style markdown links:
   `[image_name.png](file:///absolute/path/to/media/image_name.png)`
3. Provide recommended ad copy or headlines that pair effectively with the visual.
