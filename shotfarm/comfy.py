"""Minimal ComfyUI HTTP client (stdlib only).

Each Nosana MiniMax H3 deployment exposes ComfyUI behind a service URL. We talk
to it with the standard ComfyUI API: upload inputs, POST /prompt, poll
/history/<id>, download outputs via /view.
"""
from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    # -- low level -----------------------------------------------------------
    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return r.read()

    def _post_json(self, path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            # ComfyUI explains a rejected workflow in the body (node_errors).
            raise ComfyError(f"{path} returned {e.code}: {e.read()[:2000].decode(errors='replace')}") from e

    # -- API -----------------------------------------------------------------
    def healthy(self) -> bool:
        try:
            self._get("/system_stats")
            return True
        except Exception:
            return False

    def missing_nodes(self, class_types: set[str]) -> set[str]:
        """Which of these node types does this ComfyUI not have installed?"""
        return class_types - json.loads(self._get("/object_info")).keys()

    def upload(self, path: str | Path, kind: str = "image") -> str:
        """Upload a local file to ComfyUI's input folder; returns the server-side name."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: {ctype}\r\n\r\n"
        ).encode() + path.read_bytes() + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
            f"\r\n--{boundary}--\r\n"
        ).encode()
        # ComfyUI accepts any file type through /upload/image (audio included).
        req = urllib.request.Request(
            f"{self.base}/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["name"]

    def queue(self, workflow: dict) -> str:
        res = self._post_json("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if "prompt_id" not in res:
            raise ComfyError(f"queue failed: {res}")
        return res["prompt_id"]

    def wait(self, prompt_id: str, poll: float = 3.0, max_wait: float = 1800) -> dict:
        start, blips = time.time(), 0
        while time.time() - start < max_wait:
            try:
                hist = json.loads(self._get(f"/history/{prompt_id}") or b"{}")
                blips = 0
            except OSError:
                # A network blip must not throw away a render still running on the GPU.
                blips += 1
                if blips > 5:
                    raise
                time.sleep(poll)
                continue
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"prompt {prompt_id} failed: {status}")
                if entry.get("outputs"):
                    return entry["outputs"]
            time.sleep(poll)
        raise ComfyError(f"prompt {prompt_id} timed out after {max_wait}s")

    def download_first(self, outputs: dict, dest: str | Path, keys=("videos", "gifs", "images", "audio")) -> Path:
        """Download the first saved file in the outputs dict.

        Returns dest with the server file's extension: a video-only node answers
        an image request with an .mp4, and a preview node's temp file is skipped.
        """
        for node_out in outputs.values():
            for key in keys:
                for f in node_out.get(key, []):
                    if f.get("type", "output") != "output":
                        continue
                    q = urllib.parse.urlencode(
                        {"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")}
                    )
                    dest = Path(dest).with_suffix(Path(f["filename"]).suffix)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(self._get(f"/view?{q}"))
                    return dest
        raise ComfyError(f"no downloadable output in {list(outputs)}")
