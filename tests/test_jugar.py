#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de jugar.py: timer acelerado y ventana (sin pantalla real)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EMU_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMU_DIR))

import jugar  # noqa: E402
import suasm  # noqa: E402

BUCLE = "DATA:\nx 0\nCODE:\nfin:\n  JMP fin\n"
NAVE = EMU_DIR / "programas" / "05_nave.suasm"


def ms(maquina) -> int:
    return maquina.read(5)  # direccion 5 = timer_milisegundos


class TestTimerAcelerado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.programa = suasm.assemble(BUCLE, suasm.load_opcodes(), "<bucle>")

    def test_ciclos_por_microsegundo(self):
        self.assertEqual(jugar.ciclos_por_us(1), 100)
        self.assertEqual(jugar.ciclos_por_us(50), 2)
        self.assertEqual(jugar.ciclos_por_us(100), 1)
        self.assertEqual(jugar.ciclos_por_us(1000), 1)

    def test_acelerar_1_es_el_timer_real(self):
        maquina = jugar.construir_maquina(self.programa, acelerar=1)
        maquina.run(99_000)
        self.assertEqual(ms(maquina), 0)
        maquina.run(2_000)
        self.assertEqual(ms(maquina), 1)

    def test_acelerar_50_da_un_tick_cada_2000_ciclos(self):
        maquina = jugar.construir_maquina(self.programa, acelerar=50)
        maquina.run(1_900)
        self.assertEqual(ms(maquina), 0)
        maquina.run(200)
        self.assertEqual(ms(maquina), 1)
        maquina.run(20_000)
        self.assertEqual(ms(maquina), 11)

    def test_la_inicializacion_de_data_no_deja_avisos(self):
        programa = suasm.assemble_file(NAVE, suasm.load_opcodes())
        maquina = jugar.construir_maquina(programa)
        self.assertFalse(maquina.shadow_warnings)


@unittest.skipIf(jugar.QtWidgets is None, "falta PyQt6")
class TestVentana(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gpu
        except ImportError:
            raise unittest.SkipTest("faltan numpy/Pillow")
        from PyQt6 import QtWidgets
        from PyQt6.QtTest import QTest

        cls.QTest = QTest
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.gpu = gpu
        cls.imagenes = gpu.load_sprite_images()
        cls.programa = suasm.assemble_file(NAVE, suasm.load_opcodes())

    def setUp(self):
        self.ventana = jugar.VentanaJuego(self.programa, self.gpu, self.imagenes)
        self.ventana.reloj.stop()  # se avanza a mano con paso()

    def tearDown(self):
        self.ventana.close()

    def tecla(self, nombre: str, soltar: bool = True):
        from PyQt6.QtCore import Qt

        clave = getattr(Qt.Key, nombre)
        self.QTest.keyPress(self.ventana, clave)
        if soltar:
            self.QTest.keyRelease(self.ventana, clave)

    def test_dibuja_la_pantalla(self):
        self.ventana.paso()
        self.assertFalse(self.ventana.pantalla.pixmap().isNull())
        self.assertIn("Display", self.ventana.estado.text())

    def test_flechas_son_botones(self):
        self.tecla("Key_Left", soltar=False)
        self.assertEqual(self.ventana.maquina.buttons, 4)
        self.tecla("Key_Right", soltar=False)
        self.assertEqual(self.ventana.maquina.buttons, 12)
        self.QTest.keyRelease(self.ventana, getattr(__import__("PyQt6.QtCore").QtCore.Qt.Key, "Key_Left"))
        self.assertEqual(self.ventana.maquina.buttons, 8)

    def test_el_boton_mueve_la_nave(self):
        nave_x = self.programa.symbols["nave_x"]
        self.ventana.paso()
        antes = self.ventana.maquina.ram[nave_x]
        self.tecla("Key_Left", soltar=False)
        self.ventana.paso()
        self.assertLess(self.ventana.maquina.ram[nave_x], antes)

    def test_s_alterna_el_switch_de_inicio(self):
        self.tecla("Key_S")
        self.assertEqual(self.ventana.maquina.switches & 0x8000, 0x8000)
        self.tecla("Key_S")
        self.assertEqual(self.ventana.maquina.switches & 0x8000, 0)

    def test_velocidad_y_pausa(self):
        self.tecla("Key_Minus")
        self.assertEqual(self.ventana.acelerar, 20)
        self.tecla("Key_Plus")
        self.assertEqual(self.ventana.acelerar, 50)
        self.tecla("Key_P")
        ciclos = self.ventana.maquina.cycles
        self.ventana.paso()
        self.assertEqual(self.ventana.maquina.cycles, ciclos)

    def test_reiniciar_conserva_los_switches(self):
        self.tecla("Key_S")
        self.ventana.paso()
        self.tecla("Key_R")
        self.assertEqual(self.ventana.maquina.switches & 0x8000, 0x8000)


if __name__ == "__main__":
    unittest.main()
