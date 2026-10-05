"""Execute the Python examples users copy from the published documentation."""

from pathlib import Path

import pytest
from snippet_utils import REPO_ROOT, site_pages, snippets


@pytest.mark.parametrize(
    "page",
    [page for page in site_pages() if snippets(page, "python")],
    ids=lambda page: str(page.relative_to(REPO_ROOT)),
)
def test_site_python_examples(
    page: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for snippet in snippets(page, "python"):
        namespace = {"__name__": "__main__"}
        try:
            exec(compile(snippet.source, snippet.label, "exec"), namespace)
        except Exception as exc:
            pytest.fail(f"{snippet.label}: {type(exc).__name__}: {exc}")
