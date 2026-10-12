import axios from 'axios';
import {
  SpineAnalyses,
  SpineAnalysisGold,
  SpineFeatureCollection,
} from './spine-gold.model';

// Read analysis results as Gold from sg-urban-spine (`spine serve`, OGC API Features), proxied by the Explorer
// server in spine mode (rewire/explorer_gold/service.py). Analyses are not submitted to DUCT processors.
export const getSpineAnalyses = () =>
  axios.get<SpineAnalyses>('/spine/analyses').then((r) => r.data);

export const getSpineAnalysisGold = (
  analysisType: string,
  scenario?: string,
  limit?: number
) =>
  axios
    .get<SpineAnalysisGold>(`/spine/analysis/${analysisType}`, {
      params: { scenario, limit },
    })
    .then((r) => r.data);

export const getSpineCollectionItems = (
  collectionId: string,
  scenario?: string,
  limit?: number
) =>
  axios
    .get<SpineFeatureCollection>(`/spine/collections/${collectionId}/items`, {
      params: { scenario, limit },
    })
    .then((r) => r.data);
