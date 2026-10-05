#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Run the conformance vectors on a short-lived Intel instance with AVX-512.

GitHub's Linux x86_64 runners have no AVX-512, so the AVX-512 kernels in the
Linux wheels never run in CI there. This launches one instance from the
semq-avx512-check launch template (see semq-infra), which runs
tools/remote_backends.sh against the given wheel and reports back through
presigned S3 URLs. The instance has no IAM role and no inbound access, and
terminates when it powers off.

Needs AWS credentials for the semq-avx512-check role (the workflow assumes it
through OIDC) and boto3.

    python tools/avx512_check.py --wheel dist/semq-...-manylinux_x86_64.whl
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-2"
BUCKET = "semq-ci-avx512-127348475353"
TEMPLATE = "semq-avx512-check"
TAG = {"Key": "Purpose", "Value": "semq-avx512-check"}
URL_SECONDS = 3600

USER_DATA = """#!/bin/bash
# Power off, and so terminate, after 45 minutes whatever happens.
shutdown -h +45
exec > /var/log/semq-check.log 2>&1
set -x
export DEBIAN_FRONTEND=noninteractive
apt-get update -q && apt-get install -y -q python3-venv
mkdir -p /opt/check/bundle && cd /opt/check
curl -fsS --retry 5 -o bundle.tar.gz '{get_url}' && tar -xzf bundle.tar.gz
EXPECT='{expect}' bash bundle/tools/remote_backends.sh
cp /var/log/semq-check.log bundle/check.log
test -f bundle/exit_code || echo 99 > bundle/exit_code
tar -czf result.tar.gz -C bundle check.log exit_code
curl -fsS --retry 5 -X PUT --upload-file result.tar.gz '{put_url}'
shutdown -h now
"""


def bundle(wheel: Path) -> bytes:
    """The wheel, the vectors and the two scripts, under bundle/."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(wheel, arcname=f"bundle/{wheel.name}")
        for relative in ("tools/backends.py", "tools/remote_backends.sh"):
            archive.add(ROOT / relative, arcname=f"bundle/{relative}")
        archive.add(ROOT / "tests/conformance", arcname="bundle/tests/conformance",
                    filter=lambda info: None if "__pycache__" in info.name else info)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wheel", type=Path, required=True, help="the Linux x86_64 wheel to check")
    parser.add_argument("--expect", default="scalar,avx2,avx512", help="backends that must be available")
    parser.add_argument("--timeout", type=int, default=40 * 60, help="seconds to wait for a result")
    args = parser.parse_args()

    run = os.environ.get("GITHUB_RUN_ID", "local") + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    prefix = f"runs/{run}-{uuid.uuid4().hex[:8]}"
    # Presign against the regional endpoint. The global one redirects requests
    # for a bucket outside us-east-1 for a while after it is created, and a
    # redirected presigned request fails.
    s3 = boto3.client("s3", region_name=REGION, endpoint_url=f"https://s3.{REGION}.amazonaws.com",
                      config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
    ec2 = boto3.client("ec2", region_name=REGION)

    s3.put_object(Bucket=BUCKET, Key=f"{prefix}/bundle.tar.gz", Body=bundle(args.wheel))
    get_url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": f"{prefix}/bundle.tar.gz"},
                                        ExpiresIn=URL_SECONDS)
    put_url = s3.generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": f"{prefix}/result.tar.gz"},
                                        ExpiresIn=URL_SECONDS)

    instance = ec2.run_instances(
        LaunchTemplate={"LaunchTemplateName": TEMPLATE},
        MinCount=1, MaxCount=1,
        UserData=USER_DATA.format(get_url=get_url, put_url=put_url, expect=args.expect),
        TagSpecifications=[{"ResourceType": "instance", "Tags": [TAG, {"Key": "Run", "Value": prefix}]}],
    )["Instances"][0]["InstanceId"]
    print(f"launched {instance} for {prefix}", flush=True)

    try:
        # The instance powers off right after uploading its result. Wait for
        # that rather than polling S3: without s3:ListBucket, S3 reports a
        # missing object as AccessDenied, indistinguishable from a real denial.
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            state = ec2.describe_instances(InstanceIds=[instance])["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state in ("shutting-down", "terminated", "stopping", "stopped"):
                break
            time.sleep(20)
        else:
            print(f"error: {instance} was still running after {args.timeout} seconds", file=sys.stderr)
            return 1
        try:
            result = s3.get_object(Bucket=BUCKET, Key=f"{prefix}/result.tar.gz")["Body"].read()
        except ClientError as error:
            print(f"error: {instance} is {state} and uploaded no result ({error})", file=sys.stderr)
            return 1
    finally:
        ec2.terminate_instances(InstanceIds=[instance])

    with tarfile.open(fileobj=io.BytesIO(result), mode="r:gz") as archive:
        log = archive.extractfile("check.log").read().decode(errors="replace")
        code = int(archive.extractfile("exit_code").read().decode().strip() or 99)
    print(log)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        tables = [line for line in log.splitlines() if line.startswith(("CPU:", "|"))]
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### AVX-512 check\n\n" + "\n".join(tables) + f"\n\nExit code: {code}\n\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
