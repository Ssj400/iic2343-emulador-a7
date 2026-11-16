#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de la maquina (CPU + RAM + timer + I/O).

Se comparan contra el VHDL entregado (``_x/``), no contra la placa.  Las
expectativas raras estan comentadas: si una prueba falla, primero revisar si
lo que cambio fue el modelo o la interpretacion del VHDL.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

EMU_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMU_DIR))

import cpu  # noqa: E402
import suasm  # noqa: E402

TABLE = suasm.load_opcodes()


def build(source: str, **kwargs):
    program = suasm.assemble(source, TABLE)
    keys = [row.key for row in program.listing]
    machine = cpu.Machine(rom=program.rom, keys=keys, **kwargs)
    return program, machine


class TestALU(unittest.TestCase):
    def test_suma_con_acarreo(self):
        self.assertEqual(cpu.alu(0xFFFF, 1, "ADD"), (0x0000, 1, 1, 0))
        self.assertEqual(cpu.alu(2, 3, "ADD"), (5, 0, 0, 0))

    def test_resta_banderas(self):
        # 5 - 5: sin prestamo -> C=1, resultado 0 -> Z=1
        self.assertEqual(cpu.alu(5, 5, "SUB"), (0, 1, 1, 0))
        # 3 - 5: prestamo -> C=0 y N = not C = 1 (solo SUB define N)
        self.assertEqual(cpu.alu(3, 5, "SUB"), (0xFFFE, 0, 0, 1))

    def test_logicas(self):
        self.assertEqual(cpu.alu(0b1100, 0b1010, "AND"), (0b1000, 0, 0, 0))
        self.assertEqual(cpu.alu(0b1100, 0b1010, "OR"), (0b1110, 0, 0, 0))
        self.assertEqual(cpu.alu(0b1100, 0b1010, "XOR"), (0b0110, 0, 0, 0))
        self.assertEqual(cpu.alu(0x00FF, 0, "NOT"), (0xFF00, 0, 0, 0))

    def test_desplazamientos_y_acarreo(self):
        self.assertEqual(cpu.alu(0b1000, 0, "SHR"), (0b0100, 0, 0, 0))
        self.assertEqual(cpu.alu(0b1001, 0, "SHR"), (0b0100, 1, 0, 0))
        self.assertEqual(cpu.alu(0x8000, 0, "SHL"), (0x0000, 1, 1, 0))

    def test_condiciones_de_salto(self):
        holds = cpu.condition_holds
        self.assertTrue(holds(cpu.COND_ALWAYS, 0, 0, 0))
        self.assertTrue(holds(cpu.COND_Z, 0, 1, 0))
        self.assertFalse(holds(cpu.COND_Z, 0, 0, 0))
        self.assertTrue(holds(cpu.COND_NOT_Z_NOT_N, 1, 0, 0))
        self.assertFalse(holds(cpu.COND_NOT_Z_NOT_N, 1, 0, 1))
        self.assertTrue(holds(cpu.COND_C, 1, 0, 0))
        self.assertFalse(holds(0, 0, 0, 0), "condicion 0 nunca salta")


