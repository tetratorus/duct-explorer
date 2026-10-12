import json
import subprocess
import sys
from pathlib import Path

import pytest
from spine.validate import check_silver

REWIRE = Path(__file__).resolve().parents[1]
CASE = REWIRE / "duct.bdp_conform" / "golden" / "queenstown"
BDP = CASE / "inputs" / "bdp"


@pytest.fixture(scope="module")
def out():
    import adapter
    return adapter.run({"bdp": BDP}, {})


def test_spine_validate_and_golden():
    for cmd in ("validate", "test"):
        r = subprocess.run([sys.executable, "-m", "spine.cli", "--path", str(REWIRE), cmd, "duct.bdp_conform"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("table", ["buildings", "districts", "land_cover", "id_bridge"])
def test_outputs_conform_to_silver(out, table):
    check_silver(table, out[table])


def test_every_duct_building_is_bridged(out):
    bridge = out["id_bridge"]
    b = bridge[bridge.source == "duct_bdp"]
    assert set(b.hub_id) == set(out["buildings"].building_id)
    assert (b.hub == "building").all() and b.source_id.is_unique
    raw_ids = {str(f["properties"]["id"]) for f in json.loads((BDP / "building-footprints.geojson").read_text())["features"]}
    assert set(b.source_id) <= raw_ids


def test_districts_and_links(out):
    d = out["districts"]
    assert sorted(d.district_id) == ["QTSZ03", "QTSZ04"]
    assert set(out["buildings"].district_id.dropna()) <= set(d.district_id)
    assert out["buildings"].district_id.notna().all()
    caz = out["id_bridge"][out["id_bridge"].source == "duct_caz"]
    assert set(caz.hub_id) == set(d.district_id)


def test_land_cover_values(out):
    lc = out["land_cover"]
    assert lc.lcz.dropna().between(1, 17).all()
    assert lc.tree_cover.between(0, 1).all() and lc.grass_cover.between(0, 1).all()
    assert lc.cell_id.str.match(r"^duct_lcz:\d+_\d+$").all()


def test_missing_file_is_reported(tmp_path):
    import adapter
    with pytest.raises(FileNotFoundError, match="lcz-baseline.tif"):
        for f in BDP.iterdir():
            if f.name != "lcz-baseline.tif":
                (tmp_path / f.name).write_bytes(f.read_bytes())
        adapter.run({"bdp": tmp_path}, {})
