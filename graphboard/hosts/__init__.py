import os
from pathlib import Path

from .base import HostAdapter
from .omp import OmpAdapter
from .opencode import OpencodeAdapter

ADAPTERS: dict[str, type[HostAdapter]] = {
    "omp": OmpAdapter,
    "opencode": OpencodeAdapter,
}


def get_adapter(host: str = "auto", repo=None) -> HostAdapter:
    if host in ADAPTERS:
        return ADAPTERS[host]()
    if repo is not None:
        r = Path(os.path.expanduser(str(repo)))
        if (r / ".omp").exists() and not (r / ".opencode").exists():
            return OmpAdapter()
        if (r / ".mcp.json").exists() and not (r / "opencode.json").exists():
            return OmpAdapter()
        if (r / ".opencode").exists():
            return OpencodeAdapter()
        if (r / "opencode.json").exists():
            return OpencodeAdapter()
    return OmpAdapter() if host == "omp" else OpencodeAdapter()
