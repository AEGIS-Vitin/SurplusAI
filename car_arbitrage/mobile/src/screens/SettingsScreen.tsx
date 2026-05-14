import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getApiBase, setApiBase } from '../api';

export default function SettingsScreen() {
  const [apiBase, setApiBaseState] = useState('');

  useEffect(() => {
    getApiBase().then(setApiBaseState);
  }, []);

  const save = async () => {
    await setApiBase(apiBase.trim());
    Alert.alert('Guardado', `API_BASE = ${apiBase}`);
  };

  return (
    <SafeAreaView style={styles.flex}>
      <View style={styles.container}>
        <Text style={styles.title}>Ajustes</Text>
        <Text style={styles.label}>URL del backend</Text>
        <TextInput
          style={styles.input}
          value={apiBase}
          onChangeText={setApiBaseState}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="https://car-arbitrage.fly.dev"
        />
        <Text style={styles.hint}>
          Para desarrollo local en simulador iOS: http://127.0.0.1:8000{'\n'}
          Para Android emulator: http://10.0.2.2:8000{'\n'}
          Para dispositivo real (mismo WiFi): http://&lt;IP-LAN&gt;:8000
        </Text>
        <TouchableOpacity style={styles.btn} onPress={save}>
          <Text style={styles.btnText}>Guardar</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: '#f8fafc' },
  container: { padding: 16 },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 16 },
  label: { fontSize: 12, color: '#64748b', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 8, padding: 10, backgroundColor: 'white' },
  hint: { fontSize: 12, color: '#64748b', marginTop: 8, lineHeight: 18 },
  btn: { backgroundColor: '#2563eb', padding: 14, borderRadius: 10, alignItems: 'center', marginTop: 16 },
  btnText: { color: 'white', fontWeight: '600' },
});
