"""ffmpeg helpers: probing, frame/audio extraction, stitching, and seam metrics."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

SR = 32000  # MiniMax H3 generates 32 kHz stereo audio


def _run(args: list[str]) -> bytes:
    p = subprocess.run(args, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:6])}... failed:\n{p.stderr.decode()[-2000:]}")
    return p.stdout


def duration(path: str | Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def extract_frame(clip: str | Path, dest: str | Path, which: str = "last") -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if which == "first":
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-frames:v", "1", str(dest)])
    else:
        _run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.1", "-i", str(clip), "-update", "1", "-frames:v", "1", str(dest)])
    return dest


def extract_frame_at(clip: str | Path, t: float, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1", str(dest)])
    return dest


def cut(clip: str | Path, dest: str | Path, start: float, length: float | None = None) -> Path:
    """Frame-accurate cut of video and audio."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(start, 0):.3f}", "-i", str(clip)]
    if length:
        args += ["-t", f"{length:.3f}"]
    _run(args + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(dest)])
    return dest


def trim_head(clip: str | Path, seconds: float) -> Path:
    clip = Path(clip)
    tmp = cut(clip, clip.with_suffix(".trim.mp4"), seconds)
    return tmp.replace(clip)


# ----------------------------------------------------------------------------
# Stitching
# ----------------------------------------------------------------------------
def stitch(clips: list[str | Path], dest: str | Path, crossfade: float = 0.0) -> Path:
    """Join clips. crossfade=0 is a hard cut; >0 dissolves video and audio at each join."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    clips = [str(c) for c in clips]
    if len(clips) == 1:
        _run(["ffmpeg", "-y", "-v", "error", "-i", clips[0], "-c", "copy", str(dest)])
        return dest
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", c]
    n = len(clips)
    if crossfade <= 0:
        streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        fc = f"{streams}concat=n={n}:v=1:a=1[v][a]"
    else:
        durs = [duration(c) for c in clips]
        parts, v_prev, a_prev, offset = [], "[0:v]", "[0:a]", 0.0
        for i in range(1, n):
            offset += durs[i - 1] - crossfade
            v_out, a_out = f"[v{i}]", f"[a{i}]"
            parts.append(f"{v_prev}[{i}:v]xfade=transition=fade:duration={crossfade}:offset={offset:.3f}{v_out}")
            parts.append(f"{a_prev}[{i}:a]acrossfade=d={crossfade}{a_out}")
            v_prev, a_prev = v_out, a_out
        fc = ";".join(parts)
        fc = fc.replace(f"[v{n-1}]", "[v]").replace(f"[a{n-1}]", "[a]")
    _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(dest)])
    return dest


# ----------------------------------------------------------------------------
# Seam metrics: how visible / audible are the joins?
# ----------------------------------------------------------------------------
def _gray_frames(clip: str | Path, w: int = 64, h: int = 36) -> np.ndarray:
    raw = _run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"scale={w}:{h},format=gray",
                "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def _pcm(clip: str | Path) -> np.ndarray:
    raw = _run(["ffmpeg", "-v", "error", "-i", str(clip), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"])
    return np.frombuffer(raw, np.float32)


def _rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))


def seam_report(clips: list[str | Path], window: float = 0.25) -> list[dict]:
    """For each join between clip i and i+1 (as hard-cut), measure:

    video_jump: mean abs pixel change across the join divided by the median
        frame-to-frame change inside the two clips. ~1 means the cut is as smooth
        as normal motion; >>1 means a visible jump; <<1 suggests a freeze.
    audio_jump_db: RMS level after the join minus before (same metric as the
        vLLM-Omni H3 long-video work, issue #6737).
    """
    out = []
    for i in range(len(clips) - 1):
        a, b = _gray_frames(clips[i]), _gray_frames(clips[i + 1])
        inner = np.concatenate([np.abs(np.diff(a, axis=0)).mean(axis=(1, 2)),
                                np.abs(np.diff(b, axis=0)).mean(axis=(1, 2))])
        jump = float(np.abs(b[0] - a[-1]).mean())
        base = float(np.median(inner)) or 1e-6
        pa, pb = _pcm(clips[i]), _pcm(clips[i + 1])
        n = int(window * SR)
        out.append({
            "join": f"{i}->{i+1}",
            "video_jump": round(jump / base, 2),
            "audio_jump_db": round(_rms_db(pb[:n]) - _rms_db(pa[-n:]), 2),
        })
    return out
