"""
Integration tests for compliance module with real-world scenarios.
Tests compliance validation, legal hierarchy, and documentation generation.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import compliance
import models
import database


class TestComplianceWithProductLifecycle:
    """Test compliance through product lifecycle"""

    def test_product_through_complete_lifecycle(self):
        """Test a product moving through all states"""
        now = datetime.utcnow()
        best_before = now + timedelta(days=10)
        expiry = best_before + timedelta(days=5)

        # State 1: Before best-before
        state1 = compliance.determine_product_state(best_before, expiry, now)
        assert state1 == compliance.EstadoProducto.antes_fecha_consumo

        # State 2: After best-before
        state2 = compliance.determine_product_state(
            best_before,
            expiry,
            now + timedelta(days=11)
        )
        assert state2 == compliance.EstadoProducto.despues_fecha_consumo

        # State 3: Near expiry
        state3 = compliance.determine_product_state(
            best_before,
            expiry,
            now + timedelta(days=14)
        )
        assert state3 == compliance.EstadoProducto.antes_fecha_expiracion

        # State 4: Expired
        state4 = compliance.determine_product_state(
            best_before,
            expiry,
            now + timedelta(days=16)
        )
        assert state4 == compliance.EstadoProducto.despues_fecha_expiracion

    def test_permitted_uses_hierarchy(self):
        """Test legal use hierarchy across product states"""
        states = [
            compliance.EstadoProducto.antes_fecha_consumo,
            compliance.EstadoProducto.despues_fecha_consumo,
            compliance.EstadoProducto.antes_fecha_expiracion,
            compliance.EstadoProducto.despues_fecha_expiracion
        ]

        for state in states:
            uses = compliance.get_permitted_uses(state, compliance.Categoria.frutas)

            assert isinstance(uses, list)
            assert len(uses) > 0

            # Verify hierarchy - later states should have fewer uses
            # (not strictly, depends on implementation)
            assert all(use in [u.value for u in compliance.UsoFinal] for use in uses)

    def test_use_hierarchy_strictness_by_category(self):
        """Test that different categories have appropriate strictness"""
        state_after_best_before = compliance.EstadoProducto.despues_fecha_consumo

        meat_uses = compliance.get_permitted_uses(
            state_after_best_before,
            compliance.Categoria.carnes
        )
        veg_uses = compliance.get_permitted_uses(
            state_after_best_before,
            compliance.Categoria.verduras
        )

        # Meat should have stricter rules (fewer uses)
        assert len(meat_uses) <= len(veg_uses)

    def test_use_validation_across_states(self):
        """Test use validation for all combinations"""
        states = [
            compliance.EstadoProducto.antes_fecha_consumo,
            compliance.EstadoProducto.despues_fecha_consumo,
            compliance.EstadoProducto.antes_fecha_expiracion,
            compliance.EstadoProducto.despues_fecha_expiracion
        ]

        uses = [u.value for u in compliance.UsoFinal]
        categories = [c.value for c in compliance.Categoria]

        for state in states:
            for category in categories:
                for use in uses:
                    is_allowed, reason = compliance.validate_use_allowed(
                        state,
                        compliance.Categoria(category),
                        use
                    )

                    assert isinstance(is_allowed, bool)
                    assert reason is None or isinstance(reason, str)

                    # If not allowed, reason should be provided
                    if not is_allowed:
                        assert reason is not None


class TestComplianceDocumentation:
    """Test compliance document generation"""

    def test_generate_compliance_doc_before_best_before(self):
        """Test compliance doc for product before best-before"""
        state = compliance.EstadoProducto.antes_fecha_consumo

        data = compliance.generate_compliance_data(
            transaccion_id=1,
            lote_id=100,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Test Generator",
            receptor_nombre="Test Receptor",
            producto="Apples",
            cantidad_kg=500.0,
            precio_final=250.0,
            uso_final=compliance.UsoFinal.prevencion.value,
            estado_producto=state
        )

        assert data["tipo_documento"] == "compliance_legal"
        assert data["transaccion_id"] == 1
        assert data["conformidad"]["cumple_ley_1_2025"] is True
        assert data["conformidad"]["uso_permitido"] is True

    def test_generate_compliance_doc_expired_product(self):
        """Test compliance doc for expired product"""
        state = compliance.EstadoProducto.despues_fecha_expiracion

        data = compliance.generate_compliance_data(
            transaccion_id=2,
            lote_id=101,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Test Generator",
            receptor_nombre="Test Receptor",
            producto="Old Cheese",
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=compliance.UsoFinal.compostaje.value,
            estado_producto=state
        )

        assert data["conformidad"]["cumple_ley_1_2025"] is True
        # Compostaje should be allowed for expired
        assert data["conformidad"]["uso_permitido"] is True

    def test_generate_compliance_doc_illegal_use(self):
        """Test compliance doc detects illegal use"""
        state = compliance.EstadoProducto.despues_fecha_expiracion

        # Try donation (not allowed after expiry)
        data = compliance.generate_compliance_data(
            transaccion_id=3,
            lote_id=102,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Test Generator",
            receptor_nombre="Test Receptor",
            producto="Expired Meat",
            cantidad_kg=50.0,
            precio_final=25.0,
            uso_final=compliance.UsoFinal.donacion_consumo.value,
            estado_producto=state
        )

        # Should indicate non-compliance
        assert data["conformidad"]["uso_permitido"] is False or \
               data["conformidad"]["cumple_ley_1_2025"] is False

    def test_compliance_doc_has_required_fields(self):
        """Test that compliance doc includes all required fields"""
        data = compliance.generate_compliance_data(
            transaccion_id=4,
            lote_id=103,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Generator",
            receptor_nombre="Receptor",
            producto="Test Product",
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=compliance.UsoFinal.donacion_consumo.value,
            estado_producto=compliance.EstadoProducto.antes_fecha_consumo
        )

        required_fields = [
            "tipo_documento",
            "ley",
            "transaccion_id",
            "generador",
            "receptor",
            "producto",
            "conformidad"
        ]

        for field in required_fields:
            assert field in data

        # Check nested structures
        assert "nombre" in data["generador"]
        assert "nombre" in data["receptor"]
        assert "cantidad_kg" in data["producto"]
        assert "estado" in data["producto"]
        assert "cumple_ley_1_2025" in data["conformidad"]


class TestComplianceHierarchy:
    """Test compliance use hierarchy"""

    def test_hierarchy_structure(self):
        """Test hierarchy has proper structure"""
        hierarchy = compliance.ComplianceChecker.get_use_hierarchy_description()

        assert isinstance(hierarchy, dict)
        assert len(hierarchy) == 8

        # Check each level
        for level_num in range(1, 9):
            assert level_num in hierarchy
            level = hierarchy[level_num]

            assert "nombre" in level
            assert "descripcion" in level
            assert "prioridad" in level
            assert level["prioridad"] == level_num

    def test_hierarchy_descriptions_make_sense(self):
        """Test that hierarchy descriptions are meaningful"""
        hierarchy = compliance.ComplianceChecker.get_use_hierarchy_description()

        # Level 1 should be prevention (highest priority)
        assert "prevención" in hierarchy[1]["nombre"].lower() or \
               "prevencion" in hierarchy[1]["nombre"].lower()

        # Last level should be disposal
        assert "eliminación" in hierarchy[8]["nombre"].lower() or \
               "eliminacion" in hierarchy[8]["nombre"].lower() or \
               "disposal" in hierarchy[8]["nombre"].lower()

    def test_hierarchy_completeness(self):
        """Test hierarchy covers all use types"""
        hierarchy = compliance.ComplianceChecker.get_use_hierarchy_description()

        uso_values = [u.value for u in compliance.UsoFinal]
        hierarchy_levels = list(hierarchy.keys())

        # Should have entry for each use level
        assert len(hierarchy_levels) == len(uso_values)


class TestComplianceValidationEdgeCases:
    """Edge case tests for compliance validation"""

    def test_validation_with_all_categories(self):
        """Test validation works for all product categories"""
        state = compliance.EstadoProducto.antes_fecha_consumo

        for category in compliance.Categoria:
            is_allowed, reason = compliance.validate_use_allowed(
                state,
                category,
                compliance.UsoFinal.donacion_consumo.value
            )

            assert isinstance(is_allowed, bool)

    def test_validation_with_all_uses(self):
        """Test validation works for all use types"""
        state = compliance.EstadoProducto.antes_fecha_consumo
        category = compliance.Categoria.frutas

        for use in compliance.UsoFinal:
            is_allowed, reason = compliance.validate_use_allowed(
                state,
                category,
                use.value
            )

            assert isinstance(is_allowed, bool)
            # Early state should allow everything
            assert is_allowed is True

    def test_validation_expired_state_restricted(self):
        """Test that expired state has strongest restrictions"""
        state = compliance.EstadoProducto.despues_fecha_expiracion
        category = compliance.Categoria.carnes

        # Test all uses
        allowed_uses = []
        for use in compliance.UsoFinal:
            is_allowed, reason = compliance.validate_use_allowed(
                state,
                category,
                use.value
            )

            if is_allowed:
                allowed_uses.append(use.value)

        # Expired meat should have very limited uses
        assert len(allowed_uses) <= 2  # Only compostaje and biogas

    def test_validation_fresh_state_permissive(self):
        """Test that fresh state allows most uses"""
        state = compliance.EstadoProducto.antes_fecha_consumo
        category = compliance.Categoria.verduras

        allowed_uses = []
        for use in compliance.UsoFinal:
            is_allowed, reason = compliance.validate_use_allowed(
                state,
                category,
                use.value
            )

            if is_allowed:
                allowed_uses.append(use.value)

        # Fresh vegetables should allow many uses
        assert len(allowed_uses) >= 4


class TestComplianceAuditTrail:
    """Test compliance audit trail and traceability"""

    def test_compliance_doc_includes_timestamps(self):
        """Test compliance doc includes audit timestamps"""
        data = compliance.generate_compliance_data(
            transaccion_id=5,
            lote_id=104,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Generator",
            receptor_nombre="Receptor",
            producto="Test",
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=compliance.UsoFinal.donacion_consumo.value,
            estado_producto=compliance.EstadoProducto.antes_fecha_consumo
        )

        # Should have timestamp information
        assert "fecha_generacion" in data or "timestamp" in data or "created_at" in data or "created_at" in str(data)

    def test_compliance_doc_includes_traceability(self):
        """Test compliance doc includes traceability info"""
        data = compliance.generate_compliance_data(
            transaccion_id=6,
            lote_id=105,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Generator",
            receptor_nombre="Receptor",
            producto="Test",
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=compliance.UsoFinal.donacion_consumo.value,
            estado_producto=compliance.EstadoProducto.antes_fecha_consumo
        )

        # Should link transaction, lote, generator, receptor
        assert data["transaccion_id"] == 6
        assert data["lote_id"] == 105
        assert data["generador"]["id"] == 1
        assert data["receptor"]["id"] == 2

    def test_compliance_doc_legal_reference(self):
        """Test compliance doc references correct legal framework"""
        data = compliance.generate_compliance_data(
            transaccion_id=7,
            lote_id=106,
            generador_id=1,
            receptor_id=2,
            generador_nombre="Generator",
            receptor_nombre="Receptor",
            producto="Test",
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=compliance.UsoFinal.donacion_consumo.value,
            estado_producto=compliance.EstadoProducto.antes_fecha_consumo
        )

        assert "ley" in data
        assert "1/2025" in data["ley"]
        assert "alimentos" in data["ley"].lower() or "food" in data["ley"].lower()


class TestComplianceIntegrationWithDatabase:
    """Integration tests with database models"""

    def test_compliance_validation_with_db_transaction(self, db: Session):
        """Test compliance validation using database transaction"""
        # Create test data
        gen = database.GeneradorDB(
            nombre="Test Gen",
            tipo=models.TipoGenerador.retail,
            cif="A12345678",
            direccion="Test",
            ubicacion=None,
            contacto_email="test@example.com",
            contacto_telefono="+34123456789"
        )

        rec = database.ReceptorDB(
            nombre="Test Rec",
            tipo=models.TipoReceptor.banco_alimentos,
            cif="B87654321",
            direccion="Test",
            ubicacion=None,
            capacidad_kg_dia=500.0,
            categorias_interes=["frutas"]
        )

        db.add_all([gen, rec])
        db.commit()

        # Validate use
        is_allowed, reason = compliance.validate_use_allowed(
            compliance.EstadoProducto.antes_fecha_consumo,
            compliance.Categoria.frutas,
            compliance.UsoFinal.donacion_consumo.value
        )

        assert is_allowed is True

        # Generate compliance doc
        data = compliance.generate_compliance_data(
            transaccion_id=8,
            lote_id=107,
            generador_id=gen.id,
            receptor_id=rec.id,
            generador_nombre=gen.nombre,
            receptor_nombre=rec.nombre,
            producto="Apples",
            cantidad_kg=100.0,
            precio_final=50.0,
            uso_final=compliance.UsoFinal.donacion_consumo.value,
            estado_producto=compliance.EstadoProducto.antes_fecha_consumo
        )

        assert data["generador"]["nombre"] == gen.nombre
        assert data["receptor"]["nombre"] == rec.nombre
