#!/usr/bin/env python3
"""Download a fixed set of release assets and run Navit's conservative merger."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def download(asset, directory):
    """Stream into a temporary file; retries cannot leave a truncated input."""
    expected = asset.get("digest")
    if not expected or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise ValueError(f"No SHA-256 digest for {asset['name']}")
    name = asset["name"]
    if Path(name).name != name:
        raise ValueError("Invalid asset filename")
    target = directory / name
    for attempt in range(3):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                temporary = Path(output.name)
                digest, size = hashlib.sha256(), 0
                with urllib.request.urlopen(
                    asset["browser_download_url"], timeout=60
                ) as response:
                    while block := response.read(1024 * 1024):
                        output.write(block)
                        digest.update(block)
                        size += len(block)
            if size != asset["size"] or f"sha256:{digest.hexdigest()}" != expected:
                raise ValueError(f"Size/checksum mismatch for {name}")
            os.link(temporary, target)
            return target
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def select_assets(release, regions, tag):
    names = [f"{region}-{tag}.bin" for region in regions]
    assets = {asset["name"]: asset for asset in release["assets"]}
    missing = sorted(set(names) - assets.keys())
    if missing:
        raise ValueError("Missing release assets: " + ", ".join(missing))
    return [assets[name] for name in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, help="Fixed YYYY-MM-DD release tag")
    parser.add_argument(
        "--regions", required=True, help="Comma-separated region prefixes"
    )
    parser.add_argument("--navit-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    regions = sorted(set(region.strip() for region in args.regions.split(",")))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.release):
        parser.error("Release must be a fixed YYYY-MM-DD tag")
    if not regions or any(
        not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", region) for region in regions
    ):
        parser.error("Invalid region prefix")
    if args.output.exists() or args.output.with_suffix(".json").exists():
        parser.error("Map or provenance output already exists")
    revision = subprocess.check_output(
        ["git", "-C", str(args.navit_source), "rev-parse", "HEAD"], text=True
    ).strip()
    # Record actual tool/header hashes too, so a local checkout with edits is
    # distinguishable from the committed merger used by the workflow.
    merger_files = {}
    for relative in (
        "contrib/binfile/merge.py",
        "contrib/binfile/binfile.py",
        "contrib/binfile/overlap.py",
        "navit/item.c",
        "navit/item_def.h",
        "navit/attr_def.h",
    ):
        with (args.navit_source / relative).open("rb") as stream:
            merger_files[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    request = urllib.request.Request(
        f"https://api.github.com/repos/navit-gps/gh-actions-mapserver/releases/tags/{args.release}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "navit-binfile-merge",
        },
    )
    # Read the release once so all selected assets come from that exact release.
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    assets = select_assets(release, regions, args.release)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="regional-inputs-", dir=args.output.parent
    ) as work:
        paths = [download(asset, Path(work)) for asset in assets]
        result = subprocess.run(
            [
                sys.executable,
                str(args.navit_source / "contrib/binfile/merge.py"),
                "-o",
                str(args.output),
                *map(str, paths),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        report["merger_revision"] = revision
        report["merger_files_sha256"] = merger_files
        report["source_release"] = release["html_url"]
        report["assets"] = [
            {key: asset[key] for key in ("name", "size", "digest")} for asset in assets
        ]
        with args.output.with_suffix(".json").open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
