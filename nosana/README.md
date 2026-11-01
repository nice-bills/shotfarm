# Running the farm on Nosana

ShotFarm only needs a list of ComfyUI endpoints. On Nosana, each endpoint is a deployment of the official **MiniMax H3** template.

## Deploy

1. Open the template: <https://deploy.nosana.com/deployments/create/?template=minimax-h3-i2v-32gb>
2. GPU: **RTX 5090** (recommended by Nosana for H3) or RTX PRO 6000.
3. Strategy: **Simple**, replicas = 1 per deployment, and a timeout that fits the experiment (e.g. 1–2 h). The default "Infinite" strategy restarts forever and burns credits.
4. Repeat for as many GPUs as the experiment needs (1, 2, 4, 8).
5. Copy each deployment's **Service URL** into `farm.yaml`.
6. `python -m shotfarm check --farm farm.yaml` and wait until all nodes are UP. Cold start is ~4 minutes.

You can also do this from an AI assistant with the [Nosana MCP server](https://learn.nosana.com/mcp/intro) ("deploy 4 MiniMax H3 instances on RTX 5090 with a 2 hour timeout").

## Budget

Nosana's published figure is ~2 minutes and ~$0.013 per 5-second H3 clip on an RTX 5090 (about $0.40/GPU-hour). A 60-second film is 12 five-second segments:

| Run | GPU-hours (incl. ~4 min cold start per node) | Approx. cost |
|---|---|---|
| sequential, 1 GPU | ~0.5 | ~$0.20 |
| parallel, 8 GPUs | ~8 × 0.15 | ~$0.50 |

The full experiment matrix (3 strategies × 4 GPU counts × 2 film lengths, with repeats) fits comfortably inside the $70 hackathon credit. **Stop deployments as soon as a run finishes.**

## Supply note

Nosana reported in September 2026 that RTX 4090/5090 demand exceeds supply. If 8 × 5090 are not available at once, the scheduler works with whatever mix of nodes is up; the report records which nodes did what.
