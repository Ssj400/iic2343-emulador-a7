#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enemigos extra de practica: ``extra_enemies=N`` del render.

Esto **no** es una constante del proyecto entregado: la base solo trae un
``enemyShipSM`` en 0x00C/0x00D, y la base evaluada de A7 no esta publicada.
Aqui se fija la suposicion que usa el emulador para poder practicar el caso de
>=10 aliens:

* el enemigo ``k`` (``k = 0..N-1``) escucha ``x`` en ``16 + 2k`` e ``y`` en
  ``17 + 2k``;
* mide 30x30 y usa la imagen ``nave_azul``, con la misma transparencia
  (``000000``) y el mismo ``hDiff = 2`` que ``enemyShipSM``;
* prioridad igual a ``enemyShipSM``: debajo de la nave y encima de la municion;
* arranca en ``x1 = 640`` como cualquier componente sin posicion escrita.

Nada de esto esta validado contra la placa.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMU_DIR))

import numpy as np  # noqa: E402

import cpu  # noqa: E402
import gpu  # noqa: E402

BACKGROUND, AMMO, ENEMY, SHIP = gpu.SPRITES[0], gpu.SPRITES[1], gpu.SPRITES[2], gpu.SPRITES[3]
EXTRA = gpu.extra_enemy_defs(1)[0]


class FakeMachine:
    """Lo minimo que ``gpu`` necesita: RAM y direcciones escritas."""

    def __init__(self):
        self.ram = [0] * cpu.RAM_WORDS
        self.written_addresses: set[int] = set()

    def place(self, sprite: gpu.SpriteDef, x1: int, y1: int) -> None:
        self.ram[sprite.ax] = x1
        self.ram[sprite.ay] = y1
        self.written_addresses.update({sprite.ax, sprite.ay})


def _drawn(frame: np.ndarray) -> np.ndarray:
    return frame.any(axis=2)


