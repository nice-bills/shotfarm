# CLAUDE.md: ShotFarm project context

Read this first. It brings any Claude Code session up to speed on the project.

## What this is

ShotFarm is our entry for the **Decentralize AI Hackathon** (HackerNoon × Nosana × Arweave × MEXC), **Round 2: Nov 2026 – Feb 2027**. Site: https://decentralizeai.tech

- The entry itself is a **HackerNoon blog post** tagged `decentralize-ai-hackathon` (plus e.g. `gpu-cloud`, `ai-compute`, `ai-infrastructure`). The code is the evidence behind it.
- FAQ rule: mockups and demo-less prototypes are **not eligible for prizes**. We need working code, a deployment, and reproducible metrics.
- Judging rubric (decentralizeai.tech/judges): deep technical understanding, novel insights, real-world impact, research & evidence (cite specific projects/papers/people), clear communication.
- Judges include Sjoerd Dijkstra (Nosana co-founder), David Smooke (HackerNoon CEO), Ojus Save (Render DevRel), Valeria Kholostenko (Decentralized Storage Alliance).
- Target prize: **Nosana winner reward** ($450 compute credits × 15 winners). Every eligible participant also gets $70 in Nosana credits via https://decentralizeai.tech/claim/nosana (answers drafted in `docs/CLAIM.md`).
- Competition is thin: about 39 tagged posts by Nov 1 2026.

## The idea (one line)

A render farm for long-form open AI video: render every shot of a film **at the same time** on many Nosana GPUs, instead of one clip after another.

## Why it's new

- **MiniMax H3** (open weights, Aug 2026) generates video with native 32 kHz stereo audio, 4–15 s per generation, 768p, 24 fps. On Nosana an RTX 5090 renders a 5 s clip in about 2 min (~$0.013/clip, ~$0.40/GPU-hr, ~4 min cold start). Source: https://nosana.com/blog/how-to-use-minimax-h3
- Every existing long-video method for H3 is **sequential**: each window is conditioned on the previous window's tail.
  - H3-Motion-Context / Endless MiniMax H3: https://comfyui-wiki.com/en/news/2026-09-03-endless-minimax-h3 (1:30 of video in ~2 h on one GPU)
  - Wan2GP sliding window, vLLM-Omni #6737 / #7838: https://github.com/vllm-project/vllm-omni/issues/6737 (has audio RMS-jump measurements we reuse as a metric)
  - Reddit thread on H3 clip chaining (r/StableDiffusion "Clip chaining for MiniMax H3"). User DeliciousGorilla found that pinning both ends of each clip (parallelizable) causes **motion stalls at the joins**, because each clip starts at zero velocity. That's the problem our draft-then-parallel method targets.
  - Academic basis for keyframe pinning: "Generating Long-Take Videos via Effective Keyframes and Guidance" (WACV 2025).
- Our contribution is the systems layer: distributing segments across a decentralized grid, plus **draft-then-parallel**. First a cheap low-res sequential animatic fixes motion and sound. Then the expensive final pass renders all segments in parallel, pinned to frames sliced from the animatic, with the animatic's audio just before each join passed as a Ref2VA audio reference.
- Pitch hook: Disney key animators vs in-betweeners (1930s) and Pixar render farms. H3's first+last-frame mode is the in-betweener; Nosana is the render farm.

## Ideas we killed (don't revisit)

| Idea | Why |
|---|---|
| Verifiable AI receipts on Arweave | Already entered: hackernoon.com/verifiable-ai-needs-receipts-not-confidence-scores |
| Agent orchestrator for decentralized GPUs | Already entered: hackernoon.com/building-an-ai-agent-orchestrator-for-decentralized-gpu-compute |
| Live AI FMV / choose-your-own-adventure video game | Prior art (Seedance FMV, Runway Game Worlds); 2 min per clip means it can't be played live |
| Twi / African-language voice AI | Nosana already featured Geneline-X (Mar 2026) |
| Self-hosted LLM cost comparison | Nosana has published this themselves; not new |
| Animate old photos with sound | MyHeritage Deep Nostalgia (2021) |
| Generic agents / RAG / code review / trading bots | On Nosana's own published idea list, so this is what everyone builds |

