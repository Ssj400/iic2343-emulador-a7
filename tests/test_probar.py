#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de probar.py (el atajo de un solo comando)."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMU_DIR))

import probar  # noqa: E402

SUMA = EMU_DIR / "programas" / "01_suma.suasm"


def ejecutar(*argumentos: str) -> tuple[int, str, str]:
    salida, error = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
        codigo = probar.main(list(argumentos))
    return codigo, salida.getvalue(), error.getvalue()


class TestProbar(unittest.TestCase):
    def test_muestra_variables_por_nombre(self):
        codigo, salida, _ = ejecutar(str(SUMA), "--sin-imagen", "--ciclos", "70")
        self.assertEqual(codigo, 0)
        self.assertIn("Ensamblado OK", salida)
        self.assertIn("total", salida)
        self.assertIn("15 (0x000F)", salida)

    def test_no_lista_las_direcciones_de_es_salvo_ver_todo(self):
        _, salida, _ = ejecutar(str(SUMA), "--sin-imagen", "--ciclos", "70")
        self.assertNotIn("switches", salida.split("Variables")[1].split("Display")[0])
        _, salida, _ = ejecutar(str(SUMA), "--sin-imagen", "--ciclos", "70", "--ver-todo")
        self.assertIn("switches", salida)

    def test_programa_inexistente_da_error_claro(self):
        codigo, _, error = ejecutar("no_existe.suasm", "--sin-imagen")
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR al ensamblar", error)

    def test_forma_inexistente_da_error(self):
        with tempfile.TemporaryDirectory() as carpeta:
            programa = Path(carpeta) / "malo.suasm"
            programa.write_text("DATA:\na 0\nb 0\nCODE:\n  MOV (a), (b)\n", encoding="utf-8")
            codigo, _, error = ejecutar(str(programa), "--sin-imagen")
        self.assertEqual(codigo, 1)
        self.assertIn("no existe la forma", error)

    def test_el_aviso_de_la_inicializacion_de_data_no_aparece(self):
        # 01_suma inicializa direcciones de E/S en su DATA: eso no debe avisarse.
        _, salida, _ = ejecutar(str(SUMA), "--sin-imagen", "--ciclos", "70")
        self.assertNotIn("AVISOS", salida)

    def test_guarda_la_imagen_sin_abrirla(self):
        try:
            import gpu  # noqa: F401
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("faltan numpy/Pillow")
        with tempfile.TemporaryDirectory() as carpeta:
            imagen = Path(carpeta) / "salida.png"
            codigo, salida, _ = ejecutar(str(SUMA), "--no-abrir", "--salida", str(imagen), "--ciclos", "70")
            self.assertEqual(codigo, 0)
            self.assertTrue(imagen.is_file())
            self.assertGreater(imagen.stat().st_size, 1000)
            self.assertIn("Imagen guardada en", salida)


if __name__ == "__main__":
    unittest.main()
