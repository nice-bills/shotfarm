"""Three ways to render a long film with a 15-second model.

sequential          Baseline / prior art. Each segment starts from the last
                    frame of the previous one. Seams are good, but it is
                    inherently serial: N segments = N x render time, on one GPU.

parallel_keyframes  Render every keyframe image first (in parallel), then render
                    every segment pinned between keyframe i and i+1 (in parallel).
                    Wall-clock ~= one segment. Known weakness: each segment starts
                    from zero velocity, so motion can stall at the joins.

draft_then_parallel ShotFarm's method. A cheap low-res, low-step sequential
                    *animatic* fixes motion and sound for the whole film. Then
                    the expensive final pass renders every segment in parallel.
                    Each one starts from a 22-frame clip of the animatic just
                    before its join, guiding motion and sound, and ends pinned
                    to the animatic's frame at the next join. The guide frames
                    are cut off afterwards. This is how film render farms work:
                    animatic first, final frames in parallel.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import media
from .comfy import ComfyClient
from .scheduler import Job, RunResult, run_pool
from .storyboard import Segment, Storyboard, frames_for
from .workflow import fill, load_template

GUIDE_FRAMES = 22  # H3 guide clips must be 5, 22, 39... frames; 22 is ~0.9 s of motion and sound


@dataclass
class Templates:
    image: str | None = None    # text -> keyframe image
    i2v: str | None = None      # first frame -> video   (sequential)
    fl2v: str | None = None     # first + last frame -> video (parallel)
    draft: str | None = None    # cheap i2v for the animatic
    final: str | None = None    # guide clip + last frame -> video

    def get(self, name: str) -> dict:
        path = getattr(self, name)
        if not path:
            raise ValueError(f"farm config is missing the '{name}' workflow template")
        return load_template(path)


class Renderer:
    """Turns one unit of work into one ComfyUI job on a given endpoint."""

    def __init__(self, sb: Storyboard, templates: Templates, workdir: Path,
                 client_factory: Callable[[str], ComfyClient] = ComfyClient):
        self.sb, self.t, self.dir = sb, templates, workdir
        self.client = client_factory

    def _values(self, seg: Segment | None, prompt: str, seed: int, seconds: float = 5, **files) -> dict:
        frames = seg.frames if seg and seg.frames else frames_for(seconds, self.sb.fps)
        v = {"PROMPT": prompt, "SEED": seed, "SECONDS": seconds, "FRAMES": frames,
             "WIDTH": self.sb.width, "HEIGHT": self.sb.height, "AUDIO": seg.audio if seg else ""}
        v.update(files)
        return v

    def _run(self, endpoint: str, template: str, values: dict, uploads: dict, dest: Path) -> Path:
        c = self.client(endpoint)
        for key, path in uploads.items():
            values[key] = c.upload(path)
        wf = fill(self.t.get(template), values)
        outputs = c.wait(c.queue(wf))
        return c.download_first(outputs, dest)

    def keyframe(self, endpoint: str, i: int) -> Path:
        dest = self.dir / "keyframes" / f"kf_{i:03d}.png"
        out = self._run(endpoint, "image", self._values(None, self.sb.keyframes[i], 1000 + i), {}, dest)
        # Nosana's H3 template has no image model, so "image" may be a 5-frame T2VA clip.
        return out if out.suffix == dest.suffix else media.extract_frame(out, dest, "first")

    def segment(self, endpoint: str, seg: Segment, template: str, tag: str) -> Path:
        uploads = {}
        if seg.first_frame:
            uploads["FIRST_FRAME"] = seg.first_frame
        if seg.last_frame and template in ("fl2v", "final"):
            uploads["LAST_FRAME"] = seg.last_frame
        if seg.guide_clip and template == "final":
            uploads["GUIDE_CLIP"] = seg.guide_clip
        prompt = f"{seg.prompt} Audio: {seg.audio}".strip() if seg.audio else seg.prompt
        out = self._run(endpoint, template, self._values(seg, prompt, seg.seed, seg.seconds), uploads,
                        self.dir / tag / f"seg_{seg.index:03d}.mp4")
        return media.trim_head(out, GUIDE_FRAMES / self.sb.fps) if "GUIDE_CLIP" in uploads else out


def _keyframes_parallel(r: Renderer, endpoints: list[str], log) -> RunResult:
    n = len(r.sb.keyframes)
    jobs = [Job(f"kf{i}", (lambda ep, i=i: r.keyframe(ep, i))) for i in range(n)]
    res = run_pool(jobs, endpoints, log=log)
    if res.failed:
        raise RuntimeError(f"keyframes failed: {res.failed}")
    return res


def sequential(r: Renderer, endpoints: list[str], log=print) -> dict:
    ep = endpoints[0]
    t0 = time.time()
    kf0 = r.keyframe(ep, 0)
    clips, prev = [], None
    for seg in r.sb.segments:
        seg.first_frame = str(kf0 if prev is None else media.extract_frame(prev, r.dir / "seq_frames" / f"{seg.index}.png"))
        prev = r.segment(ep, seg, "i2v", "sequential")
        clips.append(prev)
        log(f"[seq] segment {seg.index} done at {time.time() - t0:.1f}s")
    return {"clips": clips, "stages": {"total": time.time() - t0}, "gpus": 1}


def parallel_keyframes(r: Renderer, endpoints: list[str], log=print) -> dict:
    t0 = time.time()
    kf = _keyframes_parallel(r, endpoints, log)
    t_kf = time.time() - t0
    for seg in r.sb.segments:
        seg.first_frame = str(kf.results[f"kf{seg.index}"])
        seg.last_frame = str(kf.results[f"kf{seg.index + 1}"])
    jobs = [Job(f"seg{s.index}", (lambda ep, s=s: r.segment(ep, s, "fl2v", "parallel"))) for s in r.sb.segments]
    res = run_pool(jobs, endpoints, log=log)
    if res.failed:
        raise RuntimeError(f"segments failed: {res.failed}")
    clips = [res.results[f"seg{s.index}"] for s in r.sb.segments]
    return {"clips": clips, "stages": {"keyframes": t_kf, "segments": res.wall_seconds, "total": time.time() - t0},
            "gpus": len(endpoints), "timeline": [e.__dict__ for e in kf.timeline + res.timeline]}


def draft_then_parallel(r: Renderer, endpoints: list[str], log=print) -> dict:
    t0 = time.time()
    # 1) animatic: cheap sequential pass that fixes motion + sound for the whole film
    ep = endpoints[0]
    kf0 = r.keyframe(ep, 0)
    drafts, prev = [], None
    for seg in r.sb.segments:
        seg.first_frame = str(kf0 if prev is None else media.extract_frame(prev, r.dir / "draft_frames" / f"{seg.index}.png"))
        prev = r.segment(ep, seg, "draft", "draft")
        drafts.append(prev)
    animatic = media.stitch(drafts, r.dir / "animatic.mp4")
    t_draft = time.time() - t0

    # 2) slice anchors from the animatic. A guided segment generates base + 17 frames to
    # stay on H3's grid and keeps base - 5 once the guide is cut, so the windows stay
    # inside the animatic and the film comes out ~0.2 s shorter per join.
    fps, end, t = r.sb.fps, media.duration(animatic), 0.0
    guide_s = GUIDE_FRAMES / fps
    for seg in r.sb.segments:
        base = frames_for(seg.seconds, fps)
        if seg.index == 0:
            seg.frames, kept = base, base
            seg.first_frame = str(media.extract_frame_at(animatic, 0.0, r.dir / "anchors" / "0_first.png"))
        else:
            seg.frames, kept = base + 17, base - 5
            seg.first_frame = None
            seg.guide_clip = str(media.cut(animatic, r.dir / "anchors" / f"{seg.index}_guide.mp4", t - guide_s, guide_s))
        t += kept / fps
        seg.last_frame = str(media.extract_frame_at(animatic, min(t, end) - 1 / fps, r.dir / "anchors" / f"{seg.index}_last.png"))

    # 3) final pass, all segments at once. Segment 0 has nothing before it to be guided by.
    jobs = [Job(f"seg{s.index}", (lambda ep, s=s: r.segment(ep, s, "final" if s.guide_clip else "fl2v", "final")))
            for s in r.sb.segments]
    res = run_pool(jobs, endpoints, log=log)
    if res.failed:
        raise RuntimeError(f"segments failed: {res.failed}")
    clips = [res.results[f"seg{s.index}"] for s in r.sb.segments]
    return {"clips": clips, "stages": {"draft": t_draft, "final": res.wall_seconds, "total": time.time() - t0},
            "gpus": len(endpoints), "timeline": [e.__dict__ for e in res.timeline]}


STRATEGIES = {
    "sequential": sequential,
    "parallel": parallel_keyframes,
    "draft-parallel": draft_then_parallel,
}


def finish(result: dict, workdir: Path, name: str, usd_per_gpu_hour: float, crossfade: float,
           cold_start_seconds: float = 240) -> dict:
    film = media.stitch(result["clips"], workdir / f"{name}.mp4", crossfade=crossfade)
    total = result["stages"]["total"]
    report = {
        "strategy": name,
        "gpus": result["gpus"],
        "film": str(film),
        "film_seconds": round(media.duration(film), 2),
        "wall_seconds": round(total, 1),
        "stages": {k: round(v, 1) for k, v in result["stages"].items()},
        # Nodes bill from cold start, so more GPUs cost more than their render time.
        "est_cost_usd": round((total + cold_start_seconds) / 3600 * result["gpus"] * usd_per_gpu_hour, 4),
        "seams": media.seam_report(result["clips"]),
        "timeline": result.get("timeline", []),
    }
    (workdir / f"{name}.report.json").write_text(json.dumps(report, indent=2, default=str))
    return report