class TestInstruccionesBasicas(unittest.TestCase):
    def test_mov_y_add(self):
        program, machine = build(
            "DATA:\n  r 0\nCODE:\n"
            "  MOV A, 5\n  MOV B, 3\n  ADD A, B\n  MOV (r), A\n  JMP fin\nfin: JMP fin\n"
        )
        # El arranque inicializa la DATA con 2 palabras por valor.
        machine.run(program.code_start + 6)
        self.assertEqual(machine.registers[0], 8)
        self.assertEqual(machine.registers[1], 3)
        self.assertEqual(machine.ram[0], 8)

    def test_los_registros_reciben_el_resultado_de_la_alu(self):
        # MOV A, Lit es en realidad "ADD 0 + literal": A = 0 + 7.
        program, machine = build("CODE:\n  MOV A, 7\nfin: JMP fin\n")
        machine.run(1)
        self.assertEqual(machine.registers[0], 7)

    def test_resta_en_registro_y_banderas(self):
        program, machine = build(
            "CODE:\n  MOV A, 3\n  MOV B, 5\n  SUB A, B\nfin: JMP fin\n"
        )
        machine.run(3)
        self.assertEqual(machine.registers[0], 0xFFFE)
        self.assertEqual((machine.c, machine.z, machine.n), (0, 0, 1))

    def test_cmp_no_escribe_registro_ni_ram(self):
        program, machine = build(
            "DATA:\n  x 0\nCODE:\n  MOV A, 1\n  MOV B, 1\n  CMP A, B\nfin: JMP fin\n"
        )
        machine.run(program.code_start + 3)
        self.assertEqual(machine.registers[0], 1)
        self.assertEqual(machine.registers[1], 1)
        self.assertEqual(machine.ram[0], 0)
        self.assertEqual(machine.z, 1)

    def test_inc_y_dec(self):
        program, machine = build(
            "DATA:\n  x 5\nCODE:\n  INC A\n  DEC A\n  MOV A, (x)\n  INC (x)\nfin: JMP fin\n"
        )
        machine.run(program.code_start + 4)
        self.assertEqual(machine.ram[0], 6)
        self.assertEqual(machine.registers[0], 5)

    def test_simbolo_sin_parentesis_es_la_direccion(self):
        program, machine = build(
            "DATA:\n  x 5\n  y 0\nCODE:\n  MOV A, x\n  MOV B, (x)\nfin: JMP fin\n"
        )
        machine.run(program.code_start + 2)
        self.assertEqual(machine.registers[0], 0, "x es la direccion")
        self.assertEqual(machine.registers[1], 5, "(x) es el valor guardado")

    def test_not_y_desplazamientos_en_registro(self):
        program, machine = build(
            "CODE:\n  MOV A, 0x00FF\n  NOT A\n  MOV B, 0x8000\n  SHR B\nfin: JMP fin\n"
        )
        machine.run(4)
        self.assertEqual(machine.registers[0], 0xFF00)
        self.assertEqual(machine.registers[1], 0x4000)


class TestSaltos(unittest.TestCase):
    def test_cmp_y_salto_tomado(self):
        program, machine = build(
            "CODE:\n  MOV A, 1\n  CMP A, 1\n  JEQ igual\n"
            "  MOV A, 0\nigual:\n  JMP fin\nfin: JMP fin\n"
        )
        machine.run(60)
        self.assertEqual(machine.registers[0], 1)
        self.assertEqual(machine.pc & 0xFFF, program.symbols["fin"])

    def test_cmp_y_salto_no_tomado(self):
        program, machine = build(
            "CODE:\n  MOV A, 2\n  CMP A, 1\n  JEQ igual\n"
            "  MOV A, 9\nigual:\n  JMP fin\nfin: JMP fin\n"
        )
        machine.run(60)
        self.assertEqual(machine.registers[0], 9)

    def test_salto_pisa_las_banderas(self):
        # Rareza del hardware: el registro de estado se carga en cada flanco y
        # JMP tiene SelALU = 00000000 -> SHL(0) -> Z=1.  Por eso el JEQ que
        # viene despues del JMP se toma aunque A != B.
        source = (
            "CODE:\n  MOV A, 1\n  MOV B, 2\n  CMP A, B\n  JMP sigue\n"
            "sigue:\n  JEQ fin\n  MOV A, 0xDEAD\nfin:\n  JMP fin\n"
        )
        program, machine = build(source)
        machine.run(120)
        self.assertEqual(machine.registers[0], 1, "JEQ se tomo por Z=1 del JMP")

        program, sticky = build(source, flags_mode="sticky")
        sticky.run(120)
        self.assertEqual(sticky.registers[0], 0xDEAD, "en modo sticky Z sobrevive")

    def test_nop_pisa_las_banderas(self):
        source = "CODE:\n  MOV A, 1\n  CMP A, 1\n  NOP\n  JEQ fin\n  MOV A, 0xDEAD\nfin:\n  JMP fin\n"
        program, machine = build(source)
        machine.run(120)
        self.assertEqual(machine.registers[0], 1)

    def test_mov_pisa_las_banderas(self):
        source = "CODE:\n  MOV A, 0\n  CMP A, 0\n  MOV A, 5\n  JEQ fin\n  MOV A, 0xDEAD\nfin:\n  JMP fin\n"
        program, machine = build(source)
        machine.run(120)
        self.assertEqual(machine.registers[0], 0xDEAD, "MOV A,5 deja Z=0")

    def test_aviso_de_salto_sin_cmp(self):
        source = (
            "CODE:\n  MOV A, 1\n  MOV B, 2\n  CMP A, B\n  JMP sigue\n"
            "sigue:\n  JEQ fin\nfin:\n  JMP fin\n"
        )
        program, machine = build(source)
        machine.run(120)
        addresses = list(machine.flag_warnings.values())
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0].address, program.symbols["sigue"])
        self.assertIn("JMP", addresses[0].render())

    def test_sin_aviso_cuando_el_anterior_es_cmp(self):
        source = "CODE:\n  MOV A, 1\n  CMP A, 1\n  JEQ fin\nfin:\n  JMP fin\n"
        program, machine = build(source)
        machine.run(60)
        self.assertEqual(machine.flag_warnings, {})


