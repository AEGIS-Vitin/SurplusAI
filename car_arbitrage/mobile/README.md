# Car Arbitrage Pro — App móvil (Expo / React Native)

App móvil que consume la API de `car_arbitrage/backend`.

## Setup

```bash
cd car_arbitrage/mobile
npm install      # o pnpm install
npx expo start   # arranca Metro bundler con QR para Expo Go
```

Para emular:

```bash
npx expo start --ios       # simulador iOS (requiere Xcode)
npx expo start --android   # emulador Android
npx expo start --web       # web (debug rápido)
```

## Configurar URL del backend

Tres opciones:

1. **Editar `app.json`** → `expo.extra.API_BASE` (recomendado para producción).
2. **Pantalla Ajustes** dentro de la app (URL persistida en AsyncStorage).
3. **Variable de entorno** en arranque:
   ```bash
   EXPO_PUBLIC_API_BASE=http://192.168.1.50:8000 npx expo start
   ```

URLs típicas:
- Simulador iOS: `http://127.0.0.1:8000`
- Emulador Android: `http://10.0.2.2:8000`
- Dispositivo real (mismo WiFi): `http://<IP-LAN-de-tu-Mac>:8000`
- Backend desplegado: `https://car-arbitrage.fly.dev`

## Builds nativos

EAS (Expo Application Services):

```bash
npm install -g eas-cli
eas login
eas build:configure
eas build --platform ios
eas build --platform android
eas submit --platform ios       # → App Store Connect
eas submit --platform android   # → Google Play Console
```

Costes:
- Apple Developer: 99 €/año
- Google Play: 25 € pago único
- EAS Build: tier gratuito 30 builds/mes

## Estructura

```
mobile/
├── App.tsx              # Stack navigator
├── app.json             # Config Expo (incluye API_BASE en extra)
├── package.json
├── tsconfig.json
├── babel.config.js
└── src/
    ├── api.ts           # Cliente HTTP de la API
    ├── format.ts        # Helpers €/% /días
    └── screens/
        ├── HomeScreen.tsx     # Form vehículo + veredicto + escenarios
        └── SettingsScreen.tsx # URL del backend
```
