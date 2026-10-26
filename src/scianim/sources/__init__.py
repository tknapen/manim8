"""Source adapters: what a supplied file says, with checksums, never what it means (spec 6.1)."""

from scianim.sources.adapters import EXTRACT_DIR, load_extracts, probe_all, probe_source, write_extract

__all__ = ["EXTRACT_DIR", "load_extracts", "probe_all", "probe_source", "write_extract"]
