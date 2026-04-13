# AEGIS-FOOD Quick Start Guide

## 🚀 Start the Platform in 3 Commands

```bash
cd /sessions/busy-optimistic-gauss/mnt/empresa-ia/marketplace-excedentes
docker-compose up --build
```

Wait 30 seconds for services to initialize, then open:
- **Frontend Dashboard**: http://localhost/
- **API Swagger Docs**: http://localhost:8000/docs

## 📋 Sample Data Included

The database auto-initializes with:

### Generadores (Sellers)
1. **Carrefour Madrid** (ID: 1) - Retail supermarket
2. **Mercadona Barcelona** (ID: 2) - Retail chain
3. **La Boquería Valencia** (ID: 3) - Primary market
4. **El Patio Sevilla** (ID: 4) - Restaurant
5. **Industria Murcia** (ID: 5) - Food processor

### Receptores (Buyers)
1. **Banco de Alimentos Madrid** (ID: 1) - Food bank
2. **Transformadora Barcelona** (ID: 2) - Food processor
3. **Biofeed Piensos** (ID: 3) - Animal feed producer
4. **Compost Plus** (ID: 4) - Composting facility
5. **Biogás Verde** (ID: 5) - Biogas plant

### Sample Lots
- 150 kg Manzanas (€0.50/kg base)
- 80 kg Lechuga (€0.35/kg base)
- 45 kg Queso Fresco (€4.50/kg base)
- 60 kg Costillas (€6.00/kg base)
- 200 kg Pan Integral (€0.70/kg base)

## 🎯 Try These Workflows

### 1. Generator Publishing a Lot
1. Open **Generador** tab
2. Enter ID: `1` (Carrefour)
3. Fill in:
   - Product: "Tomates Ecológicos"
   - Category: "Verduras"
   - Quantity: "200" kg
   - Price: "0.45" EUR
   - Latitude: "40.4168"
   - Longitude: "-3.7038"
   - Expiry: Tomorrow at 18:00
4. Click **"Publicar Lote"**
5. Note the lot ID returned

### 2. Receiver Finding Lots
1. Open **Receptor** tab
2. Select Category: "Verduras"
3. Set Max Price: "1.00"
4. Click **"Buscar Lotes"**
5. View available lots with prices & supply info

### 3. Place a Bid
1. In **Receptor** tab
2. Lot ID: Use the ID from step 1
3. Receptor ID: `1` (Banco de Alimentos)
4. Price Offer: "0.35" EUR
5. Use: "Donación para Consumo Humano" (donation)
6. Click **"Realizar Oferta"**

### 4. Check Price Dynamics
1. In **Generador** tab
2. Select Category: "Frutas"
3. Enter Quantity: "500" kg
4. Click **"Sugerir Precio"**
5. See automatic price suggestions

### 5. View Dashboard
1. Open **Dashboard** tab
2. See metrics:
   - Total kg saved
   - CO2 avoided
   - Money transacted
   - Active participants

## 🔌 API Testing (curl)

### Create a Lot
```bash
curl -X POST http://localhost:8000/lots \
  -H "Content-Type: application/json" \
  -d '{
    "generador_id": 1,
    "producto": "Fresas Frescas",
    "categoria": "frutas",
    "cantidad_kg": 100,
    "ubicacion_lat": 40.4168,
    "ubicacion_lon": -3.7038,
    "fecha_limite": "2025-04-14T18:00:00",
    "precio_base": 1.50
  }'
```

### Search Lots
```bash
curl "http://localhost:8000/lots?categoria=frutas&precio_max=2.0&radio_km=50"
```

### Place a Bid
```bash
curl -X POST http://localhost:8000/bids \
  -H "Content-Type: application/json" \
  -d '{
    "lote_id": 1,
    "receptor_id": 1,
    "precio_oferta": 1.20,
    "uso_previsto": 2,
    "mensaje": "Excelente para nuestro banco de alimentos"
  }'
```

### View Compliance Hierarchy
```bash
curl http://localhost:8000/compliance-hierarchy
```

### Get Dashboard Stats
```bash
curl http://localhost:8000/stats
```

