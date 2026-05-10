import Constants from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';

export const API_BASE: string =
  (Constants.expoConfig?.extra as any)?.API_BASE ?? 'http://localhost:8000';

export type Comparable = {
  source: string;
  market: 'ES' | 'DE' | 'FR' | 'IT' | 'PT' | 'NL' | 'AE' | 'UK';
  price_eur: number;
  km: number;
  year: number;
  url?: string;
};

export type Vehicle = {
  make: string;
  model: string;
  version?: string | null;
  year: number;
  km: number;
  fuel:
    | 'gasoline' | 'diesel' | 'hev' | 'mhev' | 'phev' | 'bev'
    | 'lpg' | 'cng' | 'hydrogen';
  power_cv?: number | null;
  co2_wltp?: number | null;
  euro_norm?: string | null;
  origin_country: string;
  has_coc?: boolean;
  has_service_book?: boolean;
  previous_owners?: number | null;
  declared_damages?: string | null;
};

export type AnalyzeRequest = {
  vehicle: Vehicle;
  origin: 'eu_auction' | 'eu_retail_pro' | 'eu_retail_pro_rebu' | 'eu_retail_private' | 'extra_eu';
  purchase_price: number;
  purchase_currency?: string;
  fx_rate_to_eur?: number;
  vat_regime?: 'rebu' | 'general' | 'import_extra_eu';
  canary_islands?: boolean;
  comparables: Comparable[];
};

const KEY_API_BASE = '@car_arbitrage/api_base';

export async function getApiBase(): Promise<string> {
  const stored = await AsyncStorage.getItem(KEY_API_BASE);
  return stored ?? API_BASE;
}

export async function setApiBase(url: string): Promise<void> {
  await AsyncStorage.setItem(KEY_API_BASE, url);
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const base = await getApiBase();
  const r = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`HTTP ${r.status}: ${text.slice(0, 240)}`);
  }
  return r.json();
}

export const analyze = (body: AnalyzeRequest) =>
  api<any>('/analyze', { method: 'POST', body: JSON.stringify(body) });

export const opportunities = (params: { min_margin?: number; max_risk?: number; limit?: number } = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v != null && qs.append(k, String(v)));
  return api<{ results: any[] }>(`/opportunities?${qs.toString()}`);
};

export const recent = (limit = 20) =>
  api<{ results: any[] }>(`/recent?limit=${limit}`);

export const notifyTelegram = (verdict: any, opts: { only_if_green?: boolean; min_margin_eur?: number } = {}) =>
  api<any>('/notify', {
    method: 'POST',
    body: JSON.stringify({ verdict, ...opts }),
  });

export const calibration = () => api<any>('/calibration');
