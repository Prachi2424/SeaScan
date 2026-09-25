"""Cloud training pipeline for all three official Sentinel-1 dataset parts.

Large archives are processed one at a time on ephemeral Colab/Kaggle disk.
Parts I and II provide scene-level train/validation data. Part III is reserved
for one final independent evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.request import urlretrieve

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.ml.unet import build_unet  # noqa: E402


PART_I = "https://zenodo.org/records/8346860/files"
PART_II = "https://zenodo.org/records/8253899/files"
PART_III = "https://zenodo.org/records/13761290/files"

TRAIN_ARCHIVES = (
    {
        "category": "oil",
        "expected": 1200,
        "images": f"{PART_I}/01_Train_Val_Oil_Spill_images.7z?download=1",
        "masks": f"{PART_I}/01_Train_Val_Oil_Spill_mask.7z?download=1",
    },
    {
        "category": "no_oil",
        "expected": 685,
        "images": f"{PART_II}/01_Train_Val_No_Oil_Images.7z?download=1",
        "masks": f"{PART_II}/01_Train_Val_No_Oil_mask.7z?download=1",
    },
    {
        "category": "lookalike",
        "expected": 685,
        "images": f"{PART_II}/01_Train_Val_Lookalike_images.7z?download=1",
        "masks": f"{PART_II}/01_Train_Val_Lookalike_mask.7z?download=1",
    },
)

TEST_ARCHIVE = {
    "url": f"{PART_III}/02_Test_images_and_ground_truth.7z?download=1",
    "expected": {"oil": 150, "no_oil": 150, "lookalike": 150},
}

RASTER_SUFFIXES = {".tif", ".tiff"}
PREPROCESS_SIZE = 512
MODEL_TILE_SIZE = 256


def command(arguments: list[str]) -> None:
    print("+", " ".join(arguments), flush=True)
    subprocess.run(arguments, check=True)


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    aria_marker = destination.with_name(f"{destination.name}.aria2")
    if destination.exists() and destination.stat().st_size > 0 and not aria_marker.exists():
        print(f"Reusing {destination.name} ({destination.stat().st_size / 2**30:.2f} GiB)")
        return
    if shutil.which("aria2c"):
        command([
            "aria2c", "--continue=true", "--max-connection-per-server=16",
            "--split=16", "--min-split-size=10M", "--file-allocation=none",
            "--dir", str(destination.parent), "--out", destination.name, url,
        ])
    else:
        print(f"Downloading {url}")
        urlretrieve(url, destination)


def extract(archive: Path, destination: Path) -> None:
    if not shutil.which("7z"):
        raise RuntimeError("7z is required. In Colab run: apt-get install -y p7zip-full")
    destination.mkdir(parents=True, exist_ok=True)
    command(["7z", "x", "-y", str(archive), f"-o{destination}"])


def raster_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.suffix.lower() in RASTER_SUFFIXES)


def normalise_bands(image: np.ndarray) -> np.ndarray:
    output = np.zeros_like(image, dtype=np.float32)
    for index, band in enumerate(image):
        finite = band[np.isfinite(band)]
        if finite.size == 0:
            raise ValueError("Raster band contains no finite pixels")
        lower, upper = np.percentile(finite, (2, 98))
        output[index] = np.clip(
            (np.nan_to_num(band, nan=float(lower)) - lower) / max(float(upper - lower), 1.0),
            0,
            1,
        )
    return output


def read_scene(image_path: Path, mask_path: Path) -> tuple[np.ndarray, np.ndarray]:
    import rasterio
    import torch
    import torch.nn.functional as functional

    with rasterio.open(image_path) as source:
        indexes = list(range(1, min(source.count, 3) + 1))
        image = source.read(indexes, masked=True).filled(np.nan).astype(np.float32)
    while image.shape[0] < 3:
        image = np.concatenate([image, image[-1:, :, :]], axis=0)
    image = normalise_bands(image[:3])

    with rasterio.open(mask_path) as source:
        mask = (source.read(1) > 0).astype(np.float32)

    image_tensor = functional.interpolate(
        torch.from_numpy(image).unsqueeze(0),
        size=(PREPROCESS_SIZE, PREPROCESS_SIZE),
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)
    mask_tensor = functional.interpolate(
        torch.from_numpy(mask).unsqueeze(0).unsqueeze(0),
        size=(PREPROCESS_SIZE, PREPROCESS_SIZE),
        mode="nearest",
    ).squeeze(0)
    return (
        (image_tensor.numpy() * 255).round().astype(np.uint8),
        mask_tensor.numpy().astype(np.uint8),
    )


def pair_by_stem(images_root: Path, masks_root: Path) -> list[tuple[Path, Path]]:
    masks = {path.stem: path for path in raster_files(masks_root)}
    return [(path, masks[path.stem]) for path in raster_files(images_root) if path.stem in masks]


def save_scene(image_path: Path, mask_path: Path, output: Path, category: str) -> None:
    if output.exists():
        return
    image, mask = read_scene(image_path, mask_path)
    np.savez_compressed(output, image=image, mask=mask, category=np.array(category))


def prepare_training_category(work_dir: Path, entry: dict[str, object]) -> None:
    category = str(entry["category"])
    expected = int(entry["expected"])
    output_dir = work_dir / "prepared" / "train" / category
    output_dir.mkdir(parents=True, exist_ok=True)
    if len(list(output_dir.glob("*.npz"))) == expected:
        print(f"{category}: all {expected} prepared scenes already exist")
        return

    raw = work_dir / "raw" / f"train-{category}"
    image_archive = raw / "images.7z"
    mask_archive = raw / "masks.7z"
    images_root = raw / "images"
    masks_root = raw / "masks"
    download(str(entry["masks"]), mask_archive)
    extract(mask_archive, masks_root)
    download(str(entry["images"]), image_archive)
    extract(image_archive, images_root)
    pairs = pair_by_stem(images_root, masks_root)
    if len(pairs) != expected:
        raise RuntimeError(f"Expected {expected} {category} pairs, found {len(pairs)}")
    for index, (image_path, mask_path) in enumerate(pairs, start=1):
        save_scene(image_path, mask_path, output_dir / f"{category}-{image_path.stem}.npz", category)
        if index % 50 == 0 or index == expected:
            print(f"{category}: prepared {index}/{expected}")
    shutil.rmtree(raw)


def path_category(path: Path) -> str:
    tokens = {part.lower().replace("-", "_").replace(" ", "_") for part in path.parts}
    if any("lookalike" in token or "look_alike" in token for token in tokens):
        return "lookalike"
    if any("no_oil" in token or token == "nooil" for token in tokens):
        return "no_oil"
    return "oil"


def is_mask_path(path: Path) -> bool:
    tokens = [part.lower().replace("-", "_").replace(" ", "_") for part in path.parts]
    return any(
        token in {"mask", "masks", "ground_truth", "groundtruth"} or token.startswith("mask_")
        for token in tokens
    )


def prepare_test_data(work_dir: Path) -> None:
    output_root = work_dir / "prepared" / "test"
    expected_counts = TEST_ARCHIVE["expected"]
    if all(
        len(list((output_root / category).glob("*.npz"))) == expected
        for category, expected in expected_counts.items()
    ):
        print("Part III: all prepared test scenes already exist")
        return

    raw = work_dir / "raw" / "test"
    archive = raw / "test.7z"
    extracted = raw / "extracted"
    download(str(TEST_ARCHIVE["url"]), archive)
    extract(archive, extracted)
    mask_index: dict[tuple[str, str], Path] = {}
    images: list[Path] = []
    for path in raster_files(extracted):
        category = path_category(path)
        if is_mask_path(path):
            mask_index[(category, path.stem)] = path
        else:
            images.append(path)

    counts: dict[str, int] = defaultdict(int)
    for image_path in images:
        category = path_category(image_path)
        mask_path = mask_index.get((category, image_path.stem))
        if mask_path is None:
            continue
        destination = output_root / category
        destination.mkdir(parents=True, exist_ok=True)
        save_scene(image_path, mask_path, destination / f"{category}-{image_path.stem}.npz", category)
        counts[category] += 1
    if dict(counts) != expected_counts:
        raise RuntimeError(f"Part III pairing mismatch. Expected {expected_counts}, found {dict(counts)}")
    shutil.rmtree(raw)
    print(f"Prepared independent test scenes: {dict(counts)}")


def write_manifest(work_dir: Path) -> None:
    manifest = {
        split: [
            {"path": str(path), "category": path.parent.name, "scene": path.stem}
            for path in sorted((work_dir / "prepared" / split).glob("*/*.npz"))
        ]
        for split in ("train", "test")
    }
    path = work_dir / "prepared" / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print({split: len(entries) for split, entries in manifest.items()})


def prepare_all(work_dir: Path) -> None:
    free_gib = shutil.disk_usage(
        work_dir.parent if work_dir.parent.exists() else Path("/content")
    ).free / 2**30
    if free_gib < 90:
        raise RuntimeError(
            f"At least 90 GiB free ephemeral disk is recommended; only {free_gib:.1f} GiB is available. "
            "Select a Colab high-disk runtime or a cloud VM with a larger disk."
        )
    for entry in TRAIN_ARCHIVES:
        prepare_training_category(work_dir, entry)
    prepare_test_data(work_dir)
    write_manifest(work_dir)


def scene_split(entries: list[dict[str, str]], validation_fraction: float, seed: int):
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for entry in entries:
        grouped[entry["category"]].append(entry)
    train, validation = [], []
    rng = random.Random(seed)
    for category, items in grouped.items():
        rng.shuffle(items)
        count = max(1, round(len(items) * validation_fraction))
        validation.extend(items[:count])
        train.extend(items[count:])
        print(f"{category}: {len(items) - count} train scenes, {count} validation scenes")
    return train, validation


def tile_slices() -> tuple[tuple[slice, slice], ...]:
    return (
        (slice(0, MODEL_TILE_SIZE), slice(0, MODEL_TILE_SIZE)),
        (slice(0, MODEL_TILE_SIZE), slice(MODEL_TILE_SIZE, PREPROCESS_SIZE)),
        (slice(MODEL_TILE_SIZE, PREPROCESS_SIZE), slice(0, MODEL_TILE_SIZE)),
        (slice(MODEL_TILE_SIZE, PREPROCESS_SIZE), slice(MODEL_TILE_SIZE, PREPROCESS_SIZE)),
    )


class PreparedDataset:
    """Picklable lazy dataset so Colab DataLoader workers can open compact scenes."""

    def __init__(self, entries: list[dict[str, str]], augment: bool) -> None:
        self.items = [(entry, tile) for entry in entries for tile in range(4)]
        self.augment = augment

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int):
        import torch

        entry, tile = self.items[index]
        with np.load(entry["path"], allow_pickle=False) as document:
            rows, columns = tile_slices()[tile]
            image = torch.from_numpy(document["image"][:, rows, columns].copy()).float() / 255
            mask = torch.from_numpy(document["mask"][:, rows, columns].copy()).float()
        if self.augment:
            if torch.rand(()) < 0.5:
                image, mask = image.flip(-1), mask.flip(-1)
            if torch.rand(()) < 0.5:
                image, mask = image.flip(-2), mask.flip(-2)
        return image, mask, entry["category"], entry["scene"]


def build_dataset(entries: list[dict[str, str]], augment: bool):
    return PreparedDataset(entries, augment)


def select_device():
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def batch_loss(logits, targets):
    import torch
    import torch.nn.functional as functional

    positive_weight = torch.tensor([6.0], device=logits.device)
    bce = functional.binary_cross_entropy_with_logits(logits, targets, pos_weight=positive_weight)
    probabilities = torch.sigmoid(logits)
    intersection = (probabilities * targets).sum(dim=(1, 2, 3))
    denominator = probabilities.sum(dim=(1, 2, 3)) + targets.sum(dim=(1, 2, 3))
    dice_loss = 1 - ((2 * intersection + 1) / (denominator + 1)).mean()
    return 0.5 * bce + 0.5 * dice_loss


def empty_stats() -> dict[str, float]:
    return {
        "intersection": 0,
        "prediction": 0,
        "target": 0,
        "union": 0,
        "negative_pixels": 0,
        "false_positive_pixels": 0,
        "negative_tiles": 0,
        "false_alarm_tiles": 0,
    }


def evaluate(model, loader, device, thresholds: Iterable[float]):
    import torch

    model.eval()
    statistics = {float(threshold): defaultdict(empty_stats) for threshold in thresholds}
    with torch.inference_mode():
        for images, targets, categories, _ in loader:
            probabilities = torch.sigmoid(model(images.to(device))).cpu()
            targets = targets.bool()
            for threshold in statistics:
                predictions = probabilities >= threshold
                for index, category in enumerate(categories):
                    prediction = predictions[index]
                    target = targets[index]
                    values = statistics[threshold][category]
                    if category == "oil" and target.any():
                        values["intersection"] += float((prediction & target).sum())
                        values["prediction"] += float(prediction.sum())
                        values["target"] += float(target.sum())
                        values["union"] += float((prediction | target).sum())
                    else:
                        values["negative_pixels"] += float(target.numel())
                        values["false_positive_pixels"] += float(prediction.sum())
                        values["negative_tiles"] += 1
                        values["false_alarm_tiles"] += int(prediction.sum() >= 16)
    results = {}
    for threshold, categories in statistics.items():
        oil = categories["oil"]
        metrics = {
            "threshold": threshold,
            "oil_dice": (2 * oil["intersection"] + 1) / (oil["prediction"] + oil["target"] + 1),
            "oil_iou": (oil["intersection"] + 1) / (oil["union"] + 1),
        }
        false_alarm_rates = []
        for category in ("no_oil", "lookalike"):
            values = categories[category]
            scene_rate = values["false_alarm_tiles"] / max(values["negative_tiles"], 1)
            metrics[f"{category}_false_alarm_tile_rate"] = scene_rate
            metrics[f"{category}_false_positive_pixel_rate"] = (
                values["false_positive_pixels"] / max(values["negative_pixels"], 1)
            )
            false_alarm_rates.append(scene_rate)
        metrics["selection_score"] = metrics["oil_dice"] - 0.25 * float(np.mean(false_alarm_rates))
        results[threshold] = metrics
    return results


def load_manifest(work_dir: Path):
    path = work_dir / "prepared" / "manifest.json"
    if not path.exists():
        raise RuntimeError("Prepared manifest is missing. Run the prepare stage first.")
    return json.loads(path.read_text(encoding="utf-8"))


def train_model(
    work_dir: Path, output: Path, epochs: int, batch_size: int, seed: int, workers: int = 2,
) -> None:
    import torch
    from torch.utils.data import DataLoader

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    manifest = load_manifest(work_dir)
    train_entries, validation_entries = scene_split(manifest["train"], 0.2, seed)
    train_loader = DataLoader(
        build_dataset(train_entries, True), batch_size=batch_size, shuffle=True,
        num_workers=workers, pin_memory=device_is_cuda(),
    )
    validation_loader = DataLoader(
        build_dataset(validation_entries, False), batch_size=batch_size, shuffle=False,
        num_workers=workers, pin_memory=device_is_cuda(),
    )
    device = select_device()
    print(f"Training on {device}")
    model = build_unet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    thresholds = np.arange(0.20, 0.81, 0.05).round(2).tolist()
    best_score = float("-inf")
    output.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        running_loss = 0.0
        for images, targets, _, _ in train_loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=device.type == "cuda"):
                loss = batch_loss(model(images), targets)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running_loss += float(loss.detach())
        scheduler.step()
        evaluations = evaluate(model, validation_loader, device, thresholds)
        selected = max(evaluations.values(), key=lambda values: values["selection_score"])
        print(json.dumps({"epoch": epoch, "loss": running_loss / len(train_loader), **selected}, indent=2))
        if selected["selection_score"] <= best_score:
            continue
        best_score = selected["selection_score"]
        metadata = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "epoch": epoch,
            "dataset_sample_count": len(manifest["train"]),
            "validation_dice": selected["oil_dice"],
            "validation_iou": selected["oil_iou"],
            "training_epochs": epochs,
            "input_shape": [3, MODEL_TILE_SIZE, MODEL_TILE_SIZE],
            "dataset_provenance": {
                "title": "Sentinel-1 SAR Oil spill image dataset, Parts I-III",
                "part_i_doi": "10.5281/zenodo.8346860",
                "part_ii_doi": "10.5281/zenodo.8253899",
                "part_iii_doi": "10.5281/zenodo.13761290",
                "training_scene_counts": {"oil": 1200, "no_oil": 685, "lookalike": 685},
                "validation_split": "20% stratified by original scene before tiling",
                "selected_threshold": selected["threshold"],
                "validation_no_oil_false_alarm_tile_rate": selected["no_oil_false_alarm_tile_rate"],
                "validation_lookalike_false_alarm_tile_rate": selected["lookalike_false_alarm_tile_rate"],
                "false_alarm_definition": "A negative 256x256 tile with at least 16 predicted oil pixels",
                "preprocessing": (
                    "Per-band 2nd-98th percentile normalization; two source bands padded to "
                    "three like backend inference; 512 resize; four non-overlapping 256 tiles"
                ),
                "test_status": "Part III evaluation pending",
            },
        }
        torch.save({"model_state_dict": model.state_dict(), "training_metadata": metadata}, output)
        print(f"Saved best checkpoint to {output}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def device_is_cuda() -> bool:
    import torch

    return torch.cuda.is_available()


def test_model(work_dir: Path, checkpoint_path: Path, batch_size: int, workers: int = 2) -> None:
    import torch
    from torch.utils.data import DataLoader

    manifest = load_manifest(work_dir)
    device = select_device()
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = build_unet().to(device)
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    threshold = float(checkpoint["training_metadata"]["dataset_provenance"]["selected_threshold"])
    loader = DataLoader(
        build_dataset(manifest["test"], False), batch_size=batch_size, shuffle=False,
        num_workers=workers, pin_memory=device_is_cuda(),
    )
    results = evaluate(model, loader, device, [threshold])[threshold]
    provenance = checkpoint["training_metadata"]["dataset_provenance"]
    provenance.update({
        "test_status": "Evaluated once on the untouched official Part III split",
        "test_scene_counts": TEST_ARCHIVE["expected"],
        "test_oil_dice": results["oil_dice"],
        "test_oil_iou": results["oil_iou"],
        "test_no_oil_false_alarm_tile_rate": results["no_oil_false_alarm_tile_rate"],
        "test_lookalike_false_alarm_tile_rate": results["lookalike_false_alarm_tile_rate"],
    })
    torch.save(checkpoint, checkpoint_path)
    report = {
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": sha256(checkpoint_path),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        **results,
    }
    report_path = checkpoint_path.with_suffix(".test-metrics.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Updated checkpoint provenance and wrote {report_path}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "train", "test", "all"))
    parser.add_argument("--work-dir", type=Path, default=Path("/content/seascan-full-dataset"))
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("/content/drive/MyDrive/SeaScan/checkpoints/seascan_unet_full.pt"),
    )
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    arguments.work_dir.mkdir(parents=True, exist_ok=True)
    if arguments.stage in {"prepare", "all"}:
        prepare_all(arguments.work_dir)
    if arguments.stage in {"train", "all"}:
        train_model(
            arguments.work_dir, arguments.checkpoint, arguments.epochs,
            arguments.batch_size, arguments.seed, arguments.workers,
        )
    if arguments.stage in {"test", "all"}:
        test_model(arguments.work_dir, arguments.checkpoint, arguments.batch_size, arguments.workers)


if __name__ == "__main__":
    main()
