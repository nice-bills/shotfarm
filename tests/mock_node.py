"""A fake ComfyUI node for testing the farm without GPUs.

Speaks the subset of the ComfyUI API ShotFarm uses. Each /prompt "renders" for
`render_seconds` (simulating H3's ~2 min per 5 s clip, scaled down), then
produces a real MP4 (test pattern + tone) or PNG with ffmpeg, so stitching and
seam metrics run on genuine media.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class MockNode:
    def __init__(self, render_seconds: float = 0.5, fail_first: int = 0):
        self.render_seconds = render_seconds
        self.fail_first = fail_first
        self.dir = Path(tempfile.mkdtemp(prefix="mocknode_"))
        self.history: dict[str, dict] = {}
        self.prompts = 0
        self.lock = threading.Lock()  # one GPU = one job at a time
        node = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body: bytes, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/system_stats":
                    return self._send(200, b'{"ok":true}')
                if u.path == "/object_info":
                    return self._send(200, b'{"TextEncode":{}}')
                if u.path.startswith("/history/"):
                    pid = u.path.split("/")[-1]
                    h = node.history.get(pid)
                    return self._send(200, json.dumps({pid: h} if h else {}).encode())
                if u.path == "/view":
                    f = node.dir / parse_qs(u.query)["filename"][0]
                    return self._send(200, f.read_bytes(), "application/octet-stream")
                self._send(404, b"{}")

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(n)
                if self.path == "/upload/image":
                    m = re.search(rb'filename="([^"]+)"', body)
                    name = m.group(1).decode() if m else "upload.bin"
                    return self._send(200, json.dumps({"name": name}).encode())
                if self.path == "/prompt":
                    wf = json.loads(body)["prompt"]
                    with node.lock:
                        node.prompts += 1
                        if node.prompts <= node.fail_first:
                            return self._send(500, b'{"error":"simulated node failure"}')
                    pid = uuid.uuid4().hex
                    threading.Thread(target=node._render, args=(pid, wf), daemon=True).start()
                    return self._send(200, json.dumps({"prompt_id": pid}).encode())
                self._send(404, b"{}")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _render(self, pid: str, wf: dict):
        with self.lock:
            time.sleep(self.render_seconds)
            meta = wf.get("meta", {})
            kind = meta.get("kind", "video")
            seed = int(meta.get("seed", 0))
            if kind == "image":
                name = f"{pid}.png"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                                f"color=c=0x{(seed * 2654435761) & 0xFFFFFF:06x}:s=320x192", "-frames:v", "1",
                                str(self.dir / name)], check=True)
                out = {"9": {"images": [{"filename": name, "subfolder": "", "type": "output"}]}}
            else:
                secs = float(meta["frames"]) / 24 if "frames" in meta else float(meta.get("seconds", 4))
                name = f"{pid}.mp4"
                subprocess.run(["ffmpeg", "-y", "-v", "error",
                                "-f", "lavfi", "-i", f"testsrc2=s=320x192:r=24:d={secs}",
                                "-f", "lavfi", "-i", f"sine=f={220 + seed % 400}:d={secs}:sample_rate=32000",
                                "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-ac", "2", str(self.dir / name)], check=True)
                out = {"9": {"videos": [{"filename": name, "subfolder": "", "type": "output"}]}}
        self.history[pid] = {"status": {"status_str": "success"}, "outputs": out}

    def close(self):
        self.server.shutdown()