class TestDefiniciones(unittest.TestCase):
    def test_direcciones_y_geometria(self):
        extras = gpu.extra_enemy_defs(3)
        self.assertEqual([(e.ax, e.ay) for e in extras],
                         [(0x010, 0x011), (0x012, 0x013), (0x014, 0x015)])
        self.assertEqual([e.name for e in extras],
                         ["extraEnemy0", "extraEnemy1", "extraEnemy2"])
        for extra in extras:
            self.assertEqual((extra.width, extra.height), (30, 30))
            self.assertEqual(extra.rom, "nave_azul")
            self.assertTrue(extra.has_window)
            self.assertEqual((extra.default_x, extra.default_y), (640, 0))

    def test_cero_extra_no_cambia_la_lista(self):
        self.assertEqual(gpu.extra_enemy_defs(0), ())
        self.assertEqual(gpu.sprites_with_extras(0), gpu.SPRITES)
        self.assertIs(gpu.sprites_with_extras(0), gpu.SPRITES)

    def test_los_extra_van_entre_el_enemigo_y_la_nave(self):
        self.assertEqual(
            [s.name for s in gpu.sprites_with_extras(2)],
            ["background", "ammo", "enemyShip", "extraEnemy0",
             "extraEnemy1", "mainShip"],
        )

    def test_rechaza_negativos_y_desborde_de_ram(self):
        with self.assertRaises(ValueError):
            gpu.extra_enemy_defs(-1)
        with self.assertRaises(ValueError):
            gpu.extra_enemy_defs(4000)


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = gpu.load_sprite_images()

    def test_n_cero_es_identico(self):
        machine = FakeMachine()
        machine.place(SHIP, 308, 390)
        machine.place(ENEMY, 120, 60)
        machine.place(AMMO, 340, 300)
        sin_flag = gpu.render(machine, self.images)
        con_cero = gpu.render(machine, self.images, extra_enemies=0)
        np.testing.assert_array_equal(sin_flag, con_cero)

    def test_posicion_y_dibujo(self):
        machine = FakeMachine()
        machine.place(EXTRA, 200, 100)
        self.assertEqual(gpu.positions(machine, gpu.sprites_with_extras(1))
                         ["extraEnemy0"], (200, 100))

        solo_extra = gpu.render(machine, self.images, sprites=(EXTRA,))
        self.assertTrue(solo_extra.any())
        filas = np.where(_drawn(solo_extra).any(axis=1))[0]
        columnas = np.where(_drawn(solo_extra).any(axis=0))[0]
        self.assertGreaterEqual(filas.min(), 100)
        self.assertLessEqual(filas.max(), 129)
        self.assertGreaterEqual(columnas.min(), 198)
        self.assertLessEqual(columnas.max(), 227)  # x1 + 30 - 2 - 1

    def test_describe_nombra_los_extra(self):
        machine = FakeMachine()
        machine.place(EXTRA, 200, 100)
        texto = gpu.describe(machine, extra_enemies=1)
        self.assertIn("enemigo extra 0", texto)
        self.assertIn("x1=  200", texto)

    def test_sin_posicion_escrita_queda_fuera(self):
        machine = FakeMachine()
        # Nadie escribe 16/17: x1 arranca en 640 y solo asoma la franja de 2
        # columnas del borde derecho (misma rareza que los otros sprites).
        texto = gpu.describe(machine, extra_enemies=1)
        self.assertIn("enemigo extra 0 x1=  640", texto)
        frame = gpu.render(machine, self.images, sprites=(EXTRA,))
        self.assertTrue(frame[0:30, 638:640].any())
        self.assertFalse(frame[:, :638].any())
        self.assertFalse(frame[30:, 638:640].any())

    def test_se_oculta_con_x_mayor_igual_a_642_o_y_mayor_igual_a_480(self):
        for x1, y1 in ((642, 100), (700, 100), (200, 480), (200, 600)):
            with self.subTest(x1=x1, y1=y1):
                machine = FakeMachine()
                machine.place(EXTRA, x1, y1)
                frame = gpu.render(machine, self.images, sprites=(EXTRA,))
                self.assertFalse(frame.any())

    def test_prioridad_encima_de_la_municion(self):
        machine = FakeMachine()
        machine.place(AMMO, 100, 10)
        machine.place(EXTRA, 100, 10)
        solo_extra = gpu.render(machine, self.images, sprites=(EXTRA,))
        solo_municion = gpu.render(machine, self.images, sprites=(AMMO,))
        ambos = gpu.render(machine, self.images, sprites=(AMMO, EXTRA))

        pintados = _drawn(solo_extra)
        solapados = pintados & _drawn(solo_municion) & (solo_extra != solo_municion).any(axis=2)
        self.assertTrue(solapados.any(), "la prueba no se solapa: elegir otra zona")
        np.testing.assert_array_equal(ambos[pintados], solo_extra[pintados])

    def test_prioridad_debajo_de_la_nave(self):
        machine = FakeMachine()
        machine.place(SHIP, 100, 10)
        machine.place(EXTRA, 100, 10)
        solo_nave = gpu.render(machine, self.images, sprites=(SHIP,))
        solo_extra = gpu.render(machine, self.images, sprites=(EXTRA,))
        ambos = gpu.render(machine, self.images, sprites=(EXTRA, SHIP))

        pintados = _drawn(solo_nave)
        solapados = pintados & _drawn(solo_extra) & (solo_nave != solo_extra).any(axis=2)
        self.assertTrue(solapados.any(), "la prueba no se solapa: elegir otra zona")
        np.testing.assert_array_equal(ambos[pintados], solo_nave[pintados])

    def test_prioridad_completa_con_dos_extra(self):
        machine = FakeMachine()
        machine.place(BACKGROUND, 0, 0)
        machine.place(AMMO, 100, 10)
        machine.place(ENEMY, 100, 10)
        for extra in gpu.extra_enemy_defs(2):
            machine.place(extra, 100, 10)
        machine.place(SHIP, 100, 10)

        orden = gpu.sprites_with_extras(2)
        solo_nave = gpu.render(machine, self.images, sprites=(SHIP,))
        todo = gpu.render(machine, self.images, sprites=orden)
        np.testing.assert_array_equal(todo[_drawn(solo_nave)], solo_nave[_drawn(solo_nave)])

    def test_todos_los_extra_se_dibujan(self):
        machine = FakeMachine()
        for k, extra in enumerate(gpu.extra_enemy_defs(3)):
            machine.place(extra, 60 + 40 * k, 30)
        frame = gpu.render(machine, self.images, extra_enemies=3)
        for k in range(3):
            self.assertTrue(frame[30:60, 58 + 40 * k:88 + 40 * k].any(),
                            f"falta el enemigo extra {k}")


class TestCli(unittest.TestCase):
    def test_flag_extra_enemies(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "frame.png"
            done = subprocess.run(
                [sys.executable, "cli.py", "frame", "programas/06_sprites.suasm",
                 "--steps", "300", "--extra-enemies", "2",
                 "--out", str(out), "--scale", "1"],
                cwd=EMU_DIR, capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("enemigos extra de practica", done.stdout)
            self.assertIn("enemigo extra 1", done.stdout)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
