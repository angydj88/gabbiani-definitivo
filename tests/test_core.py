"""
Tests unitarios — GABBIANI MASTER AI v7 Core Engine
Ejecutar: python -m pytest tests/test_core.py -v
"""
import sys
import os
import hashlib
import pytest
import pandas as pd

# Asegurar que el directorio padre está en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    PiezaIndustrial, CampoTrazable, CerebroOperarioV5,
    ValidadorFisico, ExtractorVectorial, NivelConfianza,
    OrigenDato, PERFILES, validar_hdr690
)


# ══════════════════════════════════════════════════════════════════════════════
# PiezaIndustrial — Hash de deduplicación
# ══════════════════════════════════════════════════════════════════════════════
class TestPiezaHash:
    def _make_pieza(self, **kwargs):
        defaults = dict(
            id="P1", nombre="Test",
            largo=CampoTrazable(1000), ancho=CampoTrazable(500),
            espesor=CampoTrazable(19), material=CampoTrazable("W980"),
            cantidad=CampoTrazable(1)
        )
        defaults.update(kwargs)
        return PiezaIndustrial(**defaults)

    def test_hash_includes_espesor(self):
        """Dos piezas iguales con distinto espesor deben tener hash diferente."""
        p1 = self._make_pieza(espesor=CampoTrazable(16))
        p2 = self._make_pieza(espesor=CampoTrazable(19))
        assert p1.hash_pieza != p2.hash_pieza

    def test_hash_same_for_identical(self):
        """Piezas idénticas deben tener el mismo hash."""
        p1 = self._make_pieza()
        p2 = self._make_pieza()
        assert p1.hash_pieza == p2.hash_pieza

    def test_hash_differs_by_material(self):
        p1 = self._make_pieza(material=CampoTrazable("W980"))
        p2 = self._make_pieza(material=CampoTrazable("M6317"))
        assert p1.hash_pieza != p2.hash_pieza


# ══════════════════════════════════════════════════════════════════════════════
# CerebroOperarioV5
# ══════════════════════════════════════════════════════════════════════════════
class TestCerebro:
    def setup_method(self):
        self.cerebro = CerebroOperarioV5("ESTÁNDAR")

    def test_normalizar_material_blanco(self):
        mat, conf = self.cerebro.normalizar_material("Blanco")
        assert mat == "W980"
        assert conf == NivelConfianza.ALTA

    def test_normalizar_material_desconocido(self):
        mat, conf = self.cerebro.normalizar_material("Zebrano Exótico")
        assert mat == "Zebrano Exótico"
        assert conf == NivelConfianza.MEDIA

    def test_normalizar_material_vacio(self):
        mat, conf = self.cerebro.normalizar_material("")
        assert mat == "SIN MATERIAL"
        assert conf == NivelConfianza.BAJA

    def test_es_basura_tornillo(self):
        assert self.cerebro.es_basura("Tornillo M8", "") is True

    def test_es_basura_lateral(self):
        assert self.cerebro.es_basura("Lateral Armario", "Blanco") is False

    def test_procesar_swap_largo_ancho(self):
        """Si largo < ancho, debe intercambiarlos."""
        datos = [{"nombre": "Test", "largo": 300, "ancho": 600,
                  "espesor": 19, "cantidad": 1, "material": "Blanco"}]
        piezas, _ = self.cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        assert len(piezas) == 1
        assert piezas[0].largo.valor == 600
        assert piezas[0].ancho.valor == 300

    def test_procesar_sandwich(self):
        """Piezas con nota PEGAR deben tener margen sándwich."""
        datos = [{"nombre": "Pieza", "largo": 1000, "ancho": 500,
                  "espesor": 19, "cantidad": 1, "material": "Blanco",
                  "notas": "PEGAR"}]
        piezas, alertas = self.cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        assert len(piezas) == 1
        margen = PERFILES["ESTÁNDAR"]["margen_sandwich"]
        assert piezas[0].largo.valor == 1000 + margen
        assert piezas[0].ancho.valor == 500 + margen
        assert any("Sándwich" in a for a in alertas)

    def test_procesar_filtra_basura(self):
        """Herrajes y tornillos deben ser filtrados."""
        datos = [
            {"nombre": "Lateral", "largo": 2000, "ancho": 600,
             "espesor": 19, "cantidad": 2, "material": "Blanco"},
            {"nombre": "Tornillo M8x40", "largo": 40, "ancho": 8,
             "espesor": 8, "cantidad": 100, "material": ""},
        ]
        piezas, _ = self.cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        assert len(piezas) == 1
        assert piezas[0].nombre == "Lateral"

    def test_procesar_2x1(self):
        """Piezas estrechas con cantidad par deben optimizarse 2x1."""
        datos = [{"nombre": "Tira", "largo": 1000, "ancho": 30,
                  "espesor": 19, "cantidad": 4, "material": "Blanco"}]
        piezas, alertas = self.cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        assert len(piezas) == 1
        assert piezas[0].cantidad.valor == 2  # 4 ÷ 2
        assert piezas[0].ancho.valor == PERFILES["ESTÁNDAR"]["ancho_seguro"]

    def test_deduplicacion(self):
        """Piezas duplicadas deben descartarse."""
        datos = [
            {"nombre": "Lateral", "largo": 2000, "ancho": 600,
             "espesor": 19, "cantidad": 2, "material": "Blanco"},
        ] * 2  # misma pieza dos veces
        piezas, alertas = self.cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        assert len(piezas) == 1
        assert any("duplicada" in a for a in alertas)


