"""duct.bdp_conform: DUCT Base Data Package (Bronze) -> Silver buildings, districts, land_cover, id_bridge.

The DUCT-specific cleaning (geometry fixes, duplicate/non-polygon removal, default heights, building type from
land use, land cover from land use) is done by DUCT's own, unmodified importer
(server/explorer/bdp/bdp.py: DUCTBaseDataPackageDB.prepare_*). This adapter only reprojects to EPSG:3414 and
renames onto the spine Silver schema, and writes id_bridge rows for DUCT's ids.
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box, shape

SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
SILVER_CRS = "EPSG:3414"

FILES = {
    "city-admin-zones": "city-admin-zones.geojson",
    "land-use": "land-use.geojson",
    "building-footprints": "building-footprints.geojson",
    "lcz-baseline": "lcz-baseline.tif",
}

# Origin + resolution of DUCT's island-wide lcz-baseline grid (bdp/lcz-baseline); cell ids stay stable when cropped.
LCZ_GRID_X0, LCZ_GRID_Y0, LCZ_GRID_RES = 103.55044937133789, 1.5346527139218749, 0.0026931763

# DUCT LCZ raster legend (explorer/dots/duct_lcz.py): 31-40 = Stewart & Oke LCZ 1-10, 1-20 = MODIS IGBP classes.
# Silver lcz is 1-17 (LCZ A-G = 11-17); IGBP classes without an unambiguous LCZ equivalent map to null.
IGBP_TO_LCZ = {1: 11, 2: 11, 3: 11, 4: 11, 5: 11, 6: 13, 7: 13, 8: 12, 9: 12, 10: 14, 12: 14, 14: 14,
               16: 16, 17: 17}

# DUCT building types (explorer/dots/duct_urban_geometries.py BLD_CATEGORIES) -> Silver buildings.use_type.
USE_TYPE = {"residential": "RESIDENTIAL", "industrial": "INDUSTRIAL", "commercial:1": "OFFICE",
            "commercial:2": "HOTEL", "commercial:3": "RETAIL", "commercial:4": "RETAIL",
            "commercial:5": "RETAIL", "commercial:6": "SCHOOL", "commercial:7": "SCHOOL",
            "commercial:9": "HOSPITAL"}

TREE_TYPES = {"vegetation:4", "vegetation:5", "vegetation:6", "vegetation:7"}
GRASS_TYPES = {"vegetation:3", "vegetation:8"}


def _upstream():
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))
    from explorer.bdp.bdp import DUCTBaseDataPackageDB
    return DUCTBaseDataPackageDB


def _gdf(features, columns) -> gpd.GeoDataFrame:
    rows = [{c: f["properties"].get(c) for c in columns} for f in features]
    geoms = [shape(f["geometry"]) for f in features]
    return gpd.GeoDataFrame(rows, columns=columns, geometry=geoms, crs="EPSG:4326").to_crs(SILVER_CRS)


def _use_type(bld_type):
    if not isinstance(bld_type, str):
        return None
    return USE_TYPE.get(bld_type) or USE_TYPE.get(bld_type.split(":")[0], "OTHER")


def _lcz(value: int):
    if 31 <= value <= 40:
        return value - 30
    return IGBP_TO_LCZ.get(value)


def _district_of(gdf: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> pd.Series:
    pts = gpd.GeoDataFrame(geometry=gdf.geometry.representative_point(), crs=SILVER_CRS)
    joined = gpd.sjoin(pts, districts[["district_id", "geometry"]], how="left", predicate="within")
    return joined.groupby(level=0)["district_id"].first().reindex(gdf.index)


def _bridge(source, source_ids, hub, hub_ids, version) -> pd.DataFrame:
    return pd.DataFrame({"source": source, "source_id": [str(s) for s in source_ids], "hub": hub,
                         "hub_id": list(hub_ids), "match_method": "exact", "confidence": 1.0,
                         "source_version": version})


def _land_cover(tif: Path, landcover: gpd.GeoDataFrame, districts: gpd.GeoDataFrame, version: str):
    with rasterio.open(tif) as src:
        data, t, nodata = src.read(1), src.transform, src.nodata
    col0 = int(round((t.c - LCZ_GRID_X0) / LCZ_GRID_RES))
    row0 = int(round((LCZ_GRID_Y0 - t.f) / LCZ_GRID_RES))
    rows = []
    for r, c in zip(*np.nonzero(data != nodata)):
        x0, y1 = t @ (c, r)
        x1, y0 = t @ (c + 1, r + 1)
        v = int(data[r, c])
        rows.append({"cell_id": f"duct_lcz:{row0 + r}_{col0 + c}", "lcz": _lcz(v), "duct_lcz_value": v,
                     "geometry": box(x0, y0, x1, y1)})
    cells = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs(SILVER_CRS)
    cells["district_id"] = _district_of(cells, districts)
    cells = cells[cells.district_id.notna()].reset_index(drop=True)
    cells["lcz"] = cells["lcz"].astype("Int64")
    for col, types in (("tree_cover", TREE_TYPES), ("grass_cover", GRASS_TYPES)):
        veg = landcover[landcover.landcover_type.isin(types)]
        if veg.empty:
            cells[col] = 0.0
            continue
        inter = gpd.overlay(cells[["cell_id", "geometry"]], veg[["geometry"]], how="intersection",
                            keep_geom_type=True)
        covered = inter.dissolve(by="cell_id").area
        cells[col] = (cells.cell_id.map(covered).fillna(0.0) / cells.area).clip(0, 1).round(6)
    cells["source_version"] = version
    return cells[["cell_id", "district_id", "lcz", "tree_cover", "grass_cover", "duct_lcz_value",
                  "source_version", "geometry"]].sort_values("cell_id").reset_index(drop=True)


def run(inputs, params):
    bdp = Path(inputs["bdp"])
    missing = [n for n in FILES.values() if not (bdp / n).exists()]
    if missing:
        raise FileNotFoundError(f"duct_bdp package {bdp} is missing {missing}")
    vfile = bdp / "VERSION"
    version = params.get("source_version") or (vfile.read_text().strip() if vfile.exists() else bdp.name)
    db = _upstream()

    _, caz = db.prepare_city_admin_zones(str(bdp / FILES["city-admin-zones"]))
    lu_index, lu_features, lc_features = db.prepare_land_use_zoning(str(bdp / FILES["land-use"]))
    buildings_raw = db.prepare_building_footprints(str(bdp / FILES["building-footprints"]), lu_index, lu_features)

    caz_gdf = _gdf(list(caz.values()), ["id", "subzone_code", "planning_area_name"])
    districts = gpd.GeoDataFrame({
        "district_id": caz_gdf.subzone_code,
        "name": caz_gdf.subzone_code,
        "planning_area": caz_gdf.planning_area_name,
        "source_version": version,
    }, geometry=caz_gdf.geometry, crs=SILVER_CRS).sort_values("district_id").reset_index(drop=True)

    b = _gdf(buildings_raw, ["id", "name", "height", "building_type"])
    buildings = gpd.GeoDataFrame({
        "building_id": "osm:" + b["id"].astype(str),
        "plot_id": pd.Series([None] * len(b), dtype="string"),
        "height_m": b["height"].astype(float),
        "storeys": pd.array([pd.NA] * len(b), dtype="Int64"),
        "use_type": b["building_type"].map(_use_type),
        "year_built": pd.array([pd.NA] * len(b), dtype="Int64"),
        "duct_name": b["name"],
        "duct_building_type": b["building_type"],
        "source_version": version,
    }, geometry=b.geometry, crs=SILVER_CRS)
    buildings.insert(2, "district_id", _district_of(buildings, districts))
    buildings = buildings.sort_values("building_id").reset_index(drop=True)

    landcover = _gdf(lc_features, ["id", "landcover_type"])
    land_cover = _land_cover(bdp / FILES["lcz-baseline"], landcover, districts, version)

    id_bridge = pd.concat([
        _bridge("duct_bdp", b["id"], "building", "osm:" + b["id"].astype(str), version),
        _bridge("duct_caz", caz_gdf["id"], "district", caz_gdf.subzone_code, version),
    ], ignore_index=True).sort_values(["source", "source_id"]).reset_index(drop=True)

    return {"buildings": buildings, "districts": districts, "land_cover": land_cover, "id_bridge": id_bridge}
