#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas del rasterizador de sprites.

La geometria se compara contra una implementacion aparte, escrita aqui a mano
con la formula del VHDL: ventana ``x1-2 .. x1+ancho-3`` e indice
``(x+2-x1) + (y-y1)*ancho``.  Si el VHDL cambia, hay que cambiar las dos cosas.

Nada de esto esta validado contra la placa: los colores vienen de los ``.coe``
del proyecto entregado, copiados a ``coe/``.
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
import suasm  # noqa: E402

TABLE = suasm.load_opcodes()
BACKGROUND = gpu.SPRITES[0]
AMMO = gpu.SPRITES[1]
ENEMY = gpu.SPRITES[2]
SHIP = gpu.SPRITES[3]


class FakeMachine:
    """Lo minimo que ``gpu`` necesita: RAM y que direcciones se escribieron."""

    def __init__(self):
        self.ram = [0] * cpu.RAM_WORDS
        self.written_addresses: set[int] = set()

    def place(self, sprite: gpu.SpriteDef, x1: int, y1: int) -> None:
        # El fondo tiene Ax1 == Ay1 == 000: no se puede ubicar con dos valores
        # distintos porque el VHDL guarda el mismo dato en x1 e y1.
        assert sprite.ax != sprite.ay, f"{sprite.name} usa la misma direccion para x e y"
        self.ram[sprite.ax] = x1
        self.ram[sprite.ay] = y1
        self.written_addresses.update({sprite.ax, sprite.ay})


def color(image: gpu.SpriteImage, index: int) -> tuple[int, int, int]:
    """Color de 8 bits que deberia salir por los pines para ese indice."""
    return (
        int(image.red[index]) * 17,
        int(image.green[index]) * 17,
        int(image.blue[index]) * 17,
    )


def opaque(image: gpu.SpriteImage, index: int) -> bool:
    return bool(image.red[index] | image.green[index] | image.blue[index])


