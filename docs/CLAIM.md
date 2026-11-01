# Nosana credit claim: draft answers

Form: <https://decentralizeai.tech/claim/nosana>

## 01 Project Information

**Project Name**
ShotFarm

**GitHub Repository URL**
https://github.com/nice-bills/shotfarm

**Proposal Description**

ShotFarm is an open-source render farm for long-form AI video on Nosana's decentralized GPU network.

The problem: MiniMax H3, the open-weight audiovisual model Nosana added in August 2026, generates video with native sound, but only 4-15 seconds per generation, and a 5-second clip takes about 2 minutes on an RTX 5090. Every existing way to make longer H3 videos (H3-Motion-Context / Endless MiniMax H3, Wan2GP's sliding window, the vLLM-Omni long-video work in issue #6737) is sequential: each window waits for the tail of the previous one. A one-minute film becomes a ~25-minute queue on a single GPU, no matter how many GPUs exist.

ShotFarm makes long-form generation parallel. A film is planned as a storyboard of segments, each pinned between two keyframes. Because each segment is pinned at both ends, segments are independent and can render at the same time on many Nosana GPUs. A scheduler fans the work out across N Nosana deployments, retries failed jobs on other nodes, and stitches the clips back into one film with sound. The goal is a one-minute film in roughly the time of one segment plus overhead instead of 12 segments back to back.

The hard part is quality at the joins. Naive keyframe pinning makes each clip start from zero velocity, so motion stalls at the seams, and each clip's audio starts fresh. ShotFarm's method, draft-then-parallel, renders a cheap low-resolution sequential "animatic" first to fix motion and sound for the whole film, then renders the expensive final pass in parallel, pinned to frames sliced from the animatic and conditioned on the animatic's audio just before each join. This mirrors how film studios work: animatic first, final frames on the render farm.

The project is built to be measured, not just demoed. It implements three strategies (sequential baseline, parallel keyframes, draft-then-parallel) and every run reports wall-clock time per stage, cost, a per-GPU timeline, and seam metrics for every join (a video-jump ratio and the audio RMS jump in dB, the same audio metric used in the vLLM-Omni H3 work).

Current status: the orchestrator, scheduler with failover, stitching and seam metrics are implemented and pass end-to-end tests against mock GPU nodes. The Nosana credits will fund the first real runs and the full experiment: 30 s and 60 s films at 1, 2, 4 and 8 GPUs per strategy, plus measurements of cold starts and node failures on the decentralized grid.

Deliverables: the open-source repo with exported H3 ComfyUI workflows, a reusable job setup other Nosana builders can use for any GPU-heavy batch workload, sample films, and a HackerNoon article publishing the speedup curves, cost per finished minute, and seam-quality results, including where the approach falls short.

Why it matters for decentralized AI: a single long render is only as fast as one GPU, but a decentralized GPU market lets anyone rent eight GPUs for ten minutes for less than a dollar. ShotFarm turns that elasticity into a real capability (minutes instead of half an hour for a film with sound) on open weights and open infrastructure.

**Model / Workload Details**

Model: MiniMax H3 (open weights, MiniMax H3 Community License), via Nosana's MiniMax H3 ComfyUI template. Modes: I2VA (draft and sequential baseline), FL2VA and Ref2VA (parallel final pass with first/last frame and reference audio). Keyframe images from an open text-to-image model (e.g. FLUX.1 schnell) on the same nodes.

Hardware: RTX 5090 (Nosana's recommended GPU for H3), falling back to RTX PRO 6000 if 5090 supply is short. One H3 deployment per GPU, Simple strategy, replicas = 1, fixed timeouts, stopped right after each run.

Workload: batch generation of 5-second, 768p, 24 fps clips with 32 kHz stereo audio, fanned out across 1-8 concurrent deployments. Nosana's published figure is about 2 minutes and $0.013 per 5-second clip on a 5090 (~$0.40/GPU-hour), plus ~4 minutes of cold start per node.

Experiment matrix: 3 strategies x 4 GPU counts (1, 2, 4, 8) x 2 film lengths (30 s, 60 s), with repeats and failure tests. Estimated 40-80 GPU-hours including cold starts, failed runs and the parallel H3 final passes, which is within the $70 credit.

## 02 Nosana Deployment Commitment
Yes

## 03 Team Information
Team Members: *(your name, role: e.g. "Name, builder")*
Social Links: https://github.com/nice-bills *(add X / LinkedIn / HackerNoon profile)*

## 04 Contact Information
Email, phone, country: *(fill in yourself)*

## 05 Agreement
Tick it yourself; it confirms the information is accurate and that you are the only person claiming for the team.
