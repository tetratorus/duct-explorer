"""Read Gold for DUCT Explorer analyses from `spine serve` (OGC API Features) instead of running DUCT processors."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
import yaml

GOLD_MAP_PATH = Path(__file__).with_name("gold_map.yaml")


def load_gold_map(path: Path = GOLD_MAP_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class SpineGoldClient:
    """Minimal OGC API Features client for an sg-urban-spine `spine serve` endpoint."""

    def __init__(self, base_url: str, timeout: float = 30.0, session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        r = self.session.get(urljoin(self.base_url, path.lstrip("/")), params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def collections(self) -> list[dict]:
        return self._get("collections")["collections"]

    def collection_ids(self) -> list[str]:
        return [c["id"] for c in self.collections()]

    def gold_collections(self, transform_id: str, ids: Optional[list[str]] = None) -> list[str]:
        prefix = f"gold.{transform_id}."
        return sorted(c for c in (ids if ids is not None else self.collection_ids()) if c.startswith(prefix))

    def items(self, collection_id: str, scenario: Optional[str] = None, limit: Optional[int] = None) -> dict:
        params = {k: v for k, v in (("scenario", scenario), ("limit", limit)) if v is not None}
        fc = self._get(f"collections/{collection_id}/items", params)
        nxt = next((ln["href"] for ln in fc.get("links", []) if ln.get("rel") == "next"), None)
        while nxt and (limit is None or len(fc["features"]) < limit):
            page = self.session.get(urljoin(self.base_url, nxt), timeout=self.timeout)
            page.raise_for_status()
            page = page.json()
            fc["features"].extend(page.get("features", []))
            nxt = next((ln["href"] for ln in page.get("links", []) if ln.get("rel") == "next"), None)
        return fc

    def scenarios(self) -> list[str]:
        return self._get("scenarios")["scenarios"]

    def lineage(self, scenario: str, transform_id: str) -> dict:
        return self._get(f"lineage/{scenario}/{transform_id}")


def analysis_gold(client: SpineGoldClient, analysis_type: str, scenario: Optional[str] = None,
                  limit: Optional[int] = None, gold_map: Optional[dict] = None,
                  include_features: bool = True) -> dict:
    """Collect the Gold collections an Explorer analysis consumes, keyed by transform id."""
    gold_map = gold_map or load_gold_map()
    spec = gold_map["analyses"].get(analysis_type)
    if spec is None:
        raise KeyError(f"no Gold mapping for analysis '{analysis_type}'")
    ids = client.collection_ids()
    transforms = {}
    for tid in spec["transforms"]:
        cols = client.gold_collections(tid, ids)
        transforms[tid] = {
            "collections": {c: (client.items(c, scenario, limit) if include_features else None) for c in cols},
            "available": bool(cols),
        }
    return {
        "analysis_type": analysis_type,
        "scenario": scenario,
        "join_key": spec.get("join_key"),
        "replaces": spec.get("replaces", {}),
        "gap": spec.get("gap"),
        "transforms": transforms,
        "silver": [c for c in gold_map.get("silver", []) if c in ids],
    }
