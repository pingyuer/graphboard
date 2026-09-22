from abc import ABC, abstractmethod
from pathlib import Path


class HostAdapter(ABC):
    name: str

    @abstractmethod
    def agents_dir(self, repo: Path) -> Path:
        """Return the directory where agent markdown files live."""
        ...

    @abstractmethod
    def render_frontmatter(self, name: str, description: str) -> str:
        """Render the YAML frontmatter for an agent file."""
        ...

    @abstractmethod
    def write_config(self, repo: Path, board_dir: Path, project: str) -> str:
        """Write host configuration file and return status string."""
        ...

    @abstractmethod
    def gitignore_entries(self) -> list[str]:
        """Return list of gitignore patterns specific to this host."""
        ...

    @abstractmethod
    def next_steps(self, repo: Path) -> str:
        """Return instruction text for the user after init."""
        ...
