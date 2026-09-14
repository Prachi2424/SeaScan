from __future__ import annotations

import argparse
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.geospatial.satellite import segment_satellite


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a trained SeaScan U-Net against a real GeoTIFF or PNG.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--threshold", default=0.5, type=float)
    parser.add_argument("--bounds", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    settings = Settings(model_weights_path=arguments.weights)
    geojson, model, validation = segment_satellite(arguments.image, settings=settings, threshold=arguments.threshold, bounds=tuple(arguments.bounds) if arguments.bounds else None)
    print({"geojson": geojson, "model": model, "validation": validation})


if __name__ == "__main__":
    main()
