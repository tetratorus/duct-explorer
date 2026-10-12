"""Build a small Bronze `duct_bdp` package from the full DUCT BDP + URA Master Plan 2019 downloads.

Selects MP2019 subzones, keeps DUCT building footprints whose centroid falls inside them, clips MP2019
land use to them, crops the DUCT LCZ raster, and writes the files under the names DUCT's own
BDP importer expects. MP2019 properties from data.gov.sg are plain columns; DUCT's importer parses the
KML-style HTML `Description` attribute, so the properties are re-wrapped in that format (data format
only; no values change).

    python rewire/bronze/make_fixture.py --bdp bdp --subzones subzones.geojson --landuse landuse.geojson \
        --codes QTSZ03,QTSZ04 --out rewire/duct.bdp_conform/golden/queenstown/inputs/bdp
"""
import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import rasterio
import shapely
from rasterio.windows import Window, from_bounds
from shapely.geometry import mapping


def _description(props: dict) -> str:
    rows = "".join(f"<tr><th>{k}</th><td>{'' if v is None else v}</td></tr>" for k, v in props.items())
    return f"<center><table>{rows}</table></center>"


def _write(gdf: gpd.GeoDataFrame, path: Path, wrap: bool) -> None:
    features = []
    for _, row in gdf.iterrows():
        props = {k: (None if (isinstance(v, float) and v != v) else v)
                 for k, v in row.drop(labels="geometry").items()}
        geom = json.loads(json.dumps(mapping(row.geometry)))
        features.append({"type": "Feature",
                         "properties": {"Description": _description(props)} if wrap else props,
                         "geometry": geom})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def build(bdp: Path, subzones: Path, landuse: Path, codes: list[str], out: Path, version: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    sz = gpd.read_file(subzones).to_crs(4326)
    sz = sz[sz.SUBZONE_C.isin(codes)].sort_values("SUBZONE_C")
    area = sz.unary_union
    _write(sz, out / "city-admin-zones.geojson", wrap=True)

    lu = gpd.read_file(landuse, bbox=tuple(area.bounds)).to_crs(4326)
    lu = lu[lu.intersects(area)].copy()
    lu["geometry"] = lu.intersection(area)
    lu = lu[lu.geom_type.isin(["Polygon", "MultiPolygon"]) & ~lu.is_empty].sort_values("OBJECTID")
    lu["geometry"] = shapely.set_precision(lu.geometry.values.data, 1e-7)
    lu = lu[lu.is_valid & ~lu.is_empty]
    _write(lu, out / "land-use.geojson", wrap=True)

    bf = gpd.read_file(bdp / "building-footprints")
    bf = bf[bf.representative_point().within(area)].sort_values("id")
    _write(bf, out / "building-footprints.geojson", wrap=False)

    with rasterio.open(bdp / "lcz-baseline") as src:
        w = from_bounds(*area.bounds, transform=src.transform)
        col0, row0 = math.floor(w.col_off), math.floor(w.row_off)
        win = Window(col0, row0, math.ceil(w.col_off + w.width) - col0 + 1, math.ceil(w.row_off + w.height) - row0 + 1)
        data = src.read(window=win)
        profile = src.profile | {"width": data.shape[2], "height": data.shape[1],
                                 "transform": src.window_transform(win), "driver": "GTiff"}
    with rasterio.open(out / "lcz-baseline.tif", "w", **profile) as dst:
        dst.write(data)
    (out / "VERSION").write_text(version + "\n")
    print(f"{out}: {len(sz)} subzones, {len(lu)} land-use, {len(bf)} buildings, lcz {data.shape[1:]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bdp", type=Path, required=True)
    ap.add_argument("--subzones", type=Path, required=True)
    ap.add_argument("--landuse", type=Path, required=True)
    ap.add_argument("--codes", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--version", default="duct-bdp-sg+mp2019")
    a = ap.parse_args()
    build(a.bdp, a.subzones, a.landuse, a.codes.split(","), a.out, a.version)
