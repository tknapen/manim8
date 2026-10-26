"""SciAnim Studio render bridge: runs inside a family environment next to Manim.

Generated scene code imports `SnapshotScene`, `checkpoint` and `components` from here. Nothing in
this package is imported by the control plane.
"""

from scianim_bridge import components
from scianim_bridge.checkpoint import checkpoint
from scianim_bridge.scene import SnapshotScene

__version__ = "0.1.0a0"

__all__ = ["SnapshotScene", "__version__", "checkpoint", "components"]