# ══════════════════════════════════════════════════════════════════════════════
# CerebroOperarioV5 — Perfiles especiales
# ══════════════════════════════════════════════════════════════════════════════
class TestCerebroPerfiles:
    def test_qube_genera_fondo(self):
        cerebro = CerebroOperarioV5("APOTHEKA")
        datos = [{"nombre": "Cajón Grande", "largo": 600, "ancho": 400,
                  "espesor": 19, "cantidad": 2, "material": "Blanco",
                  "notas": "QUBE"}]
        piezas, alertas = cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        nombres = [p.nombre for p in piezas]
        assert any("Fondo" in n for n in nombres)
        assert any("Frente" in n for n in nombres)

    def test_gradeles_fuerza_16mm(self):
        cerebro = CerebroOperarioV5("GRADELES_16")
        datos = [{"nombre": "Puerta Armario", "largo": 1800, "ancho": 600,
                  "espesor": 19, "cantidad": 2, "material": "Blanco"}]
        piezas, _ = cerebro.procesar(datos, 1, OrigenDato.VISION_IA)
        assert len(piezas) == 1
        assert piezas[0].espesor.valor == 16


# ══════════════════════════════════════════════════════════════════════════════
# ValidadorFisico
# ══════════════════════════════════════════════════════════════════════════════
class TestValidadorFisico:
    def setup_method(self):
        self.perfil = PERFILES["ESTÁNDAR"]

    def test_pieza_normal(self):
        ok, alertas, conf = ValidadorFisico.validar(
            {"largo": 1000, "ancho": 500, "espesor": 19, "cantidad": 2, "nombre": "Lateral"},
            self.perfil)
        assert ok is True
        assert len(alertas) == 0

    def test_largo_excesivo(self):
        ok, alertas, conf = ValidadorFisico.validar(
            {"largo": 5000, "ancho": 500, "espesor": 19, "cantidad": 1, "nombre": "Pieza"},
            self.perfil)
        assert ok is False
        assert conf == NivelConfianza.BAJA

    def test_espesor_no_comercial(self):
        ok, alertas, conf = ValidadorFisico.validar(
            {"largo": 1000, "ancho": 500, "espesor": 17, "cantidad": 1, "nombre": "Pieza"},
            self.perfil)
        assert any("no comercial" in a for a in alertas)

    def test_cantidad_cero(self):
        ok, alertas, conf = ValidadorFisico.validar(
            {"largo": 1000, "ancho": 500, "espesor": 19, "cantidad": 0, "nombre": "Pieza"},
            self.perfil)
        assert ok is False

    def test_largo_menor_que_ancho_avisa(self):
        ok, alertas, conf = ValidadorFisico.validar(
            {"largo": 300, "ancho": 600, "espesor": 19, "cantidad": 1, "nombre": "Pieza"},
            self.perfil)
        assert any("intercambiarán" in a for a in alertas)

    def test_material_espesor_invalido(self):
        ok, alertas, conf = ValidadorFisico.validar(
            {"largo": 1000, "ancho": 500, "espesor": 19, "cantidad": 1,
             "nombre": "Fondo", "material": "16B"},
            self.perfil)
        assert any("16B" in a and "19mm" in a for a in alertas)


