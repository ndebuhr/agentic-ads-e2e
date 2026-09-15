#!/usr/bin/env python3
"""Extend a video with Veo via the raw Vertex REST long-running pair.

Fallback for when the genmedia MCP server's model registry rejects a model for
extension. Submits predictLongRunning, polls fetchPredictOperation, and
downloads the result.

Usage:
  veo_extend_rest.py --video gs://bucket/input/clip-24fps.mp4 --prompt "..." \
      [--model veo-3.1-fast-generate-001] [--out-prefix gs://bucket/veo_outputs/] \
      [--download media/] [--project P] [--location us-central1] [--timeout 600]
"""
import argparse, json, os, subprocess, sys, time, urllib.request

def gcloud(*args):
    return subprocess.check_output(["gcloud", *args], text=True).strip()

def call(url, token, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True); ap.add_argument("--prompt", default="")
    ap.add_argument("--model", default="veo-3.1-fast-generate-001")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT") or gcloud("config", "get-value", "project"))
    ap.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    ap.add_argument("--out-prefix", default=None, help="gs:// prefix for output (default gs://$GENMEDIA_BUCKET/veo_outputs/)")
    ap.add_argument("--download", default=None, help="local dir to download the result into")
    ap.add_argument("--name", default=None, help="local filename base (default: keep GCS name, e.g. sample_0.mp4)")
    ap.add_argument("--sample-count", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    out = a.out_prefix or f"gs://{os.environ['GENMEDIA_BUCKET']}/veo_outputs/"
    token = gcloud("auth", "print-access-token")
    host = "aiplatform.googleapis.com" if a.location == "global" else f"{a.location}-aiplatform.googleapis.com"
    base = f"https://{host}/v1/projects/{a.project}/locations/{a.location}/publishers/google/models/{a.model}"
    body = {"instances": [{"prompt": a.prompt, "video": {"gcsUri": a.video, "mimeType": "video/mp4"}}],
            "parameters": {"sampleCount": a.sample_count, "storageUri": out}}
    op = call(f"{base}:predictLongRunning", token, body)["name"]
    print("operation:", op, flush=True)
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        time.sleep(15)
        st = call(f"{base}:fetchPredictOperation", token, {"operationName": op})
        if st.get("done"):
            if "error" in st:
                print("FAILED:", json.dumps(st["error"])); sys.exit(1)
            vids = st.get("response", {}).get("videos", [])
            if not vids and st.get("response", {}).get("raiMediaFilteredCount"):
                print("FILTERED:", json.dumps(st["response"])); sys.exit(1)
            for i, v in enumerate(vids):
                uri = v.get("gcsUri"); print("video:", uri)
                if a.download and uri:
                    os.makedirs(a.download, exist_ok=True)
                    fname = os.path.basename(uri) if not a.name else (a.name + (f"_{i}" if len(vids) > 1 else "") + ".mp4")
                    dest = os.path.join(a.download, fname)
                    subprocess.check_call(["gcloud", "storage", "cp", "-q", uri, dest])
                    print("downloaded to", dest)
            return
        print("polling...", flush=True)
    print("timed out"); sys.exit(1)

if __name__ == "__main__":
    main()
