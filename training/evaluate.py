"""CPU checkpoint evaluation using an explicit JSON scene manifest."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import time
from pathlib import Path
import numpy as np


def metrics(prediction, truth):
    prediction, truth = np.asarray(prediction, dtype=bool), np.asarray(truth, dtype=bool)
    if prediction.shape != truth.shape:
        raise ValueError('Prediction and truth shapes must match.')
    tp = int((prediction & truth).sum()); fp = int((prediction & ~truth).sum())
    fn = int((~prediction & truth).sum()); tn = int((~prediction & ~truth).sum())
    return from_counts(tp, fp, fn, tn)


def from_counts(tp, fp, fn, tn):
    def ratio(a, b): return a / b if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, dice=ratio(2*tp, 2*tp+fp+fn),
                iou=ratio(tp, tp+fp+fn), precision=ratio(tp, tp+fp), recall=ratio(tp, tp+fn),
                false_positive_rate=ratio(fp, fp+tn))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def evaluate(manifest, weights, output, threshold=.5):
    import torch
    import torch.nn.functional as functional
    from training.dataset import _read_image, _read_mask
    from training.model import build_unet
    if not 0 < threshold < 1: raise ValueError('Threshold must be between 0 and 1.')
    entries = json.loads(manifest.read_text())
    if not isinstance(entries, list) or not entries: raise ValueError('Manifest must be a nonempty scene list.')
    prepared, seen = [], set()
    for entry in entries:
        image = (manifest.parent / entry['image']).resolve()
        mask = (manifest.parent / entry['mask']).resolve()
        if entry.get('category') not in ('oil', 'no_oil', 'look_alike', 'unknown'):
            raise ValueError('Each scene needs category: oil, no_oil, look_alike, or unknown.')
        image_hash = sha(image)
        if image_hash in seen: raise ValueError('Duplicate image contents in evaluation manifest.')
        seen.add(image_hash)
        prepared.append((entry, image, mask, image_hash))
    torch.set_num_threads(2)
    checkpoint = torch.load(weights, map_location='cpu', weights_only=True)
    model = build_unet()
    model.load_state_dict(checkpoint['model_state_dict']); model.eval()
    with torch.inference_mode(): model(torch.zeros(1, 3, 256, 256))
    scenes = []
    for entry, image_path, mask_path, image_hash in prepared:
        image = _read_image(image_path); truth = _read_mask(mask_path)
        if image.shape[1:] != truth.shape: raise ValueError(f'Image/mask dimensions differ: {image_path.name}')
        if entry['category'] in ('no_oil', 'look_alike') and truth.any():
            raise ValueError('Negative scene category has positive ground-truth pixels.')
        image = functional.interpolate(torch.from_numpy(image)[None], size=(256,256), mode='bilinear', align_corners=False)
        truth = functional.interpolate(torch.from_numpy(truth)[None,None], size=(256,256), mode='nearest').numpy()[0,0] > 0
        started = time.perf_counter()
        with torch.inference_mode(): prediction = torch.sigmoid(model(image))[0,0].numpy() >= threshold
        elapsed = time.perf_counter() - started
        scenes.append(dict(scene=entry.get('id', image_path.stem), category=entry['category'], image_sha256=image_hash,
                           mask_sha256=sha(mask_path), inference_seconds=elapsed, **metrics(prediction, truth)))
    def summary(items):
        counts = {key: sum(item[key] for item in items) for key in ('tp','fp','fn','tn')}
        macro = {}
        for key in ('dice','iou','precision','recall','false_positive_rate'):
            values = [item[key] for item in items if item[key] is not None]
            macro[key] = sum(values)/len(values) if values else None
        return dict(scene_count=len(items), pooled_pixel_metrics=from_counts(**counts), macro_scene_metrics=macro)
    report = dict(checkpoint_sha256=sha(weights), manifest_sha256=sha(manifest), threshold=threshold,
                  hardware=platform.machine(), device='cpu', torch_version=str(torch.__version__), threads=2,
                  preprocessing='Training-compatible per-band 2nd–98th percentile normalization; 256x256 resized scenes; nearest-neighbor masks. Not tiled application inference.',
                  split_status='User-supplied manifest; training-set independence not verified.',
                  metric_policy='Undefined denominators are null and excluded from macro averages, including empty-empty Dice/IoU.',
                  timing='Warmed model forward pass and threshold only; excludes reads, preprocessing and checkpoint loading.',
                  overall=summary(scenes), categories={key: summary([item for item in scenes if item['category']==key]) for key in ('oil','no_oil','look_alike','unknown')}, scenes=scenes)
    output.mkdir(parents=True, exist_ok=True)
    (output/'segmentation-evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    def display(value): return 'Undefined' if value is None else f'{value:.4f}'
    lines = ['# Segmentation evaluation', '', report['split_status'], '', report['preprocessing'], '',
             '| Scene | Category | Dice | IoU | Precision | Recall | FPR | Seconds |', '|---|---|---|---|---|---|---|---|']
    lines += ['| '+' | '.join([item['scene'], item['category']]+[display(item[key]) for key in ('dice','iou','precision','recall','false_positive_rate','inference_seconds')])+' |' for item in scenes]
    lines += ['', report['metric_policy'], '', report['timing'], '', 'JSON includes pooled confusion counts, category summaries, checkpoint and evidence hashes. Missing categories have zero scenes and no accuracy estimate.']
    (output/'segmentation-evaluation.md').write_text('\n'.join(lines)+'\n')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--threshold', type=float, default=.5)
    args=parser.parse_args()
    result=evaluate(args.manifest,args.weights,args.output,args.threshold)
    print(json.dumps(result['overall'], indent=2))
