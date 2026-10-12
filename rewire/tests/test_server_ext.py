import pytest
from fastapi import HTTPException

from spine_gold import load_gold_map

server_ext = pytest.importorskip("server_ext")


class FakeSpine:
    def collection_ids(self):
        return ["silver.buildings", "gold.duct.mva_wind_corridor.hotspots"]

    def gold_collections(self, tid, ids):
        return [i for i in ids if i.startswith(f"gold.{tid}.")]

    def items(self, cid, scenario=None, limit=None):
        return {"type": "FeatureCollection", "features": [], "cid": cid, "scenario": scenario}


@pytest.fixture
def server():
    s = object.__new__(server_ext.SpineGoldExplorerServer)
    s.spine, s.gold_map = FakeSpine(), load_gold_map()
    return s


def test_analyses_endpoint(server):
    a = server.get_spine_analyses()
    assert a["wind-corridor-potential"] == {"duct.mva_wind_corridor": ["gold.duct.mva_wind_corridor.hotspots"]}
    assert a["district-cooling"] == {"cea.building_demand": []}


def test_analysis_endpoint(server):
    g = server.get_spine_analysis("wind-corridor-potential", scenario="s1")
    assert g["transforms"]["duct.mva_wind_corridor"]["collections"]["gold.duct.mva_wind_corridor.hotspots"]["scenario"] == "s1"
    with pytest.raises(HTTPException) as e:
        server.get_spine_analysis("nope")
    assert e.value.status_code == 404


def test_items_endpoint_only_proxies_spine_collections(server):
    assert server.get_spine_items("silver.buildings")["cid"] == "silver.buildings"
    with pytest.raises(HTTPException):
        server.get_spine_items("../etc")


def test_spine_endpoints_registered(server, monkeypatch):
    monkeypatch.setattr(server_ext.SpineGoldExplorerServer, "endpoint_prefix", ("/explorer", "v1"), raising=False)
    rules = [e.rule for e in server_ext.spine_endpoints(server)]
    assert rules == ["spine/analyses", "spine/analysis/{analysis_type}", "spine/collections/{collection_id}/items"]


def test_requires_spine_url(monkeypatch):
    monkeypatch.delenv(server_ext.SPINE_URL_ENV, raising=False)
    monkeypatch.setattr(server_ext.ExplorerServer, "__init__", lambda self, *a: None)
    with pytest.raises(ValueError):
        server_ext.SpineGoldExplorerServer(("127.0.0.1", 1), ("127.0.0.1", 2), "/tmp")