# ══════════════════════════════════════════════════════════════════════════════
# ExtractorVectorial — Cabeceras
# ══════════════════════════════════════════════════════════════════════════════
class TestExtractorVectorial:
    def test_parsear_tabla_normal(self):
        df = pd.DataFrame({
            "Nombre": ["Lateral", "Estante"],
            "Largo": [2000, 800],
            "Ancho": [600, 400],
            "Espesor": [19, 19],
            "Cantidad": [2, 3],
            "Material": ["Blanco", "Roble"]
        })
        piezas = ExtractorVectorial.parsear_tablas([df], 1)
        assert len(piezas) == 2
        assert piezas[0]["largo"] == 2000

    def test_parsear_tabla_cabeceras_mm(self):
        """Cabeceras con (mm) deben normalizarse."""
        df = pd.DataFrame({
            "Pieza": ["Lateral", "Estante"],
            "Largo (mm)": [2000, 800],
            "Ancho (mm)": [600, 400],
            "Esp": [19, 19],
            "Cant": [2, 3],
            "Material": ["Blanco", "Roble"]
        })
        piezas = ExtractorVectorial.parsear_tablas([df], 1)
        assert len(piezas) == 2

    def test_parsear_tabla_insuficiente(self):
        """Tabla con pocas columnas debe ser ignorada."""
        df = pd.DataFrame({"A": [1], "B": [2]})
        piezas = ExtractorVectorial.parsear_tablas([df], 1)
        assert len(piezas) == 0

    def test_normalizar_cabecera(self):
        assert ExtractorVectorial._normalizar_cabecera("Largo (mm)") == "largo"
        assert ExtractorVectorial._normalizar_cabecera("  ANCHO mm  ") == "ancho"
        assert ExtractorVectorial._normalizar_cabecera("L(mm)") == "l"


# ══════════════════════════════════════════════════════════════════════════════
# Validación HDR6,90
# ══════════════════════════════════════════════════════════════════════════════
class TestValidarHDR:
    def _make_pieza(self, **kwargs):
        defaults = dict(
            id="P1", nombre="Test",
            largo=CampoTrazable(1000), ancho=CampoTrazable(500),
            espesor=CampoTrazable(19), material=CampoTrazable("W980"),
            cantidad=CampoTrazable(2)
        )
        defaults.update(kwargs)
        return PiezaIndustrial(**defaults)

    def test_pieza_valida(self):
        errores = validar_hdr690([self._make_pieza()])
        assert len(errores) == 0

    def test_dimension_cero(self):
        errores = validar_hdr690([self._make_pieza(largo=CampoTrazable(0))])
        assert any("Longitud" in e for e in errores)

    def test_cantidad_negativa(self):
        errores = validar_hdr690([self._make_pieza(cantidad=CampoTrazable(-1))])
        assert any("Solicitados" in e for e in errores)

    def test_nombre_vacio(self):
        errores = validar_hdr690([self._make_pieza(nombre="")])
        assert any("Codigo" in e for e in errores)


# ══════════════════════════════════════════════════════════════════════════════
# Veta dinámica y Código de canteado
# ══════════════════════════════════════════════════════════════════════════════
class TestVetaYCanteado:
    def _make_pieza(self, **kwargs):
        defaults = dict(
            id="P1", nombre="Test",
            largo=CampoTrazable(1000), ancho=CampoTrazable(500),
            espesor=CampoTrazable(19), material=CampoTrazable("W980"),
            cantidad=CampoTrazable(1)
        )
        defaults.update(kwargs)
        return PiezaIndustrial(**defaults)

    def test_veta_liso_w980(self):
        p = self._make_pieza(material=CampoTrazable("W980"))
        assert p.to_csv_row()["Veta"] == 0

    def test_veta_liso_blanco(self):
        p = self._make_pieza(material=CampoTrazable("BLANCO"))
        assert p.to_csv_row()["Veta"] == 0

    def test_veta_madera_roble(self):
        p = self._make_pieza(material=CampoTrazable("M6317"))
        assert p.to_csv_row()["Veta"] == 1

    def test_veta_madera_elegance(self):
        p = self._make_pieza(material=CampoTrazable("ELEGANCE"))
        assert p.to_csv_row()["Veta"] == 1

    def test_canteado_4c_en_notas(self):
        p = self._make_pieza(notas="4C")
        assert p.to_csv_row()["Descripcion"] == "4C"

    def test_canteado_1l_2c(self):
        p = self._make_pieza(notas="CANTO 1L 2C")
        assert "1L" in p.to_csv_row()["Descripcion"]

    def test_canteado_sc(self):
        p = self._make_pieza(notas="SC")
        assert p.to_csv_row()["Descripcion"] == "SC"

    def test_canteado_sin_codigo(self):
        p = self._make_pieza(notas="PEGAR DOBLE")
        assert p.to_csv_row()["Descripcion"] == "PROYECTO"

    def test_nombre_truncado_15(self):
        p = self._make_pieza(nombre="LATERAL IZQUIERDO SUPERIOR GRANDE")
        row = p.to_csv_row()
        assert len(row["Codigo"]) <= 15
