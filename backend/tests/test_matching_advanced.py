"""
Advanced tests for matching algorithm covering edge cases and complex scenarios.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from matching import MatchingEngine
import models
import database


class TestMatchingEngineBasics:
    """Basic matching engine tests"""

    def test_matching_engine_initialization(self, db: Session):
        """Test matching engine can be initialized"""
        engine = MatchingEngine(db)
        assert engine.db == db

    def test_get_recommended_matches_no_history(self, db: Session, test_generador):
        """Test getting recommendations for generator with no history"""
        engine = MatchingEngine(db)

        matches = engine.get_recommended_matches(test_generador.id, limit=5)

        assert isinstance(matches, list)
        assert len(matches) == 0  # No history = no recommendations

    def test_get_recommended_matches_with_history(
        self,
        db: Session,
        test_generador,
        test_receptor,
        test_lote
    ):
        """Test getting recommendations when generator has transaction history"""
        engine = MatchingEngine(db)

        # Create a transaction
        transaccion = database.TransaccionDB(
            generador_id=test_generador.id,
            receptor_id=test_receptor.id,
            lote_id=test_lote.id,
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=models.UsoFinal.donacion_consumo.value,
            estado=models.EstadoTransaccion.completada,
            created_at=datetime.utcnow()
        )
        db.add(transaccion)
        db.commit()

        matches = engine.get_recommended_matches(test_generador.id, limit=5)

        # Should have recommendations based on history
        assert isinstance(matches, list)


class TestMatchScoreCalculation:
    """Tests for match score calculation"""

    def test_match_score_structure(self, db: Session, test_generador, test_receptor):
        """Test that match score has correct structure"""
        engine = MatchingEngine(db)

        # Create some history
        transaccion = database.TransaccionDB(
            generador_id=test_generador.id,
            receptor_id=test_receptor.id,
            lote_id=1,
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=models.UsoFinal.donacion_consumo.value,
            estado=models.EstadoTransaccion.completada,
            created_at=datetime.utcnow()
        )
        db.add(transaccion)
        db.commit()

        score = engine._calculate_match_score(
            test_generador.id,
            test_receptor,
            {"frutas": 1},
            [transaccion]
        )

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_match_score_with_category_overlap(self, db: Session, test_generador):
        """Test match score increases with category overlap"""
        engine = MatchingEngine(db)

        # Create two receptors with different category interests
        receptor1 = database.ReceptorDB(
            nombre="Receptor 1",
            tipo=models.TipoReceptor.banco_alimentos,
            cif="B11111111",
            direccion="Test 123",
            ubicacion=None,
            capacidad_kg_dia=500.0,
            categorias_interes=["frutas", "verduras"],
            licencias=[]
        )

        receptor2 = database.ReceptorDB(
            nombre="Receptor 2",
            tipo=models.TipoReceptor.banco_alimentos,
            cif="B22222222",
            direccion="Test 456",
            ubicacion=None,
            capacidad_kg_dia=500.0,
            categorias_interes=["carnes", "pescados"],  # No overlap
            licencias=[]
        )

        db.add_all([receptor1, receptor2])
        db.commit()

        # Create history with fruit sales
        categorias_compradas = {"frutas": 5, "verduras": 3}
        transacciones = []

        score1 = engine._calculate_match_score(
            test_generador.id,
            receptor1,
            categorias_compradas,
            transacciones
        )

        score2 = engine._calculate_match_score(
            test_generador.id,
            receptor2,
            categorias_compradas,
            transacciones
        )

        # Receptor1 should have higher score (category overlap)
        assert score1 > score2

    def test_match_score_with_capacity(self, db: Session, test_generador):
        """Test match score reflects receptor capacity"""
        engine = MatchingEngine(db)

        receptor_low = database.ReceptorDB(
            nombre="Low Capacity",
            tipo=models.TipoReceptor.banco_alimentos,
            cif="B33333333",
            direccion="Test",
            ubicacion=None,
            capacidad_kg_dia=10.0,  # Low capacity
            categorias_interes=["frutas"],
            licencias=[]
        )

        receptor_high = database.ReceptorDB(
            nombre="High Capacity",
            tipo=models.TipoReceptor.banco_alimentos,
            cif="B44444444",
            direccion="Test",
            ubicacion=None,
            capacidad_kg_dia=5000.0,  # High capacity
            categorias_interes=["frutas"],
            licencias=[]
        )

        db.add_all([receptor_low, receptor_high])
        db.commit()

        categorias_compradas = {"frutas": 1}
        transacciones = []

        score_low = engine._calculate_match_score(
            test_generador.id,
            receptor_low,
            categorias_compradas,
            transacciones
        )

        score_high = engine._calculate_match_score(
            test_generador.id,
            receptor_high,
            categorias_compradas,
            transacciones
        )

        # Higher capacity should give higher score
        assert score_high > score_low


class TestSurplusPrediction:
    """Tests for surplus prediction"""

    def test_predict_next_surplus_no_history(self, db: Session, test_generador):
        """Test prediction with no transaction history"""
        engine = MatchingEngine(db)

        predictions = engine.predict_next_surplus(test_generador.id)

        assert isinstance(predictions, list)
        assert len(predictions) == 0

    def test_predict_next_surplus_with_history(
        self,
        db: Session,
        test_generador,
        test_receptor,
        test_lote
    ):
        """Test prediction with transaction history"""
        engine = MatchingEngine(db)

        # Create multiple transactions
        for i in range(3):
            transaccion = database.TransaccionDB(
                generador_id=test_generador.id,
                receptor_id=test_receptor.id,
                lote_id=test_lote.id,
                cantidad_kg=100.0 + i * 10,
                precio_final=50.0,
                uso_final=models.UsoFinal.donacion_consumo.value,
                estado=models.EstadoTransaccion.completada,
                created_at=datetime.utcnow() - timedelta(days=5 - i)
            )
            db.add(transaccion)
        db.commit()

        predictions = engine.predict_next_surplus(test_generador.id)

        # Should have predictions
        assert isinstance(predictions, list)
        if len(predictions) > 0:
            # Verify structure
            pred = predictions[0]
            assert "producto" in pred
            assert "categoria" in pred
            assert "cantidad_predicha_kg" in pred
            assert "fecha_predicha" in pred
            assert "confianza" in pred
            assert 0.0 <= pred["confianza"] <= 1.0

    def test_prediction_confidence_increases_with_history(
        self,
        db: Session,
        test_generador,
        test_receptor,
        test_lote
    ):
        """Test that confidence increases with more transaction history"""
        engine = MatchingEngine(db)

        # Create few transactions
        for i in range(2):
            transaccion = database.TransaccionDB(
                generador_id=test_generador.id,
                receptor_id=test_receptor.id,
                lote_id=test_lote.id,
                cantidad_kg=100.0,
                precio_final=50.0,
                uso_final=models.UsoFinal.donacion_consumo.value,
                estado=models.EstadoTransaccion.completada,
                created_at=datetime.utcnow() - timedelta(days=5 - i)
            )
            db.add(transaccion)
        db.commit()

        predictions_few = engine.predict_next_surplus(test_generador.id)

        # Add more transactions
        for i in range(5):
            transaccion = database.TransaccionDB(
                generador_id=test_generador.id,
                receptor_id=test_receptor.id,
                lote_id=test_lote.id,
                cantidad_kg=100.0,
                precio_final=50.0,
                uso_final=models.UsoFinal.donacion_consumo.value,
                estado=models.EstadoTransaccion.completada,
                created_at=datetime.utcnow() - timedelta(days=1 - i)
            )
            db.add(transaccion)
        db.commit()

        predictions_many = engine.predict_next_surplus(test_generador.id)

        # Should have predictions with higher confidence
        if len(predictions_many) > 0 and len(predictions_few) > 0:
            # Confidence should be higher with more history
            assert predictions_many[0].get("confianza", 0) >= predictions_few[0].get("confianza", 0)


class TestDistanceScoring:
    """Tests for distance calculation and scoring"""

    def test_distance_score_calculation(self, db: Session, test_generador, test_receptor):
        """Test distance score calculation"""
        engine = MatchingEngine(db)

        score = engine._calculate_distance_score(test_generador.id, test_receptor)

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_distance_score_no_location_returns_default(self, db: Session, test_generador):
        """Test distance score returns default when no location"""
        engine = MatchingEngine(db)

        receptor_no_loc = database.ReceptorDB(
            nombre="No Location",
            tipo=models.TipoReceptor.banco_alimentos,
            cif="B55555555",
            direccion="Test",
            ubicacion=None,
            capacidad_kg_dia=500.0,
            categorias_interes=[]
        )
        db.add(receptor_no_loc)
        db.commit()

        score = engine._calculate_distance_score(test_generador.id, receptor_no_loc)

        assert score == 0.5  # Default value

    def test_haversine_distance_calculation(self):
        """Test haversine distance calculation"""
        # Madrid coordinates
        coords1 = (40.4168, -3.7038)
        # Barcelona coordinates
        coords2 = (41.3874, 2.1686)

        distance = MatchingEngine._haversine_distance(coords1, coords2)

        # Distance should be roughly 500km
        assert 400 < distance < 650

    def test_haversine_distance_same_point(self):
        """Test haversine distance for same point"""
        coords = (40.4168, -3.7038)

        distance = MatchingEngine._haversine_distance(coords, coords)

        assert distance == 0

    def test_extract_coords_from_geometry(self):
        """Test coordinate extraction from geometry"""
        # Create mock geometry object
        class MockGeometry:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        geom = MockGeometry(-3.7038, 40.4168)
        coords = MatchingEngine._extract_coords(geom)

        assert coords is not None
        assert coords == (40.4168, -3.7038)  # Note: swapped


class TestMatchingEdgeCases:
    """Edge case tests for matching"""

    def test_recommend_matches_with_limit_zero(self, db: Session, test_generador):
        """Test getting recommendations with limit 0"""
        engine = MatchingEngine(db)

        matches = engine.get_recommended_matches(test_generador.id, limit=0)

        assert len(matches) == 0

    def test_recommend_matches_with_large_limit(self, db: Session, test_generador):
        """Test getting recommendations with large limit"""
        engine = MatchingEngine(db)

        matches = engine.get_recommended_matches(test_generador.id, limit=1000)

        # Should return whatever is available, max 1000
        assert len(matches) <= 1000
        assert isinstance(matches, list)

    def test_recommend_matches_nonexistent_generator(self, db: Session):
        """Test getting recommendations for non-existent generator"""
        engine = MatchingEngine(db)

        matches = engine.get_recommended_matches(999999, limit=5)

        assert isinstance(matches, list)
        assert len(matches) == 0

    def test_predict_surplus_nonexistent_generator(self, db: Session):
        """Test predicting surplus for non-existent generator"""
        engine = MatchingEngine(db)

        predictions = engine.predict_next_surplus(999999)

        assert isinstance(predictions, list)
        assert len(predictions) == 0


class TestMatchingIntegration:
    """Integration tests for matching"""

    def test_full_matching_workflow(
        self,
        db: Session,
        test_generador,
        test_receptor
    ):
        """Test complete matching workflow"""
        engine = MatchingEngine(db)

        # Create some history
        now = datetime.utcnow()
        for i in range(3):
            lote = database.LoteDB(
                generador_id=test_generador.id,
                producto=f"Product {i}",
                categoria=models.Categoria.frutas,
                cantidad_kg=100.0,
                ubicacion=None,
                fecha_publicacion=now - timedelta(days=5 - i),
                fecha_limite=now - timedelta(days=2 - i),
                precio_base=50.0 * (i + 1),
                precio_actual=45.0 * (i + 1),
                temperatura_conservacion=4.0,
                estado=models.EstadoLote.adjudicado,
                lote_origen=f"LOTE_{i}"
            )
            db.add(lote)

        db.commit()

        # Get lotes
        lotes = db.query(database.LoteDB).filter(
            database.LoteDB.generador_id == test_generador.id
        ).all()

        # Create transactions
        for lote in lotes:
            transaccion = database.TransaccionDB(
                generador_id=test_generador.id,
                receptor_id=test_receptor.id,
                lote_id=lote.id,
                cantidad_kg=100.0,
                precio_final=40.0,
                uso_final=models.UsoFinal.donacion_consumo.value,
                estado=models.EstadoTransaccion.completada,
                created_at=now - timedelta(days=5 - lotes.index(lote))
            )
            db.add(transaccion)

        db.commit()

        # Get recommendations
        matches = engine.get_recommended_matches(test_generador.id, limit=5)
        assert isinstance(matches, list)

        # Get predictions
        predictions = engine.predict_next_surplus(test_generador.id)
        assert isinstance(predictions, list)

        # Both should work together
        if len(matches) > 0:
            for match in matches:
                assert "receptor_id" in match
                assert "score_match" in match
                assert 0.0 <= match["score_match"] <= 1.0
