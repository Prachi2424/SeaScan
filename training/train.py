from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Subset

from dataset import OilSpillSegmentationDataset
from model import build_unet


def dice_score(logits: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
    predictions = (torch.sigmoid(logits) >= 0.5).float()
    intersection = (predictions * masks).sum(dim=(1, 2, 3))
    denominator = predictions.sum(dim=(1, 2, 3)) + masks.sum(dim=(1, 2, 3))
    return ((2 * intersection + 1e-6) / (denominator + 1e-6)).mean()


def combined_loss(logits: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
    bce = nn.functional.binary_cross_entropy_with_logits(logits, masks)
    probabilities = torch.sigmoid(logits)
    intersection = (probabilities * masks).sum(dim=(1, 2, 3))
    denominator = probabilities.sum(dim=(1, 2, 3)) + masks.sum(dim=(1, 2, 3))
    dice_loss = 1 - ((2 * intersection + 1e-6) / (denominator + 1e-6)).mean()
    return bce + dice_loss


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train SeaScan's U-Net only on paired real satellite scenes and masks.")
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--masks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--epochs", default=30, type=int)
    parser.add_argument("--batch-size", default=4, type=int)
    parser.add_argument("--learning-rate", default=1e-3, type=float)
    parser.add_argument("--image-size", default=256, type=int)
    parser.add_argument("--seed", default=42, type=int)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.epochs < 1 or arguments.batch_size < 1:
        raise ValueError("epochs and batch-size must be positive.")
    dataset = OilSpillSegmentationDataset(arguments.images, arguments.masks, arguments.image_size)
    if len(dataset) < 2:
        raise ValueError("At least two paired samples are required to produce a held-out validation metric.")
    indices = list(range(len(dataset)))
    random.Random(arguments.seed).shuffle(indices)
    validation_count = max(1, round(len(indices) * 0.2))
    train_indices, validation_indices = indices[validation_count:], indices[:validation_count]
    if not train_indices:
        raise ValueError("Training split is empty.")
    train_loader = DataLoader(Subset(dataset, train_indices), batch_size=arguments.batch_size, shuffle=True)
    validation_loader = DataLoader(Subset(dataset, validation_indices), batch_size=arguments.batch_size)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_unet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=arguments.learning_rate)
    best_dice = float("-inf")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(1, arguments.epochs + 1):
        model.train()
        for images, masks in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(images.to(device))
            loss = combined_loss(logits, masks.to(device))
            loss.backward()
            optimizer.step()
        model.eval()
        validation_scores: list[float] = []
        with torch.inference_mode():
            for images, masks in validation_loader:
                validation_scores.append(float(dice_score(model(images.to(device)), masks.to(device))))
        validation_dice = sum(validation_scores) / len(validation_scores)
        print(json.dumps({"epoch": epoch, "validation_dice": validation_dice}))
        if validation_dice > best_dice:
            best_dice = validation_dice
            torch.save(
                {
                    "model_state_dict": model.cpu().state_dict(),
                    "training_metadata": {
                        "trained_at": datetime.now(UTC).isoformat(),
                        "epoch": epoch,
                        "dataset_sample_count": len(dataset),
                        "validation_dice": validation_dice,
                    },
                },
                arguments.output,
            )
            model.to(device)
    print(f"Saved best checkpoint to {arguments.output} (validation Dice: {best_dice:.6f}).")


if __name__ == "__main__":
    main()
