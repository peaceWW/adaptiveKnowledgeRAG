from __future__ import annotations

import logging
import socket
from typing import Any

from neo4j import GraphDatabase

from app.config import get_settings

logger = logging.getLogger(__name__)


class Neo4jStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.available = False
        self.driver = None
        from urllib.parse import urlparse

        parsed = urlparse(settings.neo4j_uri.replace("bolt://", "http://"))
        host = parsed.hostname or "localhost"
        port = parsed.port or 7687
        try:
            with socket.create_connection((host, port), timeout=0.4):
                pass
        except OSError as exc:
            logger.warning("Neo4j unreachable, graph features degrade: %s", exc)
            return
        try:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
                connection_timeout=2,
            )
            self.driver.verify_connectivity()
            self.available = True
        except Exception as exc:
            logger.warning("Neo4j unavailable, graph features degrade: %s", exc)
            if self.driver:
                try:
                    self.driver.close()
                except Exception:
                    pass
            self.driver = None
            self.available = False

    def upsert_unit(self, unit: dict[str, Any]) -> None:
        if not self.driver:
            return
        cypher = """
        MERGE (k:KnowledgeUnit {id: $id})
        SET k.title = $title,
            k.semantic_role = $semantic_role,
            k.domain = $domain,
            k.kb_id = $kb_id,
            k.lifecycle = $lifecycle
        WITH k
        UNWIND $concepts AS concept
        MERGE (c:Concept {name: concept})
        MERGE (k)-[:RELATED_TO]->(c)
        """
        with self.driver.session() as session:
            session.run(cypher, unit)

    def upsert_relation(self, from_id: str, to_id: str, rel_type: str) -> None:
        if not self.driver:
            return
        safe = "".join(ch for ch in rel_type if ch.isalnum() or ch == "_")
        cypher = f"""
        MERGE (a:KnowledgeUnit {{id: $from_id}})
        MERGE (b:KnowledgeUnit {{id: $to_id}})
        MERGE (a)-[r:{safe}]->(b)
        """
        with self.driver.session() as session:
            session.run(cypher, {"from_id": from_id, "to_id": to_id})

    def expand(self, concept: str, depth: int = 2) -> list[dict[str, Any]]:
        if not self.driver:
            return []
        cypher = """
        MATCH (c:Concept {name: $concept})-[r*1..$depth]-(n)
        RETURN DISTINCT n, type(r[-1]) AS rel
        LIMIT 50
        """
        try:
            with self.driver.session() as session:
                records = session.run(cypher, {"concept": concept, "depth": depth})
                nodes = []
                for rec in records:
                    node = rec["n"]
                    nodes.append({"id": node.get("id"), "title": node.get("title"), "rel": rec["rel"]})
                return nodes
        except Exception as exc:
            logger.warning("Neo4j expand failed: %s", exc)
            return []

    def neighborhood(self, name: str, max_level: int = 3) -> dict[str, Any]:
        if not self.driver:
            return {"nodes": [], "edges": []}
        cypher = """
        MATCH path = (n)-[r*1..3]-(m)
        WHERE n.title CONTAINS $name OR n.name CONTAINS $name
        WITH nodes(path) AS ns, relationships(path) AS rs
        UNWIND ns AS node
        UNWIND rs AS rel
        RETURN collect(DISTINCT node) AS nodes, collect(DISTINCT rel) AS rels
        """
        try:
            with self.driver.session() as session:
                rec = session.run(cypher, {"name": name}).single()
                if not rec:
                    return {"nodes": [], "edges": []}
                nodes = []
                for node in rec["nodes"] or []:
                    nodes.append(
                        {
                            "id": node.get("id") or node.get("name"),
                            "label": node.get("title") or node.get("name"),
                            "role": node.get("semantic_role", "concept"),
                        }
                    )
                edges = []
                for rel in rec["rels"] or []:
                    edges.append(
                        {
                            "source": rel.start_node.get("id") or rel.start_node.get("name"),
                            "target": rel.end_node.get("id") or rel.end_node.get("name"),
                            "type": rel.type,
                        }
                    )
                return {"nodes": nodes[:80], "edges": edges[:120]}
        except Exception as exc:
            logger.warning("Neo4j neighborhood failed: %s", exc)
            return {"nodes": [], "edges": []}

    def close(self) -> None:
        if self.driver:
            self.driver.close()
