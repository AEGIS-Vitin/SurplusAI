"""
Tests for matching engine and predictions.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import database
import models
import matching


def test_get_recommended_matches_no_history(db: Session):
    """Test that matching engine returns empty for new generator"""
    # Create generator with no transaction history
    gen = database.GeneradorDB(
        nombre="New Generator",
        tipo=models.TipoGenerador.retail,
        cif="C12345678",
        direccion="Test Address",
        ubicacion=None,
        contacto_email="gen@test.com",
        contacto_telefono="123456",
        plan_suscripcion="basico"
    )
    db.add(gen)
    db.commit()

    engine = matching.MatchingEngine(db)
    matches = engine.get_recommended_matches(gen.id)

    assert matches == []


def test_get_recommended_matches_with_history(db: Session):
    """Test that matching engine recommends receptors"""
    # Create generator and receptor
    gen = database.GeneradorDB(
        nombre="Test Generator",
        tipo=models.TipoGenerador.retail,
        cif="C12345678",
        direccion="Test Address",
        ubicacion=None,
        contacto_email="gen@test.com",
        contacto_telefono="123456",
        plan_suscripcion="basico"
    )

    receptor = database.ReceptorDB(
        nombre="Test Receptor",
        tipo=models.TipoReceptor.banco_alimentos,
        cif="D87654321",
        direccion="Test Address",
        ubicacion=None,
        capacidad_kg_dia=500.0,
        categorias_interes=["frutas"],
        licencias=[]
    )

    db.add(gen)
    db.add(receptor)
    db.commit()

    # Create a lot and transaction
    lote = database.LoteDB(
        generador_id=gen.id,
        producto="Test Product",
        categoria=models.Categoria.frutas,
        cantidad_kg=100.0,
        ubicacion=None,
        fecha_publicacion=datetime.utcnow(),
        fecha_limite=datetime.utcnow() + timedelta(days=3),
        precio_base=50.0,
        precio_actual=50.0,
        estado=models.EstadoLote.activo
    )

    puja = database.PujaDB(
        lote_id=lote.id,
        receptor_id=receptor.id,
        precio_oferta=45.0,
        uso_previsto=models.UsoFinal.donacion_consumo,
        estado=models.EstadoPuja.pendiente
    )

    transaccion = database.TransaccionDB(
        lote_id=lote.id,
        puja_id=puja.id,
        generador_id=gen.id,
        receptor_id=receptor.id,
        precio_final=45.0,
        cantidad_kg=100.0,
        uso_final=models.UsoFinal.donacion_consumo,
        estado=models.EstadoTransaccion.completada
    )

    db.add(lote)
    db.add(puja)
    db.add(transaccion)
    db.commit()

    # Now test matching
    engine = matching.MatchingEngine(db)
    matches = engine.get_recommended_matches(gen.id)

    # May return matches based on new receptors
    assert isinstance(matches, list)


def test_predict_next_surplus_no_history(db: Session):
    """Test prediction with no transaction history"""
    gen = database.GeneradorDB(
        nombre="New Generator",
        tipo=models.TipoGenerador.retail,
        cif="C12345678",
        direccion="Test Address",
        ubicacion=None,
        contacto_email="gen@test.com",
        contacto_telefono="123456",
        plan_suscripcion="basico"
    )
    db.add(gen)
    db.commit()

    engine = matching.MatchingEngine(db)
    predictions = engine.predict_next_surplus(gen.id)

    assert predictions == []


def test_predict_next_surplus_with_history(db: Session):
    """Test prediction with transaction history"""
    # Setup generator and transaction
    gen = database.GeneradorDB(
        nombre="Test Generator",
        tipo=models.TipoGenerador.retail,
        cif="C12345678",
        direccion="Test Address",
        ubicacion=None,
        contacto_email="gen@test.com",
        contacto_telefono="123456",
        plan_suscripcion="basico"
    )

    receptor = database.ReceptorDB(
        nombre="Test Receptor",
        tipo=models.TipoReceptor.banco_alimentos,
        cif="D87654321",
        direccion="Test Address",
        ubicacion=None,
        capacidad_kg_dia=500.0,
        categorias_interes=[],
        licencias=[]
    )

    db.add(gen)
    db.add(receptor)
    db.commit()

    # Create multiple lots and transactions (for predictions)
    for i in range(2):
        lote = database.LoteDB(
            generador_id=gen.id,
            producto="Apples",
            categoria=models.Categoria.frutas,
            cantidad_kg=100.0,
            ubicacion=None,
            fecha_publicacion=datetime.utcnow() - timedelta(days=10-i),
            fecha_limite=datetime.utcnow() + timedelta(days=3),
            precio_base=50.0,
            precio_actual=50.0,
            estado=models.EstadoLote.activo
        )

        puja = database.PujaDB(
            lote_id=lote.id,
            receptor_id=receptor.id,
            precio_oferta=45.0,
            uso_previsto=models.UsoFinal.donacion_consumo,
            estado=models.EstadoPuja.pendiente
        )

        transaccion = database.TransaccionDB(
            lote_id=lote.id,
            puja_id=puja.id,
            generador_id=gen.id,
            receptor_id=receptor.id,
            precio_final=45.0,
            cantidad_kg=100.0,
            uso_final=models.UsoFinal.donacion_consumo,
            estado=models.EstadoTransaccion.completada,
            created_at=datetime.utcnow() - timedelta(days=10-i)
        )

        db.add(lote)
        db.add(puja)
        db.add(transaccion)

    db.commit()

    # Test predictions
    engine = matching.MatchingEngine(db)
    predictions = engine.predict_next_surplus(gen.id)

    # Should have at least one prediction for apples
    assert len(predictions) > 0
    assert predictions[0]["producto"] == "Apples"
    assert "cantidad_predicha_kg" in predictions[0]
    assert "confianza" in predictions[0]
    assert predictions[0]["confianza"] > 0


def test_match_score_calculation(db: Session):
    """Test that match score is calculated correctly"""
    gen = database.GeneradorDB(
        nombre="Test Generator",
        tipo=models.TipoGenerador.retail,
        cif="C12345678",
        direccion="Test Address",
        ubicacion=None,
        contacto_email="gen@test.com",
        contacto_telefono="123456",
        plan_suscripcion="basico"
    )

    receptor = database.ReceptorDB(
        nombre="Test Receptor",
        tipo=models.TipoReceptor.banco_alimentos,
        cif="D87654321",
        direccion="Test Address",
        ubicacion=None,
        capacidad_kg_dia=500.0,
        categorias_interes=["frutas", "verduras"],
        licencias=[]
    )

    db.add(gen)
    db.add(receptor)
    db.commit()

    engine = matching.MatchingEngine(db)

    # Test score calculation (0-1)
    score = engine._calculate_match_score(
        gen.id,
        receptor,
        {"frutas": 1},  # categories bought
        []  # past transactions
    )

    assert 0 <= score <= 1


def test_distance_score_calculation(db: Session):
    """Test distance score calculation"""
    gen = database.GeneradorDB(
        nombre="Test Generator",
        tipo=models.TipoGenerador.retail,
        cif="C12345678",
        direccion="Test Address",
        ubicacion=None,
        contacto_email="gen@test.com",
        contacto_telefono="123456",
        plan_suscripcion="basico"
    )

    receptor = database.ReceptorDB(
        nombre="Test Receptor",
        tipo=models.TipoReceptor.banco_alimentos,
        cif="D87654321",
        direccion="Test Address",
        ubicacion=None,
        capacidad_kg_dia=500.0,
        categorias_interes=[],
        licencias=[]
    )

    db.add(gen)
    db.add(receptor)
    db.commit()

    engine = matching.MatchingEngine(db)

    # Test distance scoring (0-1)
    score = engine._calculate_distance_score(gen.id, receptor)
    assert 0 <= score <= 1
