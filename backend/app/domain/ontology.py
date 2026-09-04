from __future__ import annotations

SEMICONDUCTOR_ONTOLOGY_V1: list[dict] = [
    {
        "name": "Semiconductor",
        "level": 0,
        "children": [
            {
                "name": "Digital Design",
                "level": 1,
                "children": [
                    {
                        "name": "RTL Design",
                        "level": 2,
                        "children": [
                            {"name": "FSM", "level": 3, "related": ["state_encoding", "glitch"]},
                            {"name": "Pipeline", "level": 3, "related": ["throughput", "latency"]},
                            {
                                "name": "CDC",
                                "level": 3,
                                "related": ["Metastability", "Synchronizer", "Async FIFO", "Gray Code"],
                            },
                        ],
                    },
                    {
                        "name": "Timing Analysis",
                        "level": 2,
                        "children": [
                            {"name": "Setup Time", "level": 3, "related": ["Hold Time", "Clock Period"]},
                            {"name": "Hold Time", "level": 3, "related": ["Setup Time", "Clock Skew"]},
                            {"name": "Clock Skew", "level": 3, "related": ["CTS", "Clock Period"]},
                        ],
                    },
                ],
            },
            {
                "name": "Physical Design",
                "level": 1,
                "children": [
                    {"name": "Floorplan", "level": 2, "related": ["macro", "io"]},
                    {"name": "Placement", "level": 2, "related": ["congestion"]},
                    {"name": "CTS", "level": 2, "related": ["Clock Skew"]},
                ],
            },
            {
                "name": "DFT",
                "level": 1,
                "children": [
                    {"name": "Scan", "level": 2, "related": ["ATPG"]},
                    {"name": "ATPG", "level": 2, "related": ["coverage"]},
                    {"name": "MBIST", "level": 2, "related": ["memory"]},
                ],
            },
        ],
    }
]


def flatten_ontology(nodes: list[dict] | None = None, parent_path: str = "") -> list[dict]:
    if nodes is None:
        nodes = SEMICONDUCTOR_ONTOLOGY_V1
    rows: list[dict] = []
    for node in nodes:
        path = f"{parent_path}/{node['name']}" if parent_path else node["name"]
        rows.append(
            {
                "name": node["name"],
                "level": node["level"],
                "path": path,
                "related_concepts": node.get("related", []),
            }
        )
        rows.extend(flatten_ontology(node.get("children") or [], path))
    return rows
