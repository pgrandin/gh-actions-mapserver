#!/usr/bin/env python3
"""Read-only, bounded S3 byte-range checks against a local reference file."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

MAX_SAMPLE = 64 * 1024


def sample_ranges(size, sample_size=MAX_SAMPLE):
    if size <= 0:
        raise ValueError("Reference must be nonempty")
    if not 1 <= sample_size <= MAX_SAMPLE:
        raise ValueError(f"Sample size must be between 1 and {MAX_SAMPLE}")
    width = min(size, sample_size)
    starts = {0, size - width, (size - width) // 2, (size - width) // 4}
    # Exercise offsets on both sides of ZIP32's limit without reading GiBs.
    for boundary in (1 << 32, 1 << 33):
        if size > boundary:
            starts.add(min(size - width, boundary))
            starts.add(max(0, min(size - width, boundary - width // 2)))
    return [(start, start + width - 1) for start in sorted(starts)]


def read_range(client, bucket, key, start, end, size):
    response = client.get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
    body = response["Body"]
    try:
        expected = end - start + 1
        if response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 206:
            raise ValueError("Server did not return HTTP 206 for a range request")
        if response.get("ContentRange") != f"bytes {start}-{end}/{size}":
            raise ValueError("Server returned an unexpected Content-Range")
        if response.get("ContentLength") != expected:
            raise ValueError("Server returned an unexpected Content-Length")
        data = bytearray()
        # Never consume an unbounded response, even if a server lies in headers.
        # Loop because streaming bodies can return short reads before EOF.
        while len(data) <= expected:
            block = body.read(expected + 1 - len(data))
            if not block:
                break
            data.extend(block)
        if len(data) != expected:
            raise ValueError("Range body length does not match its headers")
        return bytes(data)
    finally:
        body.close()


def probe(client, bucket, key, reference, sample_size=MAX_SAMPLE):
    started = time.monotonic()
    checks = []
    with Path(reference).open("rb") as source:
        source.seek(0, 2)
        size = source.tell()
        ranges = sample_ranges(size, sample_size)
        before = client.head_object(Bucket=bucket, Key=key)
        if before["ContentLength"] != size:
            raise ValueError("Remote size differs from the local reference")
        for start, end in ranges:
            data = read_range(client, bucket, key, start, end, size)
            source.seek(start)
            if data != source.read(end - start + 1):
                raise ValueError(f"Remote bytes differ at offset {start}")
            checks.append(
                {"start": start, "end": end, "sha256": hashlib.sha256(data).hexdigest()}
            )
        after = client.head_object(Bucket=bucket, Key=key)
        for field in ("ContentLength", "ETag", "LastModified"):
            if before.get(field) != after.get(field):
                raise ValueError("Remote object changed during the probe")
    return {
        "bucket": bucket,
        "key": key,
        "object_bytes": size,
        "verified_ranges": checks,
        "verified_bytes": sum(end - start + 1 for start, end in ranges),
        "logical_get_requests": len(ranges),
        "logical_head_requests": 2,
        "elapsed_seconds": time.monotonic() - started,
        "scope": "Sampled byte equality only; not full-file or Navit validation",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True, help="An immutable build object key")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--profile", help="Optional standard AWS credential profile")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.namespace):
        parser.error("Invalid HF namespace")
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        parser.error("Install boto3 to run live checks; unit tests need only Python")
    session = boto3.Session(profile_name=args.profile)
    client = session.client(
        "s3",
        endpoint_url=f"https://s3.hf.co/{args.namespace}",
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            connect_timeout=15,
            read_timeout=30,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )
    try:
        print(
            json.dumps(probe(client, args.bucket, args.key, args.reference), indent=2)
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
