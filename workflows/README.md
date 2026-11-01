# Workflow templates

ShotFarm drives ComfyUI through its API, so it needs your H3 workflows in **API format**.

1. Open ComfyUI on one of your Nosana H3 deployments.
2. Load the built-in template (Templates → Video → MiniMax H3) for the mode you need: I2VA, FL2VA, or Ref2VA.
3. Settings → enable dev mode, then **Workflow → Export (API)**.
4. In the JSON, replace values with placeholders:

| Placeholder | Meaning |
|---|---|
| `{{PROMPT}}` | Segment prompt (ShotFarm appends the segment's audio description) |
| `{{SEED}}` | Per-segment seed |
| `{{SECONDS}}` | Segment length (4–15) |
| `{{WIDTH}}` `{{HEIGHT}}` | Output size |
| `{{FIRST_FRAME}}` | Uploaded first-frame image name (LoadImage node) |
| `{{LAST_FRAME}}` | Uploaded last-frame image name (FL2VA / final) |
| `{{REF_AUDIO}}` | Uploaded reference audio (Ref2VA / final, draft-parallel only) |

A placeholder that is the entire value becomes a typed value (numbers stay numbers).

Files needed for each strategy:

- `sequential`: `image`, `i2v`
- `parallel`: `image`, `fl2v`
- `draft-parallel`: `image`, `draft` (I2VA at low resolution / fewer steps / turbo LoRA), `final` (FL2VA + audio reference, or Ref2VA with first/last-frame images)

Real exported templates will be committed here after the first Nosana run.
