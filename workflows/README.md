# Workflow templates

ShotFarm drives ComfyUI through its API, so it needs your H3 workflows in **API format**.

1. Open ComfyUI on one of your Nosana H3 deployments (port 8188).
2. Build the graph by hand or import the community example below. **Do not use ComfyUI's bundled `api_minimax_h3_*` templates**: they call MiniMax's cloud API, not the weights on the node. The node graph is in the readme returned by `https://api.nosana.com/templates/minimax-h3-i2v-32gb`:
   `UNETLoader → LoraLoaderModelOnly → ModelSamplingMiniMaxH3 → KSampler → VAEDecode + VAEDecodeAudio → CreateVideo (24 fps) → SaveVideo`, conditioned by the `MiniMax H3 Image to Video` node.
3. Use `weight_dtype: default`, the 8-step turbo LoRA and cfg 1.0.
4. Settings → enable dev mode, then **Workflow → Export (API)**.
5. In the JSON, replace values with placeholders:

| Placeholder | Meaning |
|---|---|
| `{{PROMPT}}` | Segment prompt (ShotFarm appends the segment's audio description) |
| `{{SEED}}` | Per-segment seed |
| `{{FRAMES}}` | Frame count on H3's 17k+5 grid, for the node's `length` input. Always use this in `final`, whose length differs from the segment's |
| `{{SECONDS}}` | Segment length (4–15) |
| `{{WIDTH}}` `{{HEIGHT}}` | Output size, multiples of 32 |
| `{{FIRST_FRAME}}` | Uploaded first-frame image name (LoadImage node) |
| `{{LAST_FRAME}}` | Uploaded last-frame image name (fl2v / final) |
| `{{GUIDE_CLIP}}` | Uploaded 22-frame MP4 with sound (LoadVideo node; final only) |

A placeholder that is the entire value becomes a typed value (numbers stay numbers).

Files needed for each strategy:

- `sequential`: `image`, `i2v`
- `parallel`: `image`, `fl2v`
- `draft-parallel`: `image`, `draft`, `fl2v`, `final`

Every template must run on the **Image to Video variant**. The Nosana variants ship one diffusion model each (FL2VA or Ref2VA), so a Ref2VA `final` would need a second pool of nodes.

- `image`: the template has **no image model**. Use a 5-frame T2VA graph (`length` 5); ShotFarm extracts the first frame. Or add an image model to your own job definition.
- `draft`: same graph as `i2v` at lower `{{WIDTH}}`/`{{HEIGHT}}` values fixed in the JSON, such as 736x416 (0.3 MP).
- `final`: `LoadVideo {{GUIDE_CLIP}}` into `MiniMaxH3AddGuide` with `frame_idx` 0 for frames and audio, then a second `MiniMaxH3AddGuide` with `{{LAST_FRAME}}` at `frame_idx` -1, with `length` set to `{{FRAMES}}`. Node docs: <https://github.com/Comfy-Org/ComfyUI/pull/15439>. Its example workflow is `video_minimax_h3_r2v_addguides_v1.json`.

Run `python -m shotfarm check` after exporting. It reports any node a template needs that the deployment lacks.

Real exported templates will be committed here after the first Nosana run.
