# SeaScan training workspace

Phase 2 adds the oil-spill segmentation architecture, real dataset adapter, training loop, and inference workflow here.

## Detailed checkpoint evaluation (Step 10)

Create a JSON manifest with explicit pairs. Relative paths resolve against the manifest directory:

```json
[
  {"id": "scene-01", "image": "images/scene-01.png", "mask": "masks/scene-01.png", "category": "oil"}
]
```

Allowed categories: `oil`, `no_oil`, `look_alike`, `unknown`. Masks are binary (nonzero means oil); negative categories must have empty masks. Duplicate image contents and mismatched image/mask dimensions are rejected. Mask alignment must be verified by the operator; matching dimensions alone do not establish geographic alignment.

From the project root:

```bash
backend/.venv-local/bin/python -m training.evaluate --manifest evaluation-scenes.json --weights backend/models/seascan_unet.pt --output output/segmentation-evaluation
```

Outputs: per-scene Markdown and detailed JSON with Dice, IoU, precision, recall, pixel false-positive rate, confusion counts, macro and pooled metrics, category summaries, inference timing, hardware architecture, and hashes. Undefined metrics are null, not perfect scores. Categories absent from the manifest receive no accuracy estimate.

This CPU evaluator reproduces the training-style 256×256 scene resize. It does not evaluate the application's newer full-resolution tiled inference. It reads one whole source image at a time; use modest-size scenes on an 8 GB laptop. No retraining or dataset downloads occur. Timing excludes image loading and preprocessing.

The operator must provide a genuinely held-out scene manifest and check overlap with training/validation scenes before describing results as independent test accuracy. The bundled demo is only a smoke test and may overlap training data. Choose the threshold on validation data and keep it fixed for the test set. No training-split independence is inferred by this tool.