### Get Price Suggestions
```bash
curl "http://localhost:8000/price-suggestion?categoria=frutas&cantidad_kg=100&tipo_generador=retail"
```

## 🐛 Troubleshooting

### Services won't start
```bash
# Check if ports are in use
lsof -i :8000 -i :5432 -i :80

# Kill conflicting processes
docker-compose down -v  # Remove volumes too
docker system prune -a  # Clean up Docker
docker-compose up --build
```

### Database connection errors
```bash
# Check PostgreSQL logs
docker-compose logs db

# Restart database
docker-compose restart db
```

### Frontend showing blank page
```bash
# Clear browser cache (Ctrl+Shift+Delete)
# Or use incognito window
# Check if backend is running: curl http://localhost:8000/health
```

### API errors with CORs
```bash
# CORS is already configured in FastAPI
# If still issues, check frontend/nginx.conf
# and main.py CORS middleware
```

## 📊 Key Metrics Explained

### CO2 Saved
- **Carnes**: 27 kg CO2e per kg product
- **Pescados**: 12 kg CO2e per kg
- **Lácteos**: 2.5 kg CO2e per kg
- **Verduras**: 0.6 kg CO2e per kg

Example: 60 kg beef = 1,620 kg CO2e avoided (=7,000 km driving)

### Dynamic Pricing Formula
```
Precio = Base × (Días_Restantes / Días_Totales) × Factor_Demanda × Factor_Escasez

Mín: 10% del precio base
Máx: Precio base
```

### Legal Use Hierarchy (Ley 1/2025)
1. ✅ **Before best-before**: All uses allowed (1-7)
2. ⚠️ **After best-before**: Limited uses (4-7)
3. 🔴 **Before expiry**: Only compost/biogas (6-7)
4. 💀 **After expiry**: Only disposal (8)

## 🎨 Frontend Tabs

### Generador (Seller)
- Publish new lots
- View your published lots
- Get buyer recommendations
- See price suggestions

### Receptor (Buyer)
- Search available lots
- Place bids with compliance checks
- View bid history
- See legal use hierarchy

### Admin (Dashboard)
- Global metrics (kg, CO2, money)
- Participant stats
- Carbon impact by category
- Top generators & receivers

## ⚡ Performance Tips

1. **Search with filters** to reduce results
2. **Set reasonable radius** (50km default)
3. **Check lots before expiry** (price drops daily)
4. **Use price suggestions** to stay competitive
5. **Monitor matching recommendations** for best buyers

## 🔐 Security Features

- ✅ Input validation on all fields
- ✅ SQL injection prevention
- ✅ CORS properly configured
- ✅ Nginx security headers
- ✅ Environment variables for secrets
- ✅ Database constraints & foreign keys

## 📱 Browser Support

- Chrome/Chromium 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome Mobile)

## 🔗 Important URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Frontend | http://localhost/ | Dashboard |
| Swagger API | http://localhost:8000/docs | API testing |
| ReDoc API | http://localhost:8000/redoc | API docs |
| PostgreSQL | localhost:5432 | Database |
| Redis | localhost:6379 | Cache |

## 📚 Next Steps

1. **Explore the data**: Check out sample lots in Receptor tab
2. **Try bidding**: Place offers on different products
3. **Check compliance**: Click "Ver Jerarquía" to understand legal rules
4. **Read API docs**: Visit http://localhost:8000/docs
5. **Review code**: Check backend/main.py for 17 endpoints

## ❓ FAQ

**Q: How often do prices update?**
A: Every time a bid is placed, prices recalculate instantly based on demand.

**Q: Can I use real money?**
A: This MVP doesn't have payment integration yet. For production, integrate Stripe/PayPal.

**Q: How is CO2 calculated?**
A: Based on published lifecycle analysis (LCA) data per food category, adjusted by final use.

**Q: What if product is expired?**
A: System automatically restricts uses. Only composting/biogas/disposal allowed after expiry.

**Q: How do matches work?**
A: ML engine learns from past transactions, recommends buyers with similar history & capacity.

**Q: Can I customize categories?**
A: Currently fixed 8 categories. Easily extendable by modifying Categoria enum in models.py.

---

**Ready to go!** Questions? Check README.md or explore the code.
