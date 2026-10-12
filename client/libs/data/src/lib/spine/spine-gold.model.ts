// Minimal GeoJSON shape returned by OGC API Features (EPSG:4326).
export interface SpineFeatureCollection {
  type: 'FeatureCollection';
  features: {
    type: 'Feature';
    id?: string | number;
    geometry: { type: string; coordinates: unknown } | null;
    properties: Record<string, unknown>;
  }[];
  numberReturned?: number;
  scenario?: string;
}

export interface SpineGoldTransform {
  available: boolean;
  collections: Record<string, SpineFeatureCollection | null>;
}

export interface SpineAnalysisGold {
  analysis_type: string;
  scenario: string | null;
  join_key: string | null;
  replaces: { processors?: string[]; results?: string[] };
  gap: string | null;
  transforms: Record<string, SpineGoldTransform>;
  silver: string[];
}

export type SpineAnalyses = Record<string, Record<string, string[]>>;
