"""End-to-end tests against mock GPU nodes (no real GPUs needed).

    pytest -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shotfarm import media
from shotfarm.scheduler import Job, run_pool
from shotfarm.storyboard import load
from shotfarm.strategies import STRATEGIES, Renderer, Templates, finish
from shotfarm.workflow import fill, placeholders
from tests.mock_node import MockNode

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "tests" / "templates"
TEMPLATES = Templates(image=str(T / "image.json"), i2v=str(T / "i2v.json"), fl2v=str(T / "fl2v.json"),
                      draft=str(T / "i2v.json"), final=str(T / "final.json"))
RENDER = 0.6  # seconds per mock job


@pytest.fixture
def nodes():
    ns = [MockNode(render_seconds=RENDER) for _ in range(6)]
    yield ns
    for n in ns:
        n.close()


def test_fill_keeps_types():
    wf = fill({"a": "{{SEED}}", "b": "x {{PROMPT}} y", "c": ["{{SECONDS}}"]},
              {"SEED": 7, "PROMPT": "hi", "SECONDS": 5.0})
    assert wf == {"a": 7, "b": "x hi y", "c": [5.0]}
    assert placeholders({"a": "{{SEED}} {{X}}"}) == {"SEED", "X"}


def test_storyboard_validates():
    sb = load(ROOT / "examples" / "storyboard.yaml")
    assert len(sb.keyframes) == len(sb.segments) + 1
    assert sb.total_seconds == 30


def test_pool_retries_on_another_node():
    bad, good = MockNode(fail_first=99), MockNode()
    try:
        from shotfarm.comfy import ComfyClient
        jobs = [Job(f"j{i}", lambda ep: ComfyClient(ep).queue({"meta": {"kind": "image"}})) for i in range(4)]
        res = run_pool(jobs, [bad.url, good.url], log=lambda *_: None)
        assert not res.failed and len(res.results) == 4
        assert any(not e.ok for e in res.timeline)  # the bad node really failed
    finally:
        bad.close()
        good.close()


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_strategies_end_to_end(strategy, nodes, tmp_path):
    sb = load(ROOT / "examples" / "storyboard.yaml")
    r = Renderer(sb, TEMPLATES, tmp_path)
    result = STRATEGIES[strategy](r, [n.url for n in nodes], log=lambda *_: None)
    rep = finish(result, tmp_path, strategy, usd_per_gpu_hour=0.40, crossfade=0.0)
    assert abs(rep["film_seconds"] - 30) < 0.5
    assert len(rep["seams"]) == len(sb.segments) - 1
    assert json.loads((tmp_path / f"{strategy}.report.json").read_text())["strategy"] == strategy


def test_parallel_is_faster_than_sequential(nodes, tmp_path):
    sb = load(ROOT / "examples" / "storyboard.yaml")
    urls = [n.url for n in nodes]
    seq = STRATEGIES["sequential"](Renderer(sb, TEMPLATES, tmp_path / "s"), urls, log=lambda *_: None)
    sb = load(ROOT / "examples" / "storyboard.yaml")
    par = STRATEGIES["parallel"](Renderer(sb, TEMPLATES, tmp_path / "p"), urls, log=lambda *_: None)
    # 6 segments + 1 keyframe serial vs ~2 parallel waves (7 keyframes on 6 nodes) + 1 wave.
    assert par["stages"]["total"] < seq["stages"]["total"] / 1.8


def test_crossfade_stitch(nodes, tmp_path):
    sb = load(ROOT / "examples" / "storyboard.yaml")
    res = STRATEGIES["parallel"](Renderer(sb, TEMPLATES, tmp_path), [n.url for n in nodes], log=lambda *_: None)
    film = media.stitch(res["clips"], tmp_path / "xf.mp4", crossfade=0.5)
    assert abs(media.duration(film) - (30 - 5 * 0.5)) < 0.5
