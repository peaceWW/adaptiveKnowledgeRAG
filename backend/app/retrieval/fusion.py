from __future__ import annotations

from collections import defaultdict


def rrf_fuse(
    ranked_lists: list[list[dict]],
    k: int = 60,
    weights: list[float] | None = None,
    limit: int = 50,
) -> list[dict]:
    scores: dict[str, float] = defaultdict(float)
    payload: dict[str, dict] = {}
    weights = weights or [1.0] * len(ranked_lists)
    for weight, ranked in zip(weights, ranked_lists, strict=False):
        for rank, item in enumerate(ranked):
            item_id = item["id"]
            scores[item_id] += weight * (1.0 / (k + rank + 1))
            payload[item_id] = item
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    fused = []
    for item_id, score in ordered:
        row = dict(payload[item_id])
        row["fused_score"] = score
        fused.append(row)
    return fused
