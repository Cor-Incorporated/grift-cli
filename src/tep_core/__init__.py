"""tep-core: deterministic TEP evidence metrics from a git repository."""

from tep_core.analyze import analyze_repository
from tep_core.identity import load_identity
from tep_core.lineage import Lineage
from tep_core.version import DEFINITION_VERSION, __version__

__all__ = [
    "DEFINITION_VERSION",
    "Lineage",
    "analyze_repository",
    "load_identity",
    "__version__",
]
