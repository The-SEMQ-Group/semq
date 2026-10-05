# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Include TypeDoc output from this checkout in the MkDocs build.

Generated HTML/assets are virtual MkDocs files, never checked-in reference
copies. Missing dependencies, TypeScript errors and TypeDoc warnings fail the
build. The package entry point is the only TypeDoc entry point.
"""

import posixpath
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File


def on_files(files, config):
    package = Path(config.config_file_path).parent / "bindings" / "ts"
    npm = shutil.which("npm")
    if npm is None or not (package / "node_modules" / "typedoc").is_dir():
        raise PluginError(
            "The TypeScript reference needs Node.js and TypeDoc. "
            "Run npm ci --prefix bindings/ts before building the docs."
        )
    with TemporaryDirectory(prefix="semq-typedoc-") as output:
        try:
            subprocess.run(
                [npm, "run", "docs", "--", "--out", output],
                cwd=package,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.CalledProcessError as exc:
            raise PluginError(f"TypeDoc failed:\n{exc.stdout}\n{exc.stderr}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PluginError("TypeDoc exceeded the 120-second build limit") from exc
        for path in sorted(Path(output).rglob("*")):
            if path.is_file():
                relative = path.relative_to(output)
                content = path.read_bytes()
                if path.suffix == ".html":
                    # TypeDoc uses navigationLinks verbatim on nested pages.
                    # Keep the return link valid for local and subpath hosting.
                    back = posixpath.relpath(
                        "../typescript", relative.parent.as_posix()
                    )
                    content = content.replace(
                        b'href="https://github.com/The-SEMQ-Group/semq/blob/main/docs/reference/typescript.md"',
                        f'href="{back}/"'.encode(),
                    )
                files.append(
                    File.generated(
                        config,
                        "reference/typescript-api/" + relative.as_posix(),
                        content=content,
                    )
                )
    return files
