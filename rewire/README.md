# rewire/: DUCT Explorer on the sg-urban-spine

This directory plugs DUCT Explorer into [sg-urban-spine](https://github.com/tetratorus/sg-urban-spine) ("Rewire, don't
rewrite"). It follows [spec/LAYERS.md](https://github.com/tetratorus/sg-urban-spine/blob/main/spec/LAYERS.md).
DUCT's own code (`server/explorer/**`) is not modified.

Install (Python 3.10; the DUCT server does not support newer versions):

```bash
python3.10 -m venv venv && . venv/bin/activate
pip install -r server/requirements.txt && pip install -e server
pip install 'git+https://github.com/tetratorus/sg-urban-spine@main'
```

## Layout

| Path | What it is |
|---|---|
| `duct.bdp_conform/` | Conformer (Bronze -> Silver): DUCT base data package -> silver `buildings`, `districts`, `land_cover`, `id_bridge` |
| `duct.bdp_conform/golden/queenstown/` | Golden case: Queenstown subzones QTSZ03 + QTSZ04 (140 buildings, 81 land-use parcels, 8 LCZ cells) |
| `bronze/make_fixture.py` | Builds a `duct_bdp` Bronze package (or the golden fixture) from the full BDP + URA MP2019 downloads |
| `explorer_gold/gold_map.yaml` | Which Gold outputs (spine transform ids) each Explorer analysis reads |
| `explorer_gold/spine_gold.py` | OGC API Features client for `spine serve` + `analysis_gold()` |
| `explorer_gold/server_ext.py`, `service.py` | Server option: Explorer server with `/spine/*` endpoints that read Gold instead of running DUCT processors |
| `tests/` | pytest: golden + Silver contract checks, id_bridge coverage, OGC client against a live `spine serve`, server option |

## Run

```bash
cd rewire
spine --path . validate duct.bdp_conform
spine --path . test duct.bdp_conform          # golden
pytest tests                                  # from rewire/ or repo root
# full package -> lake
spine bronze-add duct_bdp <version> <files...> --url <source> --license <licence>
spine --path . run duct.bdp_conform
```

## duct.bdp_conform

DUCT's own importer does the DUCT-specific cleaning: `DUCTBaseDataPackageDB.prepare_city_admin_zones`,
`prepare_land_use_zoning` and `prepare_building_footprints` in `server/explorer/bdp/bdp.py`. It fixes geometry,
drops duplicate and non-polygon footprints, applies the 10 m default height, and assigns building and land-cover
types from MP2019 land use. `adapter.py` calls those functions unchanged. It then only reprojects to EPSG:3414 and
renames columns:

| Silver | From DUCT | Hub key |
|---|---|---|
| `districts` | city-admin-zones (MP2019 subzones) | `district_id` = MP2019 `SUBZONE_C` (e.g. `QTSZ03`) |
| `buildings` | building-footprints (OSM) after DUCT cleaning; `use_type` from DUCT `building_type`; `district_id` = subzone containing the footprint | `building_id` = `osm:<DUCT id>` |
| `land_cover` | `lcz-baseline` raster cells (~300 m); `lcz` 1-17; `tree_cover` / `grass_cover` = area share of DUCT's land-use-derived vegetation land cover | `cell_id` = `duct_lcz:<row>_<col>` on DUCT's island-wide grid |
| `id_bridge` | `source=duct_bdp` (DUCT building id -> building), `source=duct_caz` (DUCT admin-zone id -> district) | GERS-style bridge, `match_method=exact` |

The Bronze package is one directory with `city-admin-zones.geojson`, `land-use.geojson`, `building-footprints.geojson`,
`lcz-baseline.tif` and an optional `VERSION` (used as `source_version`). The bundled `bdp/building-footprints` and
`bdp/lcz-baseline` are used as-is. Subzones and land use come from data.gov.sg (URA MP2019:
`d_8594ae9ff96d0c708bc2af633048edfb`, `d_90d86daa5bfaa371668b84fa5f01424f`). `make_fixture.py` re-wraps their
attributes into the KML-style `Description` HTML that DUCT's importer parses. Only the format changes; the values
are the same.

Golden: `expected/*.parquet` was recorded with `spine freeze` from the unmodified upstream importer on that fixture.

## Explorer analyses -> Gold (`explorer_gold/gold_map.yaml`)

| Explorer analysis | DUCT processors it would run | Gold it reads (transform id from LAYERS.md) | Join key |
|---|---|---|---|
| building-energy-and-photovoltaics | bem-cea-gen, bem-cea-bee | `cea.building_demand`, `cea.solar_potential` | building_id |
| district-cooling | bem-cea-gen, bem-cea-dcn | `cea.building_demand` (network optimisation has no spine id yet, see gap) | building_id |
| mesoscale-urban-climate | ucm-wrf-prep, ucm-wrf-sim | `duct.wrf_mesoscale` (external/HPC) | cell_id |
| microscale-urban-climate | ucm-palm-prep, ucm-palm-sim | `duct.palm_microscale` (external/HPC) | cell_id |
| wind-corridor-potential | ucm-mva-uwc, ucm-mva-uvp | `duct.mva_wind_corridor` | cell_id |

All analyses share Silver `buildings` / `districts` / `land_cover` from `duct.bdp_conform`. Gold table names belong
to the repos that own those transforms (duct-fom, CityEnergyAnalyst). The client therefore discovers every
`gold.<transform_id>.<table>` collection at runtime and does not hard-code table names.

## Spine mode (client/server option)

```bash
spine serve --port 8090                                     # Silver + Gold as OGC API Features
EXPLORER_SPINE_URL=http://127.0.0.1:8090 \
  python rewire/explorer_gold/service.py service [usual explorer service args]
```

`service.py` runs the normal `explorer` CLI, but with `SpineGoldExplorerServer`: the upstream `ExplorerServer` plus
these endpoints, which use the same prefix and user auth:

- `GET /explorer/v1/spine/analyses`: analysis -> transform ids -> Gold collections available now
- `GET /explorer/v1/spine/analysis/{analysis_type}?scenario=&limit=`: Gold FeatureCollections (hub geometry joined by `spine serve`)
- `GET /explorer/v1/spine/collections/{collection_id}/items?scenario=&limit=`: proxied OGC items (only `silver.*` / `gold.*`)

The client calls these endpoints through `getSpineAnalyses`, `getSpineAnalysisGold` and `getSpineCollectionItems`
in `client/libs/data/src/lib/spine/`. Without `EXPLORER_SPINE_URL` / `service.py`, Explorer works exactly as before
and runs DUCT processors through the SaaS node.

## Changes outside rewire/

No change under `server/`. The client additions are new files only, and they do not touch the science:

- `client/libs/data/src/lib/spine/spine-gold.{model,service}.ts`: typed calls to the `/spine/*` endpoints
- `client/libs/data/src/index.ts`: two export lines for those files

## Gaps (also in transform.yaml `readiness`)

- Only the 2-subzone fixture was run. The full island-wide BDP (110k buildings) was not.
- The existing views (`review`, `compare`) still call the original `/result/...` endpoints. No UI screen uses the
  spine service functions yet.
- Upstream server tests (`server/tests`) need a SaaS node, `TEST_DATA_PATH` and GitHub credentials (`.env`), so they
  were not run here.
- Vegetation (Trees.sg) and anthropogenic-heat profiles are not conformed. Silver has no table for them.
- District-cooling network results (`supply_systems`) need a CEA network transform id in LAYERS.md.
