import re
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).parent.parent / "graphboard"

FORBIDDEN_PATTERNS = [
    r"ddn", r"dvcl", r"mlflow", r"openbayes",
    r"172\.16\.", r"10\.8\.", r"192\.168\.",
    r"\bVOC\b", r"\bACDC\b", r"\bBraTS\b", r"\bCIFAR\b", r"ImageNet",
    r"p31431", r"p32021",
]


@pytest.mark.parametrize("pattern", FORBIDDEN_PATTERNS)
def test_no_project_specific_identifiers(pattern):
    offenders = []
    for py in PKG_DIR.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(pattern, line, re.IGNORECASE):
                offenders.append(f"{py.name}:{i}: {line.strip()[:80]}")
    assert not offenders, (
        f"project-specific identifier {pattern!r} leaked into core code:\n"
        + "\n".join(offenders))


def test_templates_free_of_project_identifiers():
    tpl_dir = PKG_DIR / "templates"
    offenders = []
    for f in tpl_dir.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{f.name}: {pattern}")
    assert not offenders, "project-specific identifiers leaked into templates: " \
        + ", ".join(offenders)
