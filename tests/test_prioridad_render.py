#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regresion: la prioridad de capas del render.

El VHDL (GraphicsProcessor) elige el color con una cadena if/elsif:
nave > enemigo > municion > fondo.  Un sprite solo cede donde su pixel es
negro (000000), que es el color transparente.

Los tests de ``test_gpu.py`` renderizan un sprite a la vez, asi que no vieron
que ``render()`` recorria las capas al reves y el fondo tapaba a los demas.
Aqui se renderizan varios sprites superpuestos.

Nada de esto esta validado contra la placa.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMU_DIR))

import numpy as np  # noqa: E402

import cpu  # noqa: E402
import gpu  # noqa: E402

# gpu.SPRITES va de menor a mayor prioridad.
BACKGROUND, AMMO, ENEMY, SHIP = gpu.SPRITES[0], gpu.SPRITES[1], gpu.SPRITES[2], gpu.SPRITES[3]


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
    """Pixeles pintados (no negros)."""
    return frame.any(axis=2)


class TestPrioridadDeCapas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = gpu.load_sprite_images()

    def _machine(self) -> FakeMachine:
        machine = FakeMachine()
        # Los tres sprites en el mismo lugar, sobre una zona donde el fondo
        # (a partir de x1=y1=0) es casi todo opaco: estrellas y azul.
        for sprite in (AMMO, ENEMY, SHIP):
            machine.place(sprite, 100, 10)
        return machine

    def _render(self, machine, *sprites):
        return gpu.render(machine, self.images, sprites=tuple(sprites))

    def test_el_orden_de_sprites_es_de_menor_a_mayor_prioridad(self):
        self.assertEqual(
            [s.name for s in gpu.SPRITES],
            ["background", "ammo", "enemyShip", "mainShip"],
        )

    def test_la_nave_queda_encima_del_fondo(self):
        machine = self._machine()
        solo_nave = self._render(machine, SHIP)
        solo_fondo = self._render(machine, BACKGROUND)
        todo = self._render(machine, *gpu.SPRITES)

        pintados = _drawn(solo_nave)
        # La prueba solo vale si el fondo tambien pinta ahi con otro color.
        solapados = pintados & _drawn(solo_fondo) & (solo_nave != solo_fondo).any(axis=2)
        self.assertTrue(solapados.any(), "la prueba no se solapa: elegir otra zona")
        np.testing.assert_array_equal(todo[pintados], solo_nave[pintados])

    def test_cada_sprite_gana_al_de_menor_prioridad(self):
        machine = self._machine()
        for bajo, alto in (
            (BACKGROUND, AMMO),
            (BACKGROUND, ENEMY),
            (AMMO, ENEMY),
            (AMMO, SHIP),
            (ENEMY, SHIP),
        ):
            with self.subTest(alto=alto.name, bajo=bajo.name):
                solo_alto = self._render(machine, alto)
                solo_bajo = self._render(machine, bajo)
                ambos = self._render(machine, bajo, alto)
                pintados = _drawn(solo_alto)
                solapados = pintados & _drawn(solo_bajo) & (solo_alto != solo_bajo).any(axis=2)
                self.assertTrue(solapados.any(), "la prueba no se solapa")
                np.testing.assert_array_equal(ambos[pintados], solo_alto[pintados])

    def test_el_de_menor_prioridad_se_ve_donde_el_otro_es_negro(self):
        machine = self._machine()
        solo_nave = self._render(machine, SHIP)
        solo_fondo = self._render(machine, BACKGROUND)
        fondo_y_nave = self._render(machine, BACKGROUND, SHIP)
        # Donde la nave no pinta (negro) debe verse el fondo.
        libres = ~_drawn(solo_nave) & _drawn(solo_fondo)
        self.assertTrue(libres.any())
        np.testing.assert_array_equal(fondo_y_nave[libres], solo_fondo[libres])


if __name__ == "__main__":
    unittest.main()
