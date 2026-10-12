import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pandas as pd
import pytest
import spine
from spine.lake import BASELINE, Lake
from spine.serve import make_handler

from spine_gold import SpineGoldClient, analysis_gold, load_gold_map

REWIRE = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = REWIRE.parent / "server" / "explorer" / "analysis"


@pytest.fixture(scope="module")
def spine_url(tmp_path_factory):
    import adapter
    out = adapter.run({"bdp": REWIRE / "duct.bdp_conform" / "golden" / "queenstown" / "inputs" / "bdp"}, {})
    lake = Lake(tmp_path_factory.mktemp("lake"))
    for table, df in out.items():
        lake.silver_write(table, df)
    # Stand-in Gold table (test data, not CEA output) so the read path can be exercised end to end.
    gdir = lake.gold_dir(BASELINE, "cea.building_demand")
    gdir.mkdir(parents=True)
    ids = out["buildings"].building_id.head(10)
    pd.DataFrame({"building_id": ids, "qc_sys_mwh": range(len(ids))}).to_parquet(gdir / "demand.parquet")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(lake))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_gold_map_names_match_explorer_analyses():
    names = set()
    for f in ANALYSIS_DIR.glob("*.py"):
        names |= set(re.findall(r"def name\(self\) -> str:\s+return ['\"]([a-z-]+)['\"]", f.read_text()))
    assert set(load_gold_map()["analyses"]) == names


def test_gold_map_uses_layers_transform_ids():
    root = Path(spine.__file__).resolve().parent
    layers = next(p for p in (root / "_spec" / "LAYERS.md", root.parent / "spec" / "LAYERS.md") if p.exists())
    table = layers.read_text().split("## Transform ids in use")[1]
    known = set(re.findall(r"[a-z0-9_]+\.[a-z0-9_]+", table))
    for spec in load_gold_map()["analyses"].values():
        assert set(spec["transforms"]) <= known


def test_client_lists_and_reads_collections(spine_url):
    c = SpineGoldClient(spine_url)
    ids = c.collection_ids()
    assert {"silver.buildings", "silver.land_cover", "gold.cea.building_demand.demand"} <= set(ids)
    assert c.gold_collections("cea.building_demand", ids) == ["gold.cea.building_demand.demand"]
    fc = c.items("silver.buildings", limit=5)
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 5
    assert BASELINE in c.scenarios()


def test_analysis_gold_joins_hub_geometry(spine_url):
    g = analysis_gold(SpineGoldClient(spine_url), "building-energy-and-photovoltaics")
    demand = g["transforms"]["cea.building_demand"]
    assert demand["available"]
    fc = demand["collections"]["gold.cea.building_demand.demand"]
    assert len(fc["features"]) == 10
    assert all(f["geometry"] is not None for f in fc["features"])
    assert g["transforms"]["cea.solar_potential"] == {"collections": {}, "available": False}
    assert g["join_key"] == "building_id" and "bem-cea-bee" in g["replaces"]["processors"]


def test_external_analysis_reports_missing_gold(spine_url):
    g = analysis_gold(SpineGoldClient(spine_url), "mesoscale-urban-climate")
    assert g["transforms"]["duct.wrf_mesoscale"]["available"] is False and g["gap"]


def test_unknown_analysis(spine_url):
    with pytest.raises(KeyError):
        analysis_gold(SpineGoldClient(spine_url), "not-an-analysis")
