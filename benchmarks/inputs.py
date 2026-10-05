# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Download or verify the exact versioned inputs used by published benchmarks."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from .run import ROOT, digest

REGISTRY = ROOT / "benchmarks/configs/frozen-inputs.json"


def verify(directory: Path, files: list[dict]) -> None:
    for spec in files:
        path = directory / spec["file"]
        if (
            not path.is_file()
            or path.stat().st_size != spec["bytes"]
            or digest(path) != spec["sha256"]
        ):
            raise ValueError(f"Input verification failed: {path}")


def download(registry: dict, name: str, output: Path, github: bool = False) -> None:
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}; use --verify-only")
    files = registry["inputs"][name]["files"]
    # An input may live in a later release than the registry's default one.
    release = registry["inputs"][name].get("release", registry["release"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        dir=output.parent, prefix=".benchmark-inputs-"
    ) as temporary:
        directory = Path(temporary)
        for spec in files:
            path = directory / spec["file"]
            if github:
                subprocess.run(
                    [
                        "gh",
                        "release",
                        "download",
                        release,
                        "--repo",
                        registry["repository"],
                        "--pattern",
                        spec["asset"],
                        "--output",
                        str(path),
                    ],
                    check=True,
                )
            else:
                url = f"https://github.com/{registry['repository']}/releases/download/{release}/{spec['asset']}"
                with urlopen(url, timeout=120) as response, path.open("xb") as stream:
                    shutil.copyfileobj(response, stream)
        verify(directory, files)
        directory.rename(output)


def main() -> None:
    registry = json.loads(REGISTRY.read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=sorted(registry["inputs"]))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--github",
        action="store_true",
        help="Use authenticated GitHub CLI access for private repositories",
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify(args.output, registry["inputs"][args.name]["files"])
    else:
        download(registry, args.name, args.output, args.github)
    print(f"Verified input bytes: {args.output / 'embeddings.npz'}")


if __name__ == "__main__":
    main()