Rule from the hackathon-filter process: **one sponsor at the centre (Nosana)**. Don't bolt on Arweave or MEXC just to improve the odds.

## Repo layout

```
shotfarm/storyboard.py   Storyboard/Segment; validates H3's 4-15 s window; keyframes = segments + 1
shotfarm/comfy.py        stdlib ComfyUI client: upload, /prompt, /history poll, /view download
shotfarm/workflow.py     fills API-format workflow JSON placeholders ({{PROMPT}}, {{FIRST_FRAME}}, ...)
shotfarm/scheduler.py    one worker thread per endpoint, shared queue, retries on other nodes, drops dead nodes, timeline
shotfarm/strategies.py   sequential | parallel | draft-parallel, plus finish() -> report JSON
shotfarm/media.py        ffmpeg: frame/audio extraction, stitch (hard cut or xfade), seam_report()
shotfarm/cli.py          python -m shotfarm check|render|seams
tests/mock_node.py       fake ComfyUI node that renders real MP4/PNG with ffmpeg after a delay
tests/test_farm.py       8 end-to-end tests (all pass, ~2 min)
examples/storyboard.yaml 30 s, 6-segment test film
nosana/README.md         how to deploy the H3 template on Nosana + budget
workflows/README.md      how to export ComfyUI workflows with placeholders
docs/CLAIM.md            Nosana credit claim form answers
```

Only dependencies are numpy, PyYAML and pytest, plus `ffmpeg`/`ffprobe` on PATH. Run `pytest -q`.

Seam metrics: `video_jump` = pixel change across the join ÷ median in-clip frame change (≈1 smooth, ≫1 visible cut, ≪1 freeze). `audio_jump_db` = RMS level after the join minus before.

## Status (Nov 1 2026)

- [x] Event vetted, idea chosen, prior-art check done
- [x] Orchestrator + scheduler + 3 strategies + stitching + metrics, tested on mock nodes
- [x] Claim answers drafted (`docs/CLAIM.md`)
- [ ] **Submit the Nosana credit claim** (the user does this; it needs their phone number and agreement)
- [ ] Get the credits, deploy the H3 template on Nosana (RTX 5090, Simple strategy, replicas 1, fixed timeout; template link in nosana/README.md)
- [ ] Export real ComfyUI API workflows into `workflows/` (image, i2v, fl2v, draft, final) and replace values with placeholders
- [ ] First real run: `sequential --gpus 1` vs `parallel` vs `draft-parallel` on the 30 s storyboard
- [ ] Full matrix: 3 strategies × {1, 2, 4, 8} GPUs × {30 s, 60 s}, with repeats. Record cold starts and failures
- [ ] Charts: speedup curve, cost per finished minute, seam metrics, GPU timeline (Gantt)
- [ ] Blind A/B of seams between strategies
- [ ] Write and publish the HackerNoon post, including where the method falls short
- [ ] Optional follow-up post on how the Nosana credits were used (separate $450 × 15 prize; tags: GPU Marketplace / GPU Cloud / AI Compute / AI Infrastructure)

## Known risks / open questions

- The real H3 ComfyUI node names and inputs are unverified. The templates in `tests/templates/` are mocks with a fake top-level `"meta"` key that real workflows don't have.
- Does FL2VA accept reference audio? The vLLM-Omni work says FL2VA has no audio slot, and continuation audio only works through the **Ref2VA** packer. So the `final` template should probably be Ref2VA with the first/last images as references plus the audio tail.
- The draft pass is serial (Amdahl). Measure how much faster a low-res/turbo-LoRA draft really is.
- Nosana said in Sept 2026 that RTX 4090/5090 demand exceeds supply, so 8 × 5090 at once may not be available. RTX PRO 6000 is the fallback.
- Always stop Nosana deployments right after each run to save credits. The default "Infinite" strategy restarts forever.
- MiniMax H3 Community License: check regional/commercial terms.

## Working conventions

- Be honest in README/blog about what has and hasn't been run on real GPUs.
- Never commit `farm.yaml` (it holds endpoint URLs); it's gitignored.
- Reports go to `out/<strategy>/<strategy>.report.json` (gitignored).
