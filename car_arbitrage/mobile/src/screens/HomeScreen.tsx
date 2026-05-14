import React, { useState } from 'react';
import {
  View, Text, TextInput, ScrollView, StyleSheet, TouchableOpacity,
  Alert, ActivityIndicator, Switch,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { analyze, AnalyzeRequest, Comparable, notifyTelegram } from '../api';
import { fmtEur, fmtPct, fmtDays } from '../format';

export default function HomeScreen({ navigation }: any) {
  const [make, setMake] = useState('BMW');
  const [model, setModel] = useState('Serie 3');
  const [version, setVersion] = useState('320d');
  const [year, setYear] = useState('2020');
  const [km, setKm] = useState('95000');
  const [fuel, setFuel] = useState<'diesel' | 'gasoline' | 'bev' | 'hev' | 'phev'>('diesel');
  const [co2, setCo2] = useState('145');
  const [origin, setOrigin] = useState('DE');
  const [price, setPrice] = useState('14500');
  const [currency, setCurrency] = useState('EUR');
  const [channel, setChannel] = useState<AnalyzeRequest['origin']>('eu_auction');
  const [vat, setVat] = useState<'rebu' | 'general' | 'import_extra_eu'>('rebu');
  const [comps, setComps] = useState<Comparable[]>([
    { source: 'coches.net', market: 'ES', price_eur: 22500, km: 88000, year: 2020 },
    { source: 'coches.net', market: 'ES', price_eur: 21000, km: 105000, year: 2020 },
    { source: 'coches.net', market: 'ES', price_eur: 23500, km: 75000, year: 2021 },
    { source: 'autoscout24.es', market: 'ES', price_eur: 22000, km: 92000, year: 2020 },
    { source: 'autoscout24.es', market: 'ES', price_eur: 24000, km: 70000, year: 2021 },
  ]);
  const [loading, setLoading] = useState(false);
  const [verdict, setVerdict] = useState<any>(null);

  const onAnalyze = async () => {
    setLoading(true);
    try {
      const body: AnalyzeRequest = {
        vehicle: {
          make, model, version, year: Number(year), km: Number(km),
          fuel, co2_wltp: co2 ? Number(co2) : null,
          origin_country: origin.toUpperCase(),
          has_coc: true, has_service_book: true,
        },
        origin: channel,
        purchase_price: Number(price),
        purchase_currency: currency,
        vat_regime: vat,
        comparables: comps,
      };
      const r = await analyze(body);
      setVerdict(r);
    } catch (e: any) {
      Alert.alert('Error', e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  const onNotify = async () => {
    if (!verdict) return;
    try {
      const r = await notifyTelegram(verdict);
      Alert.alert(r.ok ? '✓ Telegram enviado' : '⚠️ Telegram', JSON.stringify(r, null, 2));
    } catch (e: any) {
      Alert.alert('Error', e.message ?? String(e));
    }
  };

  return (
    <SafeAreaView style={styles.flex}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.headerRow}>
          <Text style={styles.title}>🚗 Car Arbitrage Pro</Text>
          <TouchableOpacity onPress={() => navigation.navigate('Settings')}>
            <Text style={styles.link}>⚙</Text>
          </TouchableOpacity>
        </View>

        <Section title="Vehículo">
          <Row><Field label="Marca" value={make} onChange={setMake} /><Field label="Modelo" value={model} onChange={setModel} /></Row>
          <Row><Field label="Versión" value={version} onChange={setVersion} /><Field label="Año" value={year} onChange={setYear} kb="numeric" /></Row>
          <Row><Field label="Km" value={km} onChange={setKm} kb="numeric" /><Field label="CO₂ WLTP" value={co2} onChange={setCo2} kb="numeric" /></Row>
          <Row><Field label="País origen" value={origin} onChange={setOrigin} /><Field label="Combustible" value={fuel} onChange={(v: any) => setFuel(v)} /></Row>
        </Section>

        <Section title="Compra">
          <Row><Field label="Precio" value={price} onChange={setPrice} kb="numeric" /><Field label="Moneda" value={currency} onChange={setCurrency} /></Row>
          <Row><Field label="Canal" value={channel} onChange={(v: any) => setChannel(v)} /><Field label="Régimen IVA" value={vat} onChange={(v: any) => setVat(v)} /></Row>
        </Section>

        <Section title={`Comparables (${comps.length})`}>
          {comps.map((c, i) => (
            <Text key={i} style={styles.compRow}>
              {c.source} · {c.market} · {fmtEur(c.price_eur)} · {c.km.toLocaleString()} km · {c.year}
            </Text>
          ))}
        </Section>

        <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={onAnalyze} disabled={loading}>
          {loading ? <ActivityIndicator color="white" /> : <Text style={styles.btnText}>Analizar rentabilidad</Text>}
        </TouchableOpacity>

        {verdict && (
          <View style={styles.card}>
            <Text style={styles.verdict}>{verdict.label}</Text>
            <Text style={styles.veh}>{verdict.summary?.vehicle}</Text>
            <View style={styles.statsGrid}>
              <Stat label="Venta recom." value={fmtEur(verdict.summary?.recommended_sale_eur)} />
              <Stat label="Margen" value={fmtEur(verdict.summary?.expected_margin_eur)} />
              <Stat label="ROI an." value={fmtPct(verdict.summary?.annualized_roi_pct)} />
              <Stat label="Días vender" value={fmtDays(verdict.summary?.expected_days_to_sell)} />
              <Stat label="Velocidad" value={verdict.summary?.velocity ?? '—'} />
              <Stat label="Riesgo" value={`${verdict.summary?.risk_label} (${verdict.summary?.risk_score})`} />
              <Stat label="Puja máx" value={fmtEur(verdict.summary?.max_bid_eur)} />
              <Stat label="Prob pérdida" value={fmtPct(verdict.monte_carlo?.prob_loss)} />
            </View>

            <Text style={styles.h2}>Escenarios</Text>
            {(verdict.scenarios || []).map((s: any, i: number) => (
              <View key={i} style={styles.scen}>
                <Text style={styles.scenName}>{s.label}</Text>
                <Text style={styles.scenDetail}>
                  {fmtEur(s.sale_price_eur)} · {fmtDays(s.days_to_sell)} · margen {fmtEur(s.margin_eur)} · ROI {fmtPct(s.annualized_roi_pct)}
                </Text>
              </View>
            ))}

            <TouchableOpacity style={styles.btnSecondary} onPress={onNotify}>
              <Text style={styles.btnText}>📨 Notificar Telegram</Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const Section = ({ title, children }: any) => (
  <View style={styles.section}>
    <Text style={styles.h2}>{title}</Text>
    {children}
  </View>
);

const Row = ({ children }: any) => <View style={styles.row}>{children}</View>;

const Field = ({ label, value, onChange, kb }: any) => (
  <View style={styles.fieldWrap}>
    <Text style={styles.fieldLabel}>{label}</Text>
    <TextInput style={styles.input} value={String(value)} onChangeText={onChange} keyboardType={kb} autoCapitalize="none" />
  </View>
);

const Stat = ({ label, value }: any) => (
  <View style={styles.stat}>
    <Text style={styles.statLabel}>{label}</Text>
    <Text style={styles.statValue}>{value}</Text>
  </View>
);

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: '#f8fafc' },
  container: { padding: 16, paddingBottom: 64 },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 },
  title: { fontSize: 22, fontWeight: '700', color: '#0f172a' },
  link: { fontSize: 22 },
  section: { backgroundColor: 'white', borderRadius: 12, padding: 12, marginBottom: 12 },
  h2: { fontSize: 14, fontWeight: '600', marginBottom: 6, color: '#475569' },
  row: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  fieldWrap: { flex: 1 },
  fieldLabel: { fontSize: 11, color: '#64748b', marginBottom: 2 },
  input: { borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 8, padding: 8, backgroundColor: 'white' },
  compRow: { fontSize: 12, color: '#475569', marginVertical: 2 },
  btn: { backgroundColor: '#2563eb', padding: 14, borderRadius: 10, alignItems: 'center', marginTop: 8 },
  btnSecondary: { backgroundColor: '#0891b2', padding: 12, borderRadius: 10, alignItems: 'center', marginTop: 12 },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: 'white', fontWeight: '600' },
  card: { backgroundColor: 'white', borderRadius: 12, padding: 16, marginTop: 12 },
  verdict: { fontSize: 24, fontWeight: '700' },
  veh: { color: '#475569', marginBottom: 12 },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  stat: { width: '48%', backgroundColor: '#f1f5f9', padding: 10, borderRadius: 8 },
  statLabel: { fontSize: 11, color: '#64748b' },
  statValue: { fontSize: 14, fontWeight: '600', color: '#0f172a' },
  scen: { backgroundColor: '#f8fafc', borderLeftWidth: 3, borderLeftColor: '#2563eb', padding: 8, marginBottom: 6, borderRadius: 4 },
  scenName: { fontWeight: '600', color: '#0f172a' },
  scenDetail: { fontSize: 12, color: '#475569', marginTop: 2 },
});
