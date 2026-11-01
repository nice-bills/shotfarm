"""ShotFarm command line.

    python -m shotfarm render examples/storyboard.yaml --farm farm.yaml --strategy draft-parallel
    python -m shotfarm check --farm farm.yaml
    python -m shotfarm seams out/a.mp4 out/b.mp4 ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import media
from .comfy import ComfyClient
from .storyboard import load
from .strategies import STRATEGIES, Renderer, Templates, finish


def _farm(path: str) -> dict:
    cfg = yaml.safe_load(Path(path).read_text())
    if not cfg.get("endpoints"):
        sys.exit("farm config has no endpoints: add your Nosana service URLs")
    return cfg


def cmd_check(a):
    cfg = _farm(a.farm)
    ok = 0
    for ep in cfg["endpoints"]:
        h = ComfyClient(ep, timeout=10).healthy()
        ok += h
        print(f"{'UP  ' if h else 'DOWN'} {ep}")
    print(f"{ok}/{len(cfg['endpoints'])} nodes healthy")


def cmd_render(a):
    cfg = _farm(a.farm)
    sb = load(a.storyboard)
    endpoints = cfg["endpoints"][: a.gpus] if a.gpus else cfg["endpoints"]
    work = Path(a.out) / a.strategy
    work.mkdir(parents=True, exist_ok=True)
    print(f"'{sb.title}': {len(sb.segments)} segments, {sb.total_seconds:.0f}s of film, "
          f"{len(endpoints)} GPU(s), strategy={a.strategy}")
    r = Renderer(sb, Templates(**cfg.get("templates", {})), work)
    result = STRATEGIES[a.strategy](r, endpoints)
    rep = finish(result, work, a.strategy, float(cfg.get("usd_per_gpu_hour", 0.40)), a.crossfade)
    rep.pop("timeline")
    print(json.dumps(rep, indent=2))


def cmd_seams(a):
    print(json.dumps(media.seam_report(a.clips), indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="shotfarm", description="Parallel long-form AI video on Nosana GPUs")
    sub = p.add_subparsers(required=True)

    c = sub.add_parser("check", help="ping every node in the farm")
    c.add_argument("--farm", default="farm.yaml")
    c.set_defaults(fn=cmd_check)

    r = sub.add_parser("render", help="render a storyboard")
    r.add_argument("storyboard")
    r.add_argument("--farm", default="farm.yaml")
    r.add_argument("--strategy", choices=list(STRATEGIES), default="draft-parallel")
    r.add_argument("--gpus", type=int, default=0, help="use only the first N endpoints")
    r.add_argument("--crossfade", type=float, default=0.0, help="seconds of dissolve at each join (0 = hard cut)")
    r.add_argument("--out", default="out")
    r.set_defaults(fn=cmd_render)

    s = sub.add_parser("seams", help="measure join quality between consecutive clips")
    s.add_argument("clips", nargs="+")
    s.set_defaults(fn=cmd_seams)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
