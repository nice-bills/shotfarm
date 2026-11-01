"""End-to-end tests against mock GPU nodes (no real GPUs needed).

    pytest -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shotfarm import media
from shotfarm.comfy import ComfyClient, ComfyError
from shotfarm.scheduler import Job, run_pool
from shotfarm.storyboard import frames_for, load
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


def test_frames_snap_to_h3_grid():
    assert [frames_for(s) for s in (5, 10, 15)] == [124, 243, 362]


def test_storyboard_rejects_size_h3_cannot_render():
    sb = load(ROOT / "examples" / "storyboard.yaml")
    sb.height = 720
    with pytest.raises(ValueError):
        sb.validate()


def test_missing_nodes_reported():
    node = MockNode()
    try:
        assert ComfyClient(node.url).missing_nodes({"TextEncode", "MiniMaxH3AddGuide"}) == {"MiniMaxH3AddGuide"}
    finally:
        node.close()


def test_rejected_workflow_explains_why():
    node = MockNode(fail_first=1)
    try:
        with pytest.raises(ComfyError, match="simulated node failure"):
            ComfyClient(node.url).queue({"meta": {}})
    finally:
        node.close()


def test_wait_survives_network_blip(monkeypatch):
    c, calls = ComfyClient("http://unused"), []

    def flaky(path):
        calls.append(path)
        if len(calls) < 3:
            raise OSError("connection reset")
        return b'{"p": {"status": {}, "outputs": {"9": {}}}}'

    monkeypatch.setattr(c, "_get", flaky)
    assert c.wait("p", poll=0) == {"9": {}}


def test_keyframe_from_video_only_node(tmp_path):
    t = tmp_path / "t2va.json"
    t.write_text('{"meta": {"kind": "video", "seed": "{{SEED}}", "seconds": 1}}')
    sb = load(ROOT / "examples" / "storyboard.yaml")
    node = MockNode(render_seconds=0)
    try:
        out = Renderer(sb, Templates(image=str(t)), tmp_path).keyframe(node.url, 0)
    finally:
        node.close()
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_draft_parallel_guides_segments_and_cuts_the_guide(nodes, tmp_path):
    sb = load(ROOT / "examples" / "storyboard.yaml")
    res = STRATEGIES["draft-parallel"](Renderer(sb, TEMPLATES, tmp_path), [n.url for n in nodes], log=lambda *_: None)
    assert sb.segments[0].guide_clip is None and sb.segments[0].frames == 124
    assert sb.segments[1].frames == 141 and (141 - 5) % 17 == 0
    assert abs(media.duration(sb.segments[1].guide_clip) - 22 / 24) < 0.1
    assert abs(media.duration(res["clips"][1]) - 119 / 24) < 0.1


def test_pool_retries_on_another_node():
    bad, good = MockNode(fail_first=99), MockNode()
    try:
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
