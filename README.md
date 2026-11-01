# ShotFarm

**A render farm for open AI video on Nosana's decentralized GPU network.**

MiniMax H3 (open weights, August 2026) generates video *with native sound*, but only 4–15 seconds at a time, and a 5-second clip takes about 2 minutes on an RTX 5090. Today every long-video method for H3 is **sequential**: each window waits for the tail of the previous one. A one-minute film becomes a ~25-minute queue on a single GPU.

ShotFarm makes long-form generation **parallel**. It plans the film first, then renders every shot at the same time on as many Nosana GPUs as you rent, and stitches them back into one continuous film with sound.

> Old idea, new model: Disney split animation into *key animators* (draw the important poses) and *in-betweeners* (draw everything between them) in the 1930s, and Pixar render farms split films into shots that render in parallel. H3's first-and-last-frame mode is an in-betweener. Nosana is the render farm.

Built for the [Decentralize AI Hackathon](https://decentralizeai.tech) (HackerNoon × Nosana × Arweave × MEXC), Round 2.

---

## How it works

```
storyboard.yaml ──► keyframes (parallel) ──► segments pinned between keyframes (parallel) ──► stitch ──► film.mp4
                         GPU 1..N                         GPU 1..N
```

A film is a list of segments; segment *i* runs from keyframe *i* to keyframe *i+1*. Because every segment is pinned at both ends, no segment depends on another, so they can all render at once.

Three strategies are implemented so we can **measure** the trade-off rather than claim it:

| Strategy | What it does | Wall-clock (N segments, N GPUs) | Known risk |
|---|---|---|---|
| `sequential` | Baseline / prior art: each segment starts from the previous one's last frame | ≈ N × one segment | Drift accumulates ("photocopy effect") |
| `parallel` | Keyframe images first, then every segment pinned between two keyframes | ≈ 1 image + 1 segment | Motion can stall at joins (each clip starts at zero velocity) |
| `draft-parallel` | **ShotFarm's method.** A cheap low-res sequential *animatic* fixes motion and sound; the expensive final pass renders all segments in parallel, each guided by a 22-frame clip of the animatic's picture and sound before its join and pinned to its frame at the next join | ≈ cheap draft + 1 segment | Draft pass is serial (Amdahl's law) |

Every run writes a report: wall-clock per stage, estimated cost, a per-GPU timeline, and **seam metrics** for every join:

- `video_jump`: pixel change across the join ÷ median frame-to-frame change inside the clips (≈1 smooth, ≫1 visible cut, ≪1 freeze)
- `audio_jump_db`: RMS level after the join minus before (the same metric the vLLM-Omni team used for H3 long-video work, [issue #6737](https://github.com/vllm-project/vllm-omni/issues/6737))

## Status

**Pre-alpha.** The orchestrator, scheduler (with retry and node failover), stitcher and seam metrics are implemented and tested end to end against mock GPU nodes (`pytest -q`). **Not yet run on real Nosana GPUs**: that is the next milestone, using the hackathon's Nosana credits.

## Quick start

```bash
pip install -r requirements.txt
pytest -q                                   # runs the whole pipeline on mock GPU nodes

# 1. Deploy N copies of Nosana's MiniMax H3 template (see nosana/README.md)
# 2. Export your ComfyUI H3 workflows in API format with placeholders (see workflows/README.md)
cp farm.example.yaml farm.yaml              # paste your Nosana service URLs
python -m shotfarm check  --farm farm.yaml
python -m shotfarm render examples/storyboard.yaml --strategy draft-parallel
python -m shotfarm render examples/storyboard.yaml --strategy sequential --gpus 1   # baseline
```

## Experiment plan (what the HackerNoon write-up will report)

1. **Speedup curve:** 30 s and 60 s films at 1, 2, 4 and 8 GPUs for each strategy. Wall-clock, cost per finished minute, GPU utilisation.
2. **Seam quality:** `video_jump` and `audio_jump_db` per join, plus a blind A/B of the three strategies by viewers.
3. **Decentralization in practice:** cold-start times, node failures and retries across Nosana's grid, and what they do to the tail latency of a film.
4. **Cost:** dollars per finished minute vs. the same work on a single rented GPU.

## Prior art and how this differs

- [H3-Motion-Context / Endless MiniMax H3](https://comfyui-wiki.com/en/news/2026-09-03-endless-minimax-h3): unlimited-length, seamless, but sequential (1:30 of video in ~2 h on one GPU).
- [vLLM-Omni #6737](https://github.com/vllm-project/vllm-omni/issues/6737) and Wan2GP: server-side sliding-window continuation; sequential windows on one machine.
- [Generating Long-Take Videos via Effective Keyframes and Guidance (WACV 2025)](https://openaccess.thecvf.com/content/WACV2025/papers/Huang_Generating_Long-Take_Videos_via_Effective_Keyframes_and_Guidance_WACV_2025_paper.pdf): keyframes as first/last frames of short clips; the academic basis for the `parallel` strategy.

ShotFarm's contribution is the **systems layer**: distributing segments across a decentralized GPU grid, the draft-then-parallel method that targets the motion-stall and audio-seam problems of naive keyframe pinning, and published measurements of the speed/quality/cost trade-off.

## Layout

```
shotfarm/storyboard.py   shot plan + validation (H3's 4–15 s window)
shotfarm/comfy.py        stdlib ComfyUI API client
shotfarm/workflow.py     fill API-format workflow templates
shotfarm/scheduler.py    work-stealing pool over GPU endpoints, retries, timeline
shotfarm/strategies.py   sequential / parallel / draft-parallel
shotfarm/media.py        ffmpeg stitching (hard cut or crossfade) + seam metrics
tests/                   mock ComfyUI node + end-to-end tests
```

## License

MIT for this code. MiniMax H3 weights are under the MiniMax H3 Community License; check it for your region and use case.
