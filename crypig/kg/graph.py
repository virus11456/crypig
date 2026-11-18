"""輕量知識圖譜儲存（純 Python，無外部相依，骨架即可跑）。

正式環境可把 backend 換成 Neo4j / RDFLib；介面保持一致：
  add_triple / neighbors / multi_hop / save / load
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable


class KnowledgeGraph:
    def __init__(self) -> None:
        # adjacency: subj -> list[(predicate, obj, meta)]
        self._adj: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
        self._node_meta: dict[str, dict] = {}

    # ---- 寫入 ----
    def add_node(self, name: str, ntype: str = "concept") -> None:
        self._node_meta.setdefault(name, {"type": ntype})

    def add_triple(self, subj: str, pred: str, obj: str, **meta) -> None:
        self.add_node(subj)
        self.add_node(obj)
        # 同一三元組存在則更新 meta（自動更新、避免重複爆量）
        for i, (p, o, _m) in enumerate(self._adj[subj]):
            if p == pred and o == obj:
                self._adj[subj][i] = (p, o, {**_m, **meta})
                return
        self._adj[subj].append((pred, obj, meta))

    # ---- 查詢 ----
    def neighbors(self, node: str) -> list[tuple[str, str, dict]]:
        return list(self._adj.get(node, []))

    def multi_hop(self, start: str, max_hops: int = 3) -> list[tuple[str, str, str]]:
        """從 start 出發 BFS 走訪，回傳走過的三元組（多跳推理用）。"""
        seen_nodes = {start}
        triples: list[tuple[str, str, str]] = []
        q: deque[tuple[str, int]] = deque([(start, 0)])
        while q:
            node, depth = q.popleft()
            if depth >= max_hops:
                continue
            for pred, obj, _m in self._adj.get(node, []):
                triples.append((node, pred, obj))
                if obj not in seen_nodes:
                    seen_nodes.add(obj)
                    q.append((obj, depth + 1))
        return triples

    def subgraph(self, nodes: Iterable[str], max_hops: int = 2) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for n in nodes:
            out.extend(self.multi_hop(n, max_hops))
        # 去重保序
        seen = set()
        uniq = []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq

    def stats(self) -> dict:
        edges = sum(len(v) for v in self._adj.values())
        return {"nodes": len(self._node_meta), "edges": edges}

    # ---- 持久化 ----
    def save(self, path: str | Path) -> None:
        data = {
            "nodes": self._node_meta,
            "edges": {s: [(p, o, m) for p, o, m in lst] for s, lst in self._adj.items()},
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        self._node_meta = data.get("nodes", {})
        self._adj = defaultdict(list)
        for s, lst in data.get("edges", {}).items():
            self._adj[s] = [(p, o, m) for p, o, m in lst]
