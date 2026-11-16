#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas del ensamblador .suasm.

La prueba central es de ida y vuelta: cada una de las 389 formas de la tabla
se escribe como instruccion concreta, se ensambla y se compara la palabra de
control emitida contra la tabla.  Asi se detectan tanto errores de
clasificacion de operandos como de expansion en varias palabras.

Nada aqui valida contra MinkiAssembler.exe (binario de Windows, no ejecutado).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMU_DIR))

import suasm  # noqa: E402

BASE_DIR = EMU_DIR.parent


def _find_template():
    """Ubica ``base_invaders.txt`` (archivo del curso, no incluido en el repositorio).

    Orden de busqueda: variable de entorno ``BASE_INVADERS``, esta carpeta y la
    carpeta superior. Devuelve ``None`` si no esta.
    """
    candidates = []
    env = os.environ.get("BASE_INVADERS")
    if env:
        candidates.append(Path(env))
    candidates += [EMU_DIR / "base_invaders.txt", BASE_DIR / "base_invaders.txt"]
    return next((path for path in candidates if path.is_file()), None)


TEMPLATE = _find_template()
SIN_PLANTILLA = (
    "falta base_invaders.txt del curso: copialo junto al emulador "
    "o define BASE_INVADERS=ruta"
)


def concrete(key: str) -> str:
    """Convierte una clave abstracta de la tabla en una instruccion concreta."""
    if " " not in key:
        return key
    mnemonic, rest = key.split(" ", 1)
    operands = []
    for token in rest.split(", "):
        if token == "Lit":
            operands.append("0")
        elif token == "(dir)":
            operands.append("(10)")
        else:
            operands.append(token)
    return f"{mnemonic} " + ", ".join(operands)


