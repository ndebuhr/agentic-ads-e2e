# agentic-ads-e2e

Agent skills and infrastructure for running Google Ads campaigns end-to-end, from creative generation to campaign reporting.

- `.agents/skills/` — agent skills for image generation, video editing, and Google Ads campaign summaries
- `google-ads-e2e/` — Terraform to deploy the official Google Ads MCP server on Cloud Run (see its README)

## MCP servers

The skills expect these servers in Antigravity. Register them with `agy mcp add`; the config lives in `~/.gemini/config/mcp_config.json`.

**GEAP (Vertex AI) — image generation and prediction.** These use OAuth. Create an OAuth 2.0 *Web application* client in your Google Cloud project with:

- Authorized JavaScript origin: `https://antigravity.google`
- Authorized redirect URI: `https://antigravity.google/oauth-callback`

Then add the servers and attach the client to each entry in `mcp_config.json` (`agy mcp add` has no OAuth flag):

```bash
agy mcp add geap-generate https://aiplatform.googleapis.com/mcp/generate
agy mcp add geap-predict  https://aiplatform.googleapis.com/mcp/predict
```

```json
"geap-generate": {
  "serverUrl": "https://aiplatform.googleapis.com/mcp/generate",
  "oauth": { "clientId": "<CLIENT_ID>.apps.googleusercontent.com", "clientSecret": "<CLIENT_SECRET>" }
}
```

**GenMedia (Veo, Omni, avtool) — video generation and editing.** Local stdio servers. One script installs the binaries, checks ffmpeg, creates the output bucket, and registers them:

```bash
bash .agents/skills/genmedia-video-editing/scripts/setup.sh [--project PROJECT_ID] [--bucket BUCKET]
```

**Google Ads MCP.** Deployed to Cloud Run by the Terraform in `google-ads-e2e/`; its output prints the exact `agy mcp add google-ads-mcp <url>/mcp` command. See that README.

Verify with `agy mcp list`.

## License

MIT. See [LICENSE](LICENSE).
