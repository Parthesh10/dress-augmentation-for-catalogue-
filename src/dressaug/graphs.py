"""Stage graphs — a graph is data, not code.

Only `FLAT` is runnable today. `DUMMY` is written down because phase 6 is on
the roadmap and a named stage that raises is more honest than a graph that
does not exist: running it tells you exactly which phase is missing.
"""

from __future__ import annotations

from .config import Graph

#: Phases 1 and 2, which is everything that is built.
FLAT = ["ingest", "matte", "background", "composite", "gates", "export"]

#: Phase 6. `dummy` raises until there is a dress form to place onto.
DUMMY = ["ingest", "matte", "background", "dummy", "composite", "gates", "export"]

GRAPHS: dict[Graph, list[str]] = {
    Graph.FLAT: FLAT,
    Graph.DUMMY: DUMMY,
}


def stages_for(graph: Graph) -> list[str]:
    return list(GRAPHS[graph])
