"""
Predictive matching module for connecting generators and receivers.
Uses basic collaborative filtering and category matching.
"""

from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import math


class MatchingEngine:
    """Engine for predicting best matches between generators and receivers"""

    def __init__(self, db_session):
        """
        Initialize matching engine with database session

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session

    def get_recommended_matches(
        self,
        generador_id: int,
        limit: int = 5
    ) -> List[Dict]:
        """
        Get recommended receivers for a generator based on history.

        Strategy:
        1. Look at past transactions for this generator
        2. Find receivers who bought similar products
        3. Consider geographic proximity
        4. Score by capacity, category fit, and frequency

        Args:
            generador_id: Generator ID
            limit: Max number of recommendations

        Returns:
            List of match dicts with scoring
        """

        from database import TransaccionDB, ReceptorDB, LoteDB

        # Get generator's transaction history
        transacciones = self.db.query(TransaccionDB).filter(
            TransaccionDB.generador_id == generador_id
        ).all()

        if not transacciones:
            return []

        # Extract unique receivers from past transactions
        receptores_ids = set(t.receptor_id for t in transacciones)

        # Get categories and products from history
        categorias_compradas = {}
        for trans in transacciones:
            lote = self.db.query(LoteDB).filter(LoteDB.id == trans.lote_id).first()
            if lote:
                cat = lote.categoria
                categorias_compradas[cat] = categorias_compradas.get(cat, 0) + 1

        # Find other receptores interested in these categories
        receptores = self.db.query(ReceptorDB).filter(
            ReceptorDB.id.notin_(receptores_ids)
        ).all()

        matches = []
        for receptor in receptores:
            score = self._calculate_match_score(
                generador_id,
                receptor,
                categorias_compradas,
                transacciones
            )

            if score > 0:
                matches.append({
                    "receptor_id": receptor.id,
                    "receptor_nombre": receptor.nombre,
                    "score_match": score,
                    "tipo_receptor": receptor.tipo.value,
                    "categorias_interes": receptor.categorias_interes or []
                })

        # Sort by score descending
        matches.sort(key=lambda x: x["score_match"], reverse=True)

        return matches[:limit]

    def predict_next_surplus(
        self,
        generador_id: int
    ) -> List[Dict]:
        """
        Predict what products a generator will have as surplus next.

        Uses simple patterns:
        - If generated X kg of Y in last N days, likely will again
        - Seasonal patterns (TODO: advanced ML)

        Args:
            generador_id: Generator ID

        Returns:
            List of predictions with product, quantity, date, confidence
        """

        from database import TransaccionDB, LoteDB

        # Get last 30 days of transactions
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        transacciones = self.db.query(TransaccionDB).filter(
            TransaccionDB.generador_id == generador_id,
            TransaccionDB.created_at >= thirty_days_ago
        ).all()

        if not transacciones:
            return []

        # Group by product category
        productos_stats = {}

        for trans in transacciones:
            lote = self.db.query(LoteDB).filter(LoteDB.id == trans.lote_id).first()
            if lote:
                cat = lote.categoria
                prod = lote.producto

                if prod not in productos_stats:
                    productos_stats[prod] = {
                        "categoria": cat,
                        "total_kg": 0,
                        "num_transacciones": 0,
                        "fechas": []
                    }

                productos_stats[prod]["total_kg"] += trans.cantidad_kg
                productos_stats[prod]["num_transacciones"] += 1
                productos_stats[prod]["fechas"].append(trans.created_at)

        # Generate predictions
        predictions = []

        for producto, stats in productos_stats.items():
            if stats["num_transacciones"] < 2:
                continue  # Need at least 2 samples

            # Calculate average quantity
            avg_kg = stats["total_kg"] / stats["num_transacciones"]

            # Calculate confidence (0-1) based on consistency
            confidence = min(stats["num_transacciones"] / 10, 1.0)

            # Predict next date (simple: average interval between transactions)
            if len(stats["fechas"]) >= 2:
                sorted_fechas = sorted(stats["fechas"])
                intervals = []
                for i in range(1, len(sorted_fechas)):
                    interval = (sorted_fechas[i] - sorted_fechas[i-1]).days
                    if interval > 0:
                        intervals.append(interval)

                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                    fecha_predicha = datetime.utcnow() + timedelta(days=avg_interval)
                else:
                    fecha_predicha = datetime.utcnow() + timedelta(days=7)
            else:
                fecha_predicha = datetime.utcnow() + timedelta(days=7)

            predictions.append({
                "producto": producto,
                "categoria": stats["categoria"],
                "cantidad_predicha_kg": round(avg_kg, 1),
                "fecha_predicha": fecha_predicha,
                "confianza": round(confidence, 2),
                "num_muestras": stats["num_transacciones"]
            })

        # Sort by confidence descending
        predictions.sort(key=lambda x: x["confianza"], reverse=True)

        return predictions

    def _calculate_match_score(
        self,
        generador_id: int,
        receptor,
        categorias_compradas: Dict,
        transacciones_generador: List
    ) -> float:
        """
        Calculate match score between generator and receptor.

        Scoring factors:
        - Category overlap (35%)
        - Distance/proximity (25%)
        - Receptor capacity (20%)
        - Historical frequency (20%)

        Score range: 0.0 to 1.0

        Args:
            generador_id: Generator ID
            receptor: Receptor ORM object
            categorias_compradas: Dict of category: count
            transacciones_generador: List of past transactions

        Returns:
            Match score 0-1
        """

        score = 0.0

        # Category overlap scoring (35%)
        if receptor.categorias_interes:
            overlap = 0
            total_categorias = len(categorias_compradas)

            if total_categorias > 0:
                for cat in receptor.categorias_interes:
                    if cat in categorias_compradas:
                        overlap += 1

                categoria_score = (overlap / total_categorias) * 0.35
                score += categoria_score
            else:
                score += 0.35  # Good category fit, no history to check against

        # Distance scoring (25%)
        # Assuming receptor has ubicacion (lat, lon)
        distance_score = self._calculate_distance_score(generador_id, receptor)
        score += distance_score * 0.25

        # Capacity scoring (20%)
        # Higher capacity = more likely to handle large lots
        capacity_score = min(receptor.capacidad_kg_dia / 1000, 1.0)  # Normalize to 1kg/day
        score += capacity_score * 0.20

        # Frequency/activity scoring (20%)
        frequency_score = min(len(transacciones_generador) / 50, 1.0)  # Normalize
        score += frequency_score * 0.20

        return min(score, 1.0)

    def _calculate_distance_score(self, generador_id: int, receptor) -> float:
        """
        Calculate distance score (1.0 = local, 0.0 = very far)

        Args:
            generador_id: Generator ID
            receptor: Receptor ORM object

        Returns:
            Score 0-1 (1 = closer)
        """

        from database import GeneradorDB
        from math import radians, cos, sin, asin, sqrt

        generador = self.db.query(GeneradorDB).filter(
            GeneradorDB.id == generador_id
        ).first()

        if not generador or not hasattr(generador, 'ubicacion'):
            return 0.5  # Default if no location data

        try:
            # Extract lat/lon from GeoAlchemy2 geometry
            gen_coords = self._extract_coords(generador.ubicacion)
            rec_coords = self._extract_coords(receptor.ubicacion)

            if not gen_coords or not rec_coords:
                return 0.5

            distance_km = self._haversine_distance(gen_coords, rec_coords)

            # Distance scoring: 0-50km = excellent, 50-200km = good, 200+ = poor
            if distance_km <= 50:
                return 1.0
            elif distance_km <= 200:
                return 0.5 + (1 - (distance_km - 50) / 150) * 0.5
            else:
                return max(0.1, 1 - distance_km / 1000)

        except Exception:
            return 0.5

    @staticmethod
    def _extract_coords(geom) -> Optional[Tuple[float, float]]:
        """Extract lat/lon from GeoAlchemy2 geometry object"""

        try:
            if hasattr(geom, 'coords'):
                coords = list(geom.coords)
                if coords:
                    return coords[0]
            elif hasattr(geom, 'x') and hasattr(geom, 'y'):
                return (geom.y, geom.x)  # Note: GeoAlchemy returns (lon, lat)
        except Exception:
            pass

        return None

    @staticmethod
    def _haversine_distance(
        coords1: Tuple[float, float],
        coords2: Tuple[float, float]
    ) -> float:
        """
        Calculate distance between two coordinates in km.

        Args:
            coords1: (lat, lon)
            coords2: (lat, lon)

        Returns:
            Distance in km
        """

        lat1, lon1 = coords1
        lat2, lon2 = coords2

        # Convert to radians
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1

        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371  # Radius of earth in kilometers

        return c * r
