"""Storyboard: the shot plan that makes long-form generation parallel.

A film is a list of segments. Segment i runs from keyframe i to keyframe i+1.
Because every segment is pinned at both ends, segments do not depend on each
other and can render at the same time on different GPUs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml


def frames_for(seconds: float, fps: int = 24) -> int:
    """H3 snaps frame counts up to its 17k+5 grid: 5 s is 124 frames, 15 s is 362."""
    return 17 * math.ceil((seconds * fps - 5) / 17) + 5


@dataclass
class Segment:
    index: int
    prompt: str
    seconds: float
    audio: str = ""          # what we should hear in this segment
    seed: int = 0
    first_frame: str | None = None   # local path, filled by the keyframe stage
    last_frame: str | None = None
    guide_clip: str | None = None    # local path, filled by draft-then-parallel
    frames: int | None = None        # generated length, if not frames_for(seconds)
    output: str | None = None        # local path of the rendered clip

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Storyboard:
    title: str
    style: str
    keyframes: list[str]          # prompts for keyframe images, len = segments + 1
    segments: list[Segment] = field(default_factory=list)
    width: int = 1280
    height: int = 768
    fps: int = 24

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.segments)

    def validate(self) -> None:
        if len(self.keyframes) != len(self.segments) + 1:
            raise ValueError(
                f"need {len(self.segments) + 1} keyframes for {len(self.segments)} "
                f"segments, got {len(self.keyframes)}"
            )
        if self.width % 32 or self.height % 32:
            raise ValueError(f"{self.width}x{self.height}: H3 width and height must be multiples of 32")
        for s in self.segments:
            # MiniMax H3's native contract is 4-15 s per generation.
            if not 4 <= s.seconds <= 15:
                raise ValueError(f"segment {s.index}: {s.seconds}s is outside H3's 4-15s window")


def load(path: str | Path) -> Storyboard:
    raw = yaml.safe_load(Path(path).read_text())
    style = raw.get("style", "")
    segs = []
    for i, s in enumerate(raw["segments"]):
        segs.append(
            Segment(
                index=i,
                prompt=f"{s['prompt']} {style}".strip(),
                seconds=float(s.get("seconds", 5)),
                audio=s.get("audio", ""),
                seed=int(s.get("seed", raw.get("seed", 42) + i)),
            )
        )
    sb = Storyboard(
        title=raw["title"],
        style=style,
        keyframes=[f"{k} {style}".strip() for k in raw["keyframes"]],
        segments=segs,
        width=int(raw.get("width", 1280)),
        height=int(raw.get("height", 768)),
        fps=int(raw.get("fps", 24)),
    )
    sb.validate()
    return sb