class TestCoe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = gpu.load_sprite_images()

    def test_los_cuatro_sprites_cargan(self):
        self.assertEqual(set(self.images), {"background", "ammo", "enemyShip", "mainShip"})

    def test_tamano_exacto_de_cada_imagen(self):
        expected = {"background": 90000, "ammo": 100, "enemyShip": 900, "mainShip": 6210}
        for name, size in expected.items():
            image = self.images[name]
            self.assertEqual(image.size, size, name)
            self.assertEqual(image.definition.width * image.definition.height, size, name)

    def test_valores_de_4_bits(self):
        for image in self.images.values():
            for channel in (image.red, image.green, image.blue):
                self.assertLessEqual(int(channel.max()), 0xF)

    def test_direcciones_de_cada_componente(self):
        # Copiadas de Ax1/Ay1 en los .vhd de _x/.
        self.assertEqual((BACKGROUND.ax, BACKGROUND.ay), (0x000, 0x000))
        self.assertEqual((SHIP.ax, SHIP.ay), (0x00A, 0x00B))
        self.assertEqual((ENEMY.ax, ENEMY.ay), (0x00C, 0x00D))
        self.assertEqual((AMMO.ax, AMMO.ay), (0x00E, 0x00F))

    def test_coe_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            gpu.load_sprite_images(Path("/tmp/opencode/no-existe"))

    def test_coe_con_tamano_equivocado(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for definition in gpu.SPRITES:
                for name in ("RED", "GREEN", "BLUE"):
                    (directory / f"{definition.rom}_{name}.coe").write_text(
                        "memory_initialization_radix=16;\n"
                        "memory_initialization_vector=\n0, 0;\n"
                    )
            with self.assertRaises(ValueError):
                gpu.load_sprite_images(directory)


class TestGeometria(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = gpu.load_sprite_images()

    def test_la_nave_aparece_donde_se_le_dice(self):
        machine = FakeMachine()
        machine.place(SHIP, 100, 50)
        frame = gpu.render(machine, self.images, sprites=(SHIP,))
        ship = self.images["mainShip"]
        for dx, dy in ((0, 0), (1, 0), (30, 10), (66, 89)):
            index = (dx + 2) + dy * 69
            expected = color(ship, index) if opaque(ship, index) else (0, 0, 0)
            self.assertEqual(tuple(int(v) for v in frame[50 + dy, 100 + dx]),
                             expected, f"dx={dx} dy={dy}")

    def test_la_ventana_no_incluye_el_ultimo_par_de_columnas(self):
        # x < x1 + 69 - 2 = x1 + 67, asi que x1+67 ya queda fuera.
        machine = FakeMachine()
        machine.place(SHIP, 100, 50)
        frame = gpu.render(machine, self.images, sprites=(SHIP,))
        self.assertTrue(frame[50, 100:167].any())
        self.assertFalse(frame[50, 167:200].any())

    def test_la_fila_de_abajo_no_se_pinta(self):
        machine = FakeMachine()
        machine.place(SHIP, 100, 50)
        frame = gpu.render(machine, self.images, sprites=(SHIP,))
        self.assertTrue(frame[139, 100:167].any(), "y1+89 = 139 esta dentro")
        self.assertFalse(frame[140, :].any(), "y1+90 ya esta fuera")

    def test_pixel_negro_es_transparente(self):
        ship = self.images["mainShip"]
        index = next(i for i in range(ship.size) if not opaque(ship, i))
        dx = index % 69 - 2
        dy = index // 69
        machine = FakeMachine()
        machine.place(SHIP, 100, 50)
        frame = gpu.render(machine, self.images, sprites=(SHIP,))
        self.assertEqual(tuple(int(v) for v in frame[50 + dy, 100 + dx]), (0, 0, 0))

    def test_sin_escritura_el_sprite_deja_solo_dos_columnas(self):
        # x1 arranca en 640.  Como la ventana es x1-2 <= x < x1+ancho-2, el
        # sprite NO desaparece del todo: queda una franja de 2 columnas
        # (x = 638 y 639) con los primeros pixeles de cada fila de la imagen.
        # Es una rareza del VHDL entregado, no del emulador.
        machine = FakeMachine()
        frame = gpu.render(machine, self.images, sprites=(SHIP,))
        self.assertEqual(gpu.positions(machine)[SHIP.name], (640, 0))
        self.assertFalse(frame[:, :638].any())
        self.assertTrue(frame[:, 638:640].any())

    def test_escribir_cero_si_pone_el_sprite_en_pantalla(self):
        # Escribir 0 es distinto de no escribir nunca: el registro del
        # componente arranca en 640 y solo cambia al recibir una escritura.
        machine = FakeMachine()
        machine.place(SHIP, 0, 0)
        self.assertEqual(gpu.positions(machine)[SHIP.name], (0, 0))
        self.assertTrue(gpu.render(machine, self.images, sprites=(SHIP,)).any())

    def test_prioridad_nave_sobre_enemigo(self):
        ship = self.images["mainShip"]
        enemy = self.images["enemyShip"]
        machine = FakeMachine()
        machine.place(SHIP, 100, 50)
        machine.place(ENEMY, 100, 50)
        frame = gpu.render(machine, self.images, sprites=(ENEMY, SHIP))
        # (dx, dy) = (10, 10): hay que buscar uno donde la nave sea opaca.
        for dx in range(28):
            for dy in range(30):
                ship_index = (dx + 2) + dy * 69
                enemy_index = (dx + 2) + dy * 30
                if opaque(ship, ship_index) and opaque(enemy, enemy_index):
                    self.assertEqual(
                        tuple(int(v) for v in frame[50 + dy, 100 + dx]),
                        color(ship, ship_index),
                    )
                    return
        self.fail("no se encontro un pixel donde ambos sprites sean opacos")

    def test_donde_la_nave_es_transparente_se_ve_el_enemigo(self):
        ship = self.images["mainShip"]
        enemy = self.images["enemyShip"]
        machine = FakeMachine()
        machine.place(SHIP, 100, 50)
        machine.place(ENEMY, 100, 50)
        frame = gpu.render(machine, self.images, sprites=(ENEMY, SHIP))
        for dx in range(28):
            for dy in range(30):
                ship_index = (dx + 2) + dy * 69
                enemy_index = (dx + 2) + dy * 30
                if not opaque(ship, ship_index) and opaque(enemy, enemy_index):
                    self.assertEqual(
                        tuple(int(v) for v in frame[50 + dy, 100 + dx]),
                        color(enemy, enemy_index),
                    )
                    return
        self.fail("no se encontro un pixel transparente en la nave")

    def test_municion_en_sus_direcciones(self):
        machine = FakeMachine()
        machine.place(AMMO, 200, 100)
        frame = gpu.render(machine, self.images, sprites=(AMMO,))
        ammo = self.images["ammo"]
        self.assertEqual(tuple(int(v) for v in frame[100, 200]), color(ammo, 2))
        self.assertFalse(frame[100, 210:].any(), "el sprite mide 10 de ancho")


class TestFondo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = gpu.load_sprite_images()
        cls.background = cls.images["background"]

    def test_arranca_en_0_0(self):
        machine = FakeMachine()
        self.assertEqual(gpu.positions(machine)[BACKGROUND.name], (0, 0))
        frame = gpu.render(machine, self.images, sprites=(BACKGROUND,))
        self.assertEqual(tuple(int(v) for v in frame[0, 100]),
                         color(self.background, 102))

    def test_no_comprueba_ventana_y_se_corre_al_pasar_300(self):
        # La direccion es (x+2) + y*300 para TODO el cuadro, asi que en
        # x = 298 en adelante se lee la fila siguiente de la imagen.
        machine = FakeMachine()
        frame = gpu.render(machine, self.images, sprites=(BACKGROUND,))
        self.assertEqual(tuple(int(v) for v in frame[0, 300]),
                         color(self.background, 302))
        self.assertEqual(tuple(int(v) for v in frame[1, 298]),
                         color(self.background, 600))

    def test_debajo_de_y_434_queda_negro(self):
        # La direccion del fondo es (x+2) + (y-y1)*300, sin prueba de ventana.
        # Para y >= 300 pasa de las 90 000 palabras del arreglo, y el BRAM
        # devuelve 0 (= negro = transparente).  Ojo: el VHDL mete esa cuenta
        # en 17 bits, asi que desde y = 435 el desbordamiento vuelve a caer
        # dentro de la imagen y se repite el tope del fondo.
        machine = FakeMachine()
        frame = gpu.render(machine, self.images, sprites=(BACKGROUND,))
        self.assertFalse(frame[300:435, :].any(), "la direccion sale del arreglo")
        self.assertTrue(frame[435:, :].any(), "el truncamiento a 17 bits la trae de vuelta")

    def test_desbordamiento_de_17_bits_repinta_el_tope(self):
        # Fila 437, x = 0: (0+2) + 437*300 = 131 102 -> 131 102 mod 2^17 = 30.
        machine = FakeMachine()
        frame = gpu.render(machine, self.images, sprites=(BACKGROUND,))
        self.assertEqual(tuple(int(v) for v in frame[437, 0]),
                         color(self.background, 30))

    def test_mover_el_fondo_con_los_leds(self):
        # backgroundSM tiene Ax1 = Ay1 = 000, la misma direccion que el
        # registro de LEDs.  Al escribir 10 ahi, x1 e y1 quedan en 10 (el
        # fondo se corre en diagonal).
        machine = FakeMachine()
        machine.ram[0] = 10
        machine.written_addresses.add(0)
        self.assertEqual(gpu.positions(machine)[BACKGROUND.name], (10, 10))
        frame = gpu.render(machine, self.images, sprites=(BACKGROUND,))
        # x = 100, y = 20 -> indice (100+2-10) + (20-10)*300 = 3092
        self.assertEqual(tuple(int(v) for v in frame[20, 100]),
                         color(self.background, 3092))


class TestDescribe(unittest.TestCase):
    def test_sin_escrituras_los_sprites_dejan_su_franja(self):
        # Con x1 = 640 por defecto, la ventana x1-2..x1+ancho-3 igual toca las
        # dos ultimas columnas, asi que se informan esos pocos pixeles.
        text = gpu.describe(FakeMachine())
        self.assertIn("fondo", text)
        self.assertRegex(text, r"municion .* -> \d+ pixeles")

    def test_bien_lejos_dice_fuera_de_pantalla(self):
        machine = FakeMachine()
        machine.place(SHIP, 700, 40)
        self.assertIn("fuera de pantalla", gpu.describe(machine))

    def test_con_posiciones(self):
        machine = FakeMachine()
        machine.place(SHIP, 308, 390)
        text = gpu.describe(machine)
        self.assertIn("x1=  308", text)
        self.assertIn("5978 pixeles", text)


class TestIntegracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = suasm.assemble_file(EMU_DIR / "programas" / "06_sprites.suasm", TABLE)

    def machine(self, **kwargs):
        machine = cpu.Machine(
            rom=self.program.rom,
            keys=[row.key for row in self.program.listing],
            **kwargs,
        )
        machine.init_words = self.program.code_start
        return machine

    def test_el_programa_de_ejemplo_pinta_los_tres_sprites(self):
        machine = self.machine()
        machine.run(400)
        frame = gpu.render(machine)
        self.assertEqual(frame.shape, (480, 640, 3))
        self.assertEqual(frame.dtype, np.uint8)
        self.assertEqual(gpu.positions(machine)["mainShip"], (308, 390))
        self.assertEqual(gpu.positions(machine)["enemyShip"], (120, 60))
        self.assertEqual(gpu.positions(machine)["ammo"], (340, 300))

    def test_se_mueve_solo_cuando_cambia_el_milisegundo(self):
        machine = self.machine(buttons=4)  # boton izquierda apretado
        machine.run(90_000)                # todavia no llego el primer tick
        self.assertEqual(machine.ram[self.program.symbols["nave_x"]], 308)
        machine.run(20_000)                # 110 000 ciclos: ya hubo un tick
        self.assertEqual(machine.ram[self.program.symbols["nave_x"]], 307)

    def test_no_baja_del_borde_izquierdo(self):
        machine = self.machine(buttons=4)
        machine.run(400_000)
        self.assertGreaterEqual(machine.ram[self.program.symbols["nave_x"]], 2)


if __name__ == "__main__":
    unittest.main()
