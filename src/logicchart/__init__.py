"""LogicChart turns source code into source-grounded workflow flowcharts."""

from importlib.metadata import PackageNotFoundError, version

from logicchart.model import ProjectModel

__all__ = ["ProjectModel"]

try:
    __version__ = version("logicchart")
except PackageNotFoundError:  # pragma: no cover - only when imported outside an install.
    __version__ = "0.0.0"
