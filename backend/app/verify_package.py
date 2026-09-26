from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.signing import verify_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a SeaScan digitally signed evidence package.")
    parser.add_argument("package", type=Path)
    parser.add_argument("--trusted-key-id", action="append", default=[], help="Trusted SHA-256 public-key fingerprint; repeat as needed.")
    args = parser.parse_args()
    result = verify_package(args.package.read_bytes(), set(args.trusted_key_id))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