class TestPila(unittest.TestCase):
    def test_sp_arranca_en_ffff(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        self.assertEqual(machine.sp, 0xFFFF)
        self.assertEqual(machine.sp & 0xFFF, 0xFFF)

    def test_push_escribe_en_fff_y_baja_sp(self):
        program, machine = build(
            "CODE:\n  MOV A, 0x1234\n  PUSH A\nfin: JMP fin\n"
        )
        machine.run(2)
        self.assertEqual(machine.ram[0xFFF], 0x1234)
        self.assertEqual(machine.sp & 0xFFF, 0xFFE)

    def test_push_pop_ida_y_vuelta(self):
        program, machine = build(
            "CODE:\n  MOV A, 0x1234\n  PUSH A\n  MOV A, 0\n  POP B\nfin: JMP fin\n"
        )
        # POP ocupa dos palabras (incrementa SP y luego lee).
        machine.run(5)
        self.assertEqual(machine.registers[1], 0x1234)
        self.assertEqual(machine.sp & 0xFFF, 0xFFF)
        self.assertEqual(machine.ram[0xFFF], 0x1234, "POP no borra la RAM")

    def test_call_guarda_la_direccion_de_retorno(self):
        program, machine = build(
            "CODE:\n  CALL sub\n  MOV A, 1\nfin:\n  JMP fin\n"
            "sub:\n  MOV A, 2\n  RET\n"
        )
        machine.run(30)
        self.assertEqual(machine.ram[0xFFF], 1, "CALL guarda PC+1 (0 + 1)")
        self.assertEqual(machine.registers[0], 1, "RET vuelve a la instruccion siguiente")
        self.assertEqual(machine.sp & 0xFFF, 0xFFF)

    def test_llamadas_anidadas(self):
        program, machine = build(
            "DATA:\n  marca 0\nCODE:\n"
            "  CALL uno\n  MOV A, 3\n  MOV (marca), A\nfin:\n  JMP fin\n"
            "uno:\n  MOV A, 1\n  CALL dos\n  ADD A, 10\n  RET\n"
            "dos:\n  MOV A, 2\n  RET\n"
        )
        machine.run(200)
        self.assertEqual(machine.ram[0], 3)
        self.assertEqual(machine.sp & 0xFFF, 0xFFF)
        self.assertEqual(machine.registers[0], 3)

    def test_push_sin_pop_desbalancea(self):
        program, machine = build(
            "CODE:\n  MOV A, 1\n  PUSH A\n  PUSH A\nfin: JMP fin\n"
        )
        machine.run(3)
        self.assertEqual(machine.sp & 0xFFF, 0xFFD)


class TestTimer(unittest.TestCase):
    def test_un_microsegundo_cada_100_ciclos(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        machine.run(99)
        self.assertEqual(machine.timer_microseconds, 0)
        machine.run(1)
        self.assertEqual(machine.timer_microseconds, 1)
        machine.run(100)
        self.assertEqual(machine.timer_microseconds, 2)

    def test_un_milisegundo_cada_100000_ciclos(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        machine.run(100_000)
        self.assertEqual(machine.timer_milliseconds, 1)
        self.assertEqual(machine.timer_microseconds, 0)

    def test_encadenado_us_ms_s(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        machine._us = 999
        machine._ms = 999
        machine._s = 5
        machine._prescaler = 99
        machine.step()
        self.assertEqual(
            (machine.timer_seconds, machine.timer_milliseconds, machine.timer_microseconds),
            (6, 0, 0),
        )

    def test_informe_de_tiempos(self):
        text = cpu.timing_report(50_000_000)
        self.assertIn("50.0 MHz", text)
        self.assertIn("416800", text)
        self.assertIn("100000", text)


class TestEntradaSalida(unittest.TestCase):
    def test_lectura_de_switches_por_instruccion(self):
        program, machine = build("CODE:\n  MOV A, (1)\nfin: JMP fin\n",
                                 switches=0x1234)
        machine.run(1)
        self.assertEqual(machine.registers[0], 0x1234)

    def test_lectura_de_botones(self):
        program, machine = build("CODE:\n  MOV A, (3)\nfin: JMP fin\n", buttons=0b101)
        machine.run(1)
        self.assertEqual(machine.registers[0], 0b101)

    def test_lectura_del_timer(self):
        program, machine = build(
            "CODE:\n  MOV A, (4)\n  MOV B, (5)\n  MOV C, (6)\nfin: JMP fin\n"
        )
        machine._s, machine._ms, machine._us = 7, 8, 9
        machine.run(3)
        self.assertEqual(
            (machine.registers[0], machine.registers[1], machine.registers[2]),
            (7, 8, 9),
        )

    def test_escritura_en_leds_y_ram(self):
        program, machine = build("CODE:\n  MOV A, 0x00AA\n  MOV (0), A\nfin: JMP fin\n")
        machine.run(2)
        self.assertEqual(machine.leds, 0xAA)
        self.assertEqual(machine.ram[0], 0xAA)

    def test_escritura_en_displays(self):
        program, machine = build("CODE:\n  MOV A, 0x00BB\n  MOV (2), A\nfin: JMP fin\n")
        machine.run(2)
        self.assertEqual(machine.display, 0xBB)
        self.assertEqual(machine.ram[2], 0xBB)

    def test_leer_no_escribe(self):
        program, machine = build("CODE:\n  MOV A, (5)\nfin: JMP fin\n")
        machine.run(1)
        self.assertEqual(machine.ram[5], 0)
        self.assertIsNone(machine.last_write)

    def test_escritura_en_1_alias_de_switches(self):
        # Escribir en 1 guarda en RAM[1]; leer 1 devuelve los switches.
        program, machine = build(
            "CODE:\n  MOV A, 0x00FF\n  MOV (1), A\nfin: JMP fin\n", switches=0x1234
        )
        machine.run(2)
        self.assertEqual(machine.ram[1], 0x00FF)
        self.assertEqual(machine.read(1), 0x1234)

    def test_ojo_de_buey_de_los_leds(self):
        # Direccion 0 es a la vez registro de LEDs y (Ax1, Ay1) del fondo.
        program, machine = build("CODE:\n  MOV A, 0x0102\n  MOV (0), A\nfin: JMP fin\n")
        machine.run(2)
        self.assertEqual(machine.ram[0], 0x0102)

    def test_lectura_fuera_de_rango_usa_bajo_12_bits(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        machine.ram[0x10] = 0xBEEF
        self.assertEqual(machine.read(0x1010), 0xBEEF)


class TestDireccionamientoIndirecto(unittest.TestCase):
    """Formas utiles para recorrer arreglos: el puntero va en un registro."""

    # Se usa la direccion 16 (por encima del bloque de E/S) para no chocar
    # con las direcciones que la lectura devuelve como entradas.
    _RELLENO = "  relleno" + " 0" * 16 + "\n"

    def test_mov_a_ram_con_puntero_en_registro(self):
        # MOV (B), A  ->  MEM[B] = A
        program, machine = build(
            "DATA:\n" + self._RELLENO + "  z 0\nCODE:\n"
            "  MOV B, 16\n  MOV A, 0x0042\n  MOV (B), A\nfin: JMP fin\n"
        )
        machine.run(program.code_start + 3)
        self.assertEqual(machine.ram[16], 0x0042)

    def test_inc_con_puntero_en_registro(self):
        # INC (B)  ->  MEM[B] = 1 + MEM[B]
        program, machine = build(
            "DATA:\n" + self._RELLENO + "  z 7\nCODE:\n"
            "  MOV B, 16\n  INC (B)\nfin: JMP fin\n"
        )
        machine.run(program.code_start + 2)
        self.assertEqual(machine.ram[16], 8)


class TestEntradasGuionadas(unittest.TestCase):
    def test_el_cambio_se_aplica_en_el_ciclo_indicado(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        machine.schedule_input(10, "buttons", 0b0100)
        machine.schedule_input(5, "switches", 0x00FF)
        # El evento con ciclo N se aplica al comenzar la instruccion N+1.
        machine.run(5)
        self.assertEqual(machine.switches, 0)
        machine.run(1)
        self.assertEqual(machine.switches, 0x00FF)
        machine.run(5)
        self.assertEqual(machine.buttons, 0b0100)

    def test_boton_guionado_mueve_la_nave(self):
        nave = EMU_DIR / "programas" / "05_nave.suasm"
        if not nave.exists():  # pragma: no cover
            self.skipTest("falta programas/05_nave.suasm")
        program = suasm.assemble_file(nave, TABLE)
        machine = cpu.Machine(rom=program.rom, keys=[row.key for row in program.listing])
        machine.init_words = program.code_start
        machine.schedule_input(50, "buttons", 4)   # izquierda
        machine.run(50)
        antes = machine.ram[8]
        machine.run(100)
        self.assertLess(machine.ram[8], antes)

    def test_campo_invalido(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        with self.assertRaises(ValueError):
            machine.schedule_input(0, "teclado", 1)


class TestAvisosDeDireccion(unittest.TestCase):
    def test_escribir_en_direccion_de_entrada(self):
        program, machine = build("CODE:\n  MOV A, 9\n  MOV (1), A\nfin: JMP fin\n")
        machine.run(2)
        self.assertEqual(machine.shadow_warnings, {1: 1})
        self.assertIn("[001]", machine.warnings_text())

    def test_la_inicializacion_de_data_no_avisa(self):
        program, machine = build(
            "DATA:\n  switches 0\n  x 0\nCODE:\n  MOV A, (x)\nfin: JMP fin\n"
        )
        machine.init_words = program.code_start
        machine.run(program.code_start + 1)
        self.assertEqual(machine.shadow_warnings, {})

    def test_escribir_en_leds_o_display_no_avisa(self):
        program, machine = build(
            "CODE:\n  MOV A, 1\n  MOV (0), A\n  MOV (2), A\nfin: JMP fin\n"
        )
        machine.run(3)
        self.assertEqual(machine.shadow_warnings, {})


class TestMaquina(unittest.TestCase):
    def test_rom_se_rellena_hasta_4096(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        self.assertEqual(len(machine.rom), 4096)
        self.assertEqual(machine.rom[program.size], 0)

    def test_rom_demasiado_grande(self):
        with self.assertRaises(ValueError):
            cpu.Machine(rom=[0] * 4097)

    def test_modo_de_banderas_invalido(self):
        with self.assertRaises(ValueError):
            cpu.Machine(rom=[0], flags_mode="otro")

    def test_trazado_de_estado(self):
        program, machine = build("CODE:\n  MOV A, 1\nfin: JMP fin\n")
        machine.run(2)
        text = machine.state_text()
        self.assertIn("PC=", text)
        self.assertIn("SP=", text)
        self.assertIn("A=0001", text)

    def test_volcado_de_ram(self):
        program, machine = build("CODE:\nfin: JMP fin\n")
        machine.ram[0] = 0x1111
        dump = machine.ram_dump(0, 4)
        self.assertIn("0000: 1111 0000 0000 0000", dump)

    def test_espera_alcanzar_una_etiqueta(self):
        program, machine = build("CODE:\n  MOV A, 1\n  MOV A, 2\nfin: JMP fin\n")
        reached = machine.run_until_pc(program.symbols["fin"], max_steps=100)
        self.assertTrue(reached)

    def test_ciclos_por_frame(self):
        self.assertEqual(cpu.CYCLES_PER_FRAME, 416_800)


if __name__ == "__main__":
    unittest.main()