class TestTabla(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = suasm.load_opcodes()

    def test_cantidad_y_largo(self):
        self.assertEqual(len(self.table), 389)
        words = [w for entry in self.table.values() for w in entry]
        self.assertEqual(len(words), 394)  # RET y los 4 POP ocupan 2 palabras
        for word in words:
            self.assertEqual(len(word), suasm.CTRL_BITS)
            self.assertLessEqual(set(word), {"0", "1"})

    def test_ida_y_vuelta_de_todas_las_formas(self):
        problems = []
        for key, words in self.table.items():
            source = concrete(key)
            try:
                program = suasm.assemble("CODE:\n  " + source + "\n", self.table)
            except suasm.AsmError as exc:
                problems.append(f"{source}: {exc}")
                continue
            if len(program.rom) != len(words):
                problems.append(f"{source}: {len(program.rom)} palabras != {len(words)}")
                continue
            for index, expected in enumerate(words):
                got = program.rom[index] & suasm.CTRL_MASK
                if got != int(expected, 2):
                    problems.append(
                        f"{source} palabra {index}: {got:012X} != {int(expected, 2):012X}"
                    )
        self.assertEqual(problems, [], "\n".join(problems[:20]))

    def test_operandos_de_la_tabla_son_los_esperados(self):
        allowed = {
            "A", "B", "C", "D", "Lit",
            "(A)", "(B)", "(C)", "(D)", "(dir)",
        }
        for key in self.table:
            if " " not in key:
                continue
            for token in key.split(" ", 1)[1].split(", "):
                self.assertIn(token, allowed, f"token inesperado '{token}' en '{key}'")


class TestPlantilla(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEMPLATE is None:
            raise unittest.SkipTest(SIN_PLANTILLA)
        cls.table = suasm.load_opcodes()
        cls.program = suasm.assemble_file(TEMPLATE, cls.table)

    def test_28_palabras_solo_de_inicializacion(self):
        # 14 variables x 2 palabras (MOV A,valor + MOV (dir),A), CODE vacio.
        self.assertEqual(self.program.data_words, 14)
        self.assertEqual(self.program.size, 28)
        self.assertEqual(self.program.code_start, 28)

    def test_mapa_de_memoria_del_enunciado(self):
        expected = {
            "leds": 0, "switches": 1, "displays": 2, "botones": 3,
            "timer_segundos": 4, "timer_milisegundos": 5,
            "timer_microsegundos": 6, "aux": 7,
            "nave_x": 8, "nave_y": 9,
            "alien1_x": 10, "alien1_y": 11,
            "bala_x": 12, "bala_y": 13,
        }
        for name, address in expected.items():
            self.assertEqual(self.program.symbols[name], address, name)

    def test_pares_de_inicializacion(self):
        rows = self.program.listing
        for index, entry in enumerate(self.program.data):
            for offset, value in enumerate(entry.values):
                first = rows[2 * (index + offset)]
                second = rows[2 * (index + offset) + 1]
                self.assertEqual(first.literal, value)
                self.assertEqual(first.key, f"init {entry.name}[{offset}] valor")
                self.assertEqual(second.literal, entry.address + offset)
                self.assertEqual(second.key, f"init {entry.name}[{offset}] direccion")


class TestDatos(unittest.TestCase):
    def setUp(self):
        self.table = suasm.load_opcodes()

    def test_arreglo_y_direcciones_consecutivas(self):
        program = suasm.assemble(
            "DATA:\n  a 1 2 3\n  b 0\n  c 0x10\nCODE:\n  JMP 0\n", self.table
        )
        self.assertEqual(program.symbols["a"], 0)
        self.assertEqual(program.symbols["b"], 3)
        self.assertEqual(program.symbols["c"], 4)
        self.assertEqual(program.data_words, 5)
        self.assertEqual(program.code_start, 10)
        self.assertEqual(program.rom[0] >> suasm.LITERAL_SHIFT, 1)
        # c es el quinto valor declarado: sus palabras son la 8 y la 9.
        self.assertEqual(program.rom[8] >> suasm.LITERAL_SHIFT, 0x10)
        self.assertEqual(program.rom[9] >> suasm.LITERAL_SHIFT, 4)

    def test_coma_como_separador_en_data(self):
        program = suasm.assemble("DATA:\n  a 1, 2\nCODE:\n", self.table)
        self.assertEqual(program.data[0].values, [1, 2])

    def test_simbolo_duplicado_en_data(self):
        with self.assertRaises(suasm.AsmError) as ctx:
            suasm.assemble("DATA:\n  a 1\n  a 2\nCODE:\n", self.table)
        self.assertIn("duplicado", str(ctx.exception))

    def test_simbolo_duplicado_entre_data_y_etiqueta(self):
        with self.assertRaises(suasm.AsmError):
            suasm.assemble("DATA:\n  a 1\nCODE:\na: JMP a\n", self.table)

    def test_data_no_cabe_en_ram(self):
        with self.assertRaises(suasm.AsmError):
            suasm.assemble("DATA:\n  a " + " ".join(["1"] * 4097) + "\nCODE:\n", self.table)


class TestExpansiones(unittest.TestCase):
    def setUp(self):
        self.table = suasm.load_opcodes()

    def test_ret_y_pop_ocupan_dos_palabras(self):
        program = suasm.assemble(
            "CODE:\ninicio:\n  POP A\n  RET\n", self.table
        )
        self.assertEqual(program.size, 4)
        self.assertEqual(program.symbols["inicio"], 0)

    def test_etiqueta_posterior_se_corre(self):
        program = suasm.assemble(
            "CODE:\ninicio:\n  POP A\nsiguiente:\n  JMP siguiente\n", self.table
        )
        self.assertEqual(program.symbols["inicio"], 0)
        self.assertEqual(program.symbols["siguiente"], 2)
        self.assertEqual(program.rom[2] >> suasm.LITERAL_SHIFT, 2)

    def test_ret_es_dos_palabras_con_incremento_primero(self):
        words = self.table["RET"]
        self.assertEqual(len(words), 2)
        control0 = int(words[0], 2)
        control1 = int(words[1], 2)
        self.assertEqual((control0 >> 34) & 1, 1, "la primera palabra incrementa SP")
        self.assertEqual((control1 >> 44) & 0x3, 0b10, "la segunda carga PC desde RAM")
        self.assertEqual((control1 >> 36) & 0xFF, 0b00000001, "salto siempre")


class TestLiterales(unittest.TestCase):
    def test_formatos_aceptados(self):
        cases = {
            "0": 0,
            "10": 10,
            "010": 10,  # sin prefijo se lee decimal, no octal
            "0x1F": 31,
            "0b1010": 10,
            "12d": 12,
            "0FFh": 255,
            "101b": 5,
            "-1": -1,
            "0xFFFF": 0xFFFF,
        }
        for token, expected in cases.items():
            self.assertEqual(suasm.parse_int(token), expected, token)

    def test_literal_se_ubica_en_los_bits_altos(self):
        program = suasm.assemble("CODE:\n  MOV A, 0xABCD\n", suasm.load_opcodes())
        word = program.rom[0]
        self.assertEqual(word >> suasm.LITERAL_SHIFT, 0xABCD)
        self.assertEqual(word & suasm.CTRL_MASK, program.listing[0].control)

    def test_literal_negativo_se_trunca_a_16_bits(self):
        program = suasm.assemble("CODE:\n  MOV A, -1\n", suasm.load_opcodes())
        self.assertEqual(program.listing[0].literal, 0xFFFF)

    def test_literal_de_simbolo_de_data(self):
        program = suasm.assemble(
            "DATA:\n  a 0\n  b 0\nCODE:\n  MOV A, b\n  MOV A, (b)\n",
            suasm.load_opcodes(),
        )
        # 2 variables x 2 palabras de inicializacion: el codigo empieza en 4.
        self.assertEqual(program.listing[4].literal, 1)
        self.assertEqual(program.listing[5].literal, 1)

    def test_literal_de_etiqueta(self):
        program = suasm.assemble(
            "CODE:\ninicio:\n  NOP\n  JMP inicio\n", suasm.load_opcodes()
        )
        self.assertEqual(program.listing[1].literal, 0)

    def test_dec_usa_literal_implicito_1(self):
        program = suasm.assemble("CODE:\n  DEC A\n", suasm.load_opcodes())
        self.assertEqual(program.listing[0].literal, 1)

    def test_inc_de_registro_no_necesita_literal(self):
        program = suasm.assemble("CODE:\n  INC A\n", suasm.load_opcodes())
        self.assertEqual(program.listing[0].literal, 0)


class TestErrores(unittest.TestCase):
    def setUp(self):
        self.table = suasm.load_opcodes()

    def test_forma_inexistente(self):
        # No existe MOV (dir), Lit: hay que pasar por un registro.
        with self.assertRaises(suasm.AsmError) as ctx:
            suasm.assemble("CODE:\n  MOV (0), 5\n", self.table)
        self.assertIn("MOV", str(ctx.exception))

    def test_mnemonico_desconocido(self):
        with self.assertRaises(suasm.AsmError) as ctx:
            suasm.assemble("CODE:\n  VOLAR A, B\n", self.table)
        self.assertIn("desconocido", str(ctx.exception))

    def test_contenido_fuera_de_seccion(self):
        with self.assertRaises(suasm.AsmError):
            suasm.assemble("  MOV A, 1\nCODE:\n", self.table)

    def test_simbolo_no_definido(self):
        with self.assertRaises(suasm.AsmError):
            suasm.assemble("CODE:\n  JMP donde\n", self.table)

    def test_data_sin_valores(self):
        with self.assertRaises(suasm.AsmError):
            suasm.assemble("DATA:\n  a\nCODE:\n", self.table)

    def test_nombre_invalido(self):
        with self.assertRaises(suasm.AsmError):
            suasm.assemble("DATA:\n  1a 0\nCODE:\n", self.table)

    def test_error_indica_linea(self):
        with self.assertRaises(suasm.AsmError) as ctx:
            suasm.assemble("CODE:\n  NOP\n  VOLAR\n", self.table)
        self.assertIn("linea 3", str(ctx.exception))


class TestSintaxis(unittest.TestCase):
    def setUp(self):
        self.table = suasm.load_opcodes()

    def test_comentarios_y_lineas_vacias(self):
        program = suasm.assemble(
            """
            // comentario de cabecera
            DATA:
              a 0   ; comentario
            CODE:

              MOV A, 1   // otro
            """,
            self.table,
        )
        self.assertEqual(program.size, 3)
        self.assertEqual(program.listing[2].key, "MOV A, Lit")

    def test_etiqueta_en_linea_propia_y_con_instruccion(self):
        program = suasm.assemble(
            "CODE:\nuno:\ndos: JMP uno\n", self.table
        )
        self.assertEqual(program.symbols["uno"], 0)
        self.assertEqual(program.symbols["dos"], 0)

    def test_mnemonicos_sin_importar_mayusculas(self):
        program = suasm.assemble("code:\n  mov A, 3\n  jmp 0\n", self.table)
        self.assertEqual(program.size, 2)
        self.assertEqual(program.listing[0].key, "MOV A, Lit")

    def test_registros_exigen_mayuscula(self):
        # 'b' minuscula es un simbolo, no el registro B: asi una variable
        # llamada 'b' no queda ambigua.
        program = suasm.assemble(
            "DATA:\n  b 0\nCODE:\n  MOV A, b\n", self.table
        )
        self.assertEqual(program.listing[2].literal, 0)
        with self.assertRaises(suasm.AsmError) as ctx:
            suasm.assemble("CODE:\n  MOV A, b\n", self.table)
        self.assertIn("mayuscula", str(ctx.exception))

    def test_build_key_clasifica_operandos(self):
        self.assertEqual(suasm.build_key("MOV", ["(B)", "A"]), "MOV (B), A")
        self.assertEqual(suasm.build_key("MOV", ["(nave_x)", "A"]), "MOV (dir), A")
        self.assertEqual(suasm.build_key("MOV", ["A", "(nave_x)"]), "MOV A, (dir)")
        self.assertEqual(suasm.build_key("JMP", ["fin"]), "JMP Lit")
        self.assertEqual(suasm.build_key("RET", []), "RET")
        self.assertEqual(suasm.build_key("DEC", ["A"]), "DEC A")
        self.assertEqual(suasm.build_key("DEC", ["a"]), "DEC Lit")

    @unittest.skipIf(TEMPLATE is None, SIN_PLANTILLA)
    def test_texto_del_listado(self):
        program = suasm.assemble_file(TEMPLATE, self.table)
        text = suasm.render_listing(program, limit=2)
        self.assertIn("28 palabras", text)
        self.assertIn("palabras mas", text)
        symbols = suasm.render_symbols(program)
        self.assertIn("nave_x", symbols)
        self.assertIn("RAM", symbols)


if __name__ == "__main__":
    unittest.main()
