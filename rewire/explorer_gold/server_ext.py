"""Server option: DUCT Explorer server that also serves Gold from `spine serve`.

`SpineGoldExplorerServer` is the unmodified upstream `ExplorerServer` plus three read-only endpoints under the
same prefix and user auth. Through these, the client reads analysis results from the spine (OGC API Features)
instead of submitting DUCT processor jobs:

  GET {prefix}/spine/analyses                                  analysis -> transform ids -> available Gold collections
  GET {prefix}/spine/analysis/{analysis_type}?scenario=&limit=  Gold FeatureCollections for one analysis
  GET {prefix}/spine/collections/{collection_id}/items?scenario=&limit=   proxied OGC API Features items
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from fastapi import Depends, HTTPException
from saas.rest.schemas import EndpointDefinition

from explorer.checks import CheckIfUser
from explorer.server import ExplorerServer

from spine_gold import SpineGoldClient, analysis_gold, load_gold_map

SPINE_URL_ENV = "EXPLORER_SPINE_URL"


class SpineGoldExplorerServer(ExplorerServer):
    def __init__(self, server_address, node_address, wd_path: str, spine_url: Optional[str] = None) -> None:
        super().__init__(server_address, node_address, wd_path)
        url = spine_url or os.environ.get(SPINE_URL_ENV)
        if not url:
            raise ValueError(f"spine mode needs a spine serve URL (argument or ${SPINE_URL_ENV})")
        self.spine = SpineGoldClient(url)
        self.gold_map = load_gold_map()

    def endpoints(self) -> List[EndpointDefinition]:
        return super().endpoints() + spine_endpoints(self)

    def get_spine_analyses(self) -> Dict:
        ids = self.spine.collection_ids()
        return {name: {tid: self.spine.gold_collections(tid, ids) for tid in spec["transforms"]}
                for name, spec in self.gold_map["analyses"].items()}

    def get_spine_analysis(self, analysis_type: str, scenario: Optional[str] = None,
                           limit: Optional[int] = None) -> Dict:
        try:
            return analysis_gold(self.spine, analysis_type, scenario, limit, self.gold_map)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    def get_spine_items(self, collection_id: str, scenario: Optional[str] = None,
                        limit: Optional[int] = None) -> Dict:
        if not (collection_id.startswith("gold.") or collection_id.startswith("silver.")):
            raise HTTPException(status_code=400, detail="collection id must be silver.<table> or gold.<tid>.<table>")
        return self.spine.items(collection_id, scenario, limit)


def spine_endpoints(server: SpineGoldExplorerServer) -> List[EndpointDefinition]:
    check_if_user = Depends(CheckIfUser(server))
    p = server.endpoint_prefix
    return [
        EndpointDefinition('GET', p, 'spine/analyses', server.get_spine_analyses, Dict, [check_if_user]),
        EndpointDefinition('GET', p, 'spine/analysis/{analysis_type}', server.get_spine_analysis, Dict,
                           [check_if_user]),
        EndpointDefinition('GET', p, 'spine/collections/{collection_id}/items', server.get_spine_items, Dict,
                           [check_if_user]),
    ]
