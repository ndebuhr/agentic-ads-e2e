#!/usr/bin/env python3
"""Call one tool on a genmedia MCP server over stdio and print the result.

Usage:
  mcp_call.py <server-binary> <tool-name> '<json-arguments>' [--timeout SECONDS]
  mcp_call.py <server-binary> --list

Examples:
  mcp_call.py mcp-veo-go veo_extend_video '{"video_uri":"gs://b/in.mp4","prompt":"...","output_directory":"media"}'
  mcp_call.py mcp-avtool-go --list

Environment (GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GENMEDIA_BUCKET) is
inherited by the server. Keeps stdin open until the tool result arrives, so
long-running Veo/Omni jobs finish before the server exits.
"""
import json, os, shutil, subprocess, sys, time

def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__); sys.exit(2)
    binary, rest = args[0], args[1:]
    timeout = 900
    if "--timeout" in rest:
        i = rest.index("--timeout"); timeout = int(rest[i + 1]); del rest[i:i + 2]
    path = shutil.which(binary) or os.path.expanduser(f"~/.local/bin/{binary}")
    if not os.path.exists(path):
        print(f"server binary not found: {binary} (run scripts/setup.sh)"); sys.exit(1)

    log_path = os.environ.get("MCP_CALL_LOG", f"/tmp/mcp_call-{binary}-{os.getpid()}.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=log, text=True, bufsize=1)

    def send(msg): proc.stdin.write(json.dumps(msg) + "\n"); proc.stdin.flush()
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "mcp_call", "version": "1"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    if rest[0] == "--list":
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    else:
        tool, raw = rest[0], (rest[1] if len(rest) > 1 else "{}")
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": tool, "arguments": json.loads(raw)}})

    deadline = time.time() + timeout
    result = None
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line.startswith("{"):
            continue
        msg = json.loads(line)
        if msg.get("id") == 2:
            result = msg; break
    proc.stdin.close(); proc.terminate(); proc.wait(timeout=10); log.close()
    def fail(msg):
        print(msg)
        print(f"--- server log ({log_path}) tail ---")
        print("".join(open(log_path).readlines()[-8:]))
        sys.exit(1)
    if result is None:
        fail("no result before timeout")
    if "error" in result:
        fail("ERROR: " + json.dumps(result["error"], indent=2))
    res = result["result"]
    if "tools" in res:
        for t in res["tools"]:
            props = t.get("inputSchema", {}).get("properties", {})
            print(f"- {t['name']}: {', '.join(props)}")
        return
    for item in res.get("content", []):
        if item.get("type") == "text":
            print(item["text"])
        elif item.get("type") == "resource_link":
            print("resource:", item.get("uri"), item.get("name", ""))
        else:
            print(json.dumps(item)[:500])
    if res.get("isError"):
        fail("(tool reported isError)")

if __name__ == "__main__":
    main()
