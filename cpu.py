#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Maquina del computador de ACF7 a nivel de instruccion.

Modela lo que hace el VHDL entregado, no lo que "deberia" hacer:

* cada instruccion ocupa un ciclo de la senal de reloj reducida;
* las lecturas de ROM y RAM son combinacionales;
* el registro de estado se carga en **todos** los flancos
  (``RegisterFile.vhd``: ``load => '1'``), asi que cualquier instruccion pisa
  las banderas, incluidos los saltos y ``NOP``;
* los registros A-D reciben el resultado de la ALU; ``SelDIn`` solo decide que
  se escribe en RAM (resultado de la ALU o ``PC+1``, usado por ``CALL``);
* ``SP`` arranca en ``0xFFFF`` cuando se asserta ``clear`` y sus 12 bits bajos
  son la direccion.

Las rarezas se reproducen, pero quedan configurables o con aviso:

``flags_mode``
    ``"hardware"`` (por defecto) carga las banderas en cada ciclo.
    ``"sticky"`` es una variante **hipotetica** (no es el hardware) en la que
    solo las instrucciones con operacion de ALU real tocan las banderas;
    sirve para separar "mi programa esta mal" de "el hardware pisa Z".

``warn_branch_without_cmp``
    registra un aviso cuando un salto condicional se ejecuta y la instruccion
    inmediatamente anterior no fue ``CMP``: en ese caso la bandera usada viene
    de otra instruccion (y si fue un salto, vale ``Z=1``).

Nada de esto esta validado contra la placa: ver DISENO.md, seccion
"no verificado en hardware".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

__all__ = [
    "CTRL_MASK",
    "CYCLES_PER_FRAME",
    "LITERAL_SHIFT",
    "RAM_WORDS",
    "SHADOWED_ADDRESSES",
    "Machine",
    "alu",
    "condition_holds",
    "decode_control",
    "timing_report",
]

LITERAL_SHIFT = 46
CTRL_MASK = (1 << 46) - 1
RAM_WORDS = 4096
WORD_MASK = 0xFFFF

# Xelor: 800 x 521 ciclos por frame = 416_800 ciclos.
CYCLES_PER_FRAME = 416_800
# Timer.vhd: contador 0..99, luego useg 0..999, mseg 0..999, seg...
CYCLES_PER_MICROSECOND = 100
CYCLES_PER_MILLISECOND = CYCLES_PER_MICROSECOND * 1000
CYCLES_PER_SECOND = CYCLES_PER_MILLISECOND * 1000

# Condiciones de loadPC (ControlUnit.vhd, bits 43..36).
COND_ALWAYS = 0b00000001
COND_Z = 0b00000010
COND_NOT_Z = 0b00000100
COND_NOT_Z_NOT_N = 0b00001000
COND_NOT_N = 0b00010000
COND_N = 0b00100000
COND_Z_OR_N = 0b01000000
COND_C = 0b10000000
CONDITIONAL = frozenset(
    {COND_Z, COND_NOT_Z, COND_NOT_Z_NOT_N, COND_NOT_N, COND_N, COND_Z_OR_N, COND_C}
)

# Direcciones cuya lectura devuelve E/S, no el valor guardado en RAM.
SHADOWED_ADDRESSES = frozenset({1, 3, 4, 5, 6})

_ALU_OPS: list[str] = ["SHL"] * 256
_ALU_OPS[0b00000001] = "ADD"
_ALU_OPS[0b00000010] = "SUB"
_ALU_OPS[0b00000100] = "AND"
_ALU_OPS[0b00001000] = "OR"
_ALU_OPS[0b00010000] = "XOR"
_ALU_OPS[0b00100000] = "NOT"
_ALU_OPS[0b01000000] = "SHR"
_ALU_OPS[0b10000000] = "SHL"

# one-hot -> indice de registro; cualquier otro valor cae en D (cuarto).
_REG_INDEX = {0b0001: 0, 0b0010: 1, 0b0100: 2}
REGISTER_NAMES = ("A", "B", "C", "D")


def decode_control(control: int) -> tuple:
    """Decodifica los 46 bits de control segun ControlUnit.vhd.

    Devuelve una tupla:
    (op, lreg, reg1, reg2, regdst, one, two, seldin, w, add, incsp, decsp,
     cond, selpc)
    """
    return (
        _ALU_OPS[control & 0xFF],
        (control >> 8) & 1,
        _REG_INDEX.get((control >> 9) & 0xF, 3),
        _REG_INDEX.get((control >> 13) & 0xF, 3),
        _REG_INDEX.get((control >> 17) & 0xF, 3),
        (control >> 21) & 0x7,
        (control >> 24) & 0xF,
        (control >> 28) & 0x3,
        (control >> 30) & 1,
        (control >> 31) & 0x7,
        (control >> 34) & 1,
        (control >> 35) & 1,
        (control >> 36) & 0xFF,
        (control >> 44) & 0x3,
    )


def condition_holds(cond: int, c: int, z: int, n: int) -> bool:
    """Evalua la condicion de loadPC con el estado *anterior* al flanco."""
    if cond == COND_ALWAYS:
        return True
    if cond == COND_Z:
        return z == 1
    if cond == COND_NOT_Z:
        return z == 0
    if cond == COND_NOT_Z_NOT_N:
        return z == 0 and n == 0
    if cond == COND_NOT_N:
        return n == 0
    if cond == COND_N:
        return n == 1
    if cond == COND_Z_OR_N:
        return z == 1 or n == 1
    if cond == COND_C:
        return c == 1
    return False


def alu(a: int, b: int, op: str) -> tuple[int, int, int, int]:
    """ALU.vhd: devuelve (resultado, C, Z, N) sin signo."""
    a &= WORD_MASK
    b &= WORD_MASK
    if op == "ADD":
        raw = a + b
        c = 1 if raw > WORD_MASK else 0
        result = raw & WORD_MASK
        n = 0
    elif op == "SUB":
        raw = a + ((~b) & WORD_MASK) + 1
        c = 1 if raw > WORD_MASK else 0
        result = raw & WORD_MASK
        # ALU.vhd: n <= not cout_adder when sop = "001"
        n = 0 if c else 1
    elif op == "AND":
        result = a & b
        c = 0
        n = 0
    elif op == "OR":
        result = a | b
        c = 0
        n = 0
    elif op == "XOR":
        result = a ^ b
        c = 0
        n = 0
    elif op == "NOT":
        result = (~a) & WORD_MASK
        c = 0
        n = 0
    elif op == "SHR":
        result = a >> 1
        c = a & 1
        n = 0
    else:  # SHL, incluido el caso por defecto (bits ALU = 00000000)
        result = (a << 1) & WORD_MASK
        c = (a >> 15) & 1
        n = 0
    z = 1 if result == 0 else 0
    return result, c, z, n


@dataclass
class FlagWarning:
    address: int
    previous_key: str
    count: int = 1

    def render(self) -> str:
        return (
            f"PC={self.address:04X}: salto condicional tras "
            f"'{self.previous_key}' (no CMP); banderas recicladas, "
            f"{self.count} vez/veces"
        )


@dataclass
class Machine:
    """Estado completo del computador."""

    rom: Sequence[int] = field(default_factory=list)
    keys: Sequence[str] = field(default_factory=list)
    switches: int = 0
    buttons: int = 0
    flags_mode: str = "hardware"
    warn_branch_without_cmp: bool = True
    clock_hz: int = 50_000_000
    cycles_per_frame: int = CYCLES_PER_FRAME
    input_events: list[tuple[int, str, int]] = field(default_factory=list)
    init_words: int = 0

    def __post_init__(self) -> None:
        if self.flags_mode not in ("hardware", "sticky"):
            raise ValueError("flags_mode debe ser 'hardware' o 'sticky'")
        rom = list(self.rom)
        if len(rom) > RAM_WORDS:
            raise ValueError("la ROM no puede tener mas de 4096 palabras")
        rom.extend([0] * (RAM_WORDS - len(rom)))
        self.rom = rom
        self._decode_cache: dict[int, tuple] = {}
        self.flag_warnings: dict[int, FlagWarning] = {}
        self.reset()

    # -- estado --------------------------------------------------------------

    def reset(self) -> None:
        self.registers: list[int] = [0, 0, 0, 0]
        self.ram: list[int] = [0] * RAM_WORDS
        self.pc: int = 0
        self.sp: int = 0xFFFF
        self.c = 0
        self.z = 0
        self.n = 0
        self.cycles = 0
        self.leds = 0
        self.display = 0
        self._prescaler = 0
        self._us = 0
        self._ms = 0
        self._s = 0
        self.last_write: tuple[int, int] | None = None
        self.last_pc = 0
        self._prev_key: str | None = None
        self._input_index = 0
        self.shadow_warnings: dict[int, int] = {}
        # Direcciones que alguna vez recibieron una escritura.  Los sprites
        # usan esto para distinguir "nunca se le dio posicion" (el registro
        # del componente arranca en 640 y el sprite esta fuera de pantalla)
        # de "se le escribio el valor 0".
        self.written_addresses: set[int] = set()

    # -- I/O -----------------------------------------------------------------

    @property
    def timer_microseconds(self) -> int:
        return self._us

    @property
    def timer_milliseconds(self) -> int:
        return self._ms

    @property
    def timer_seconds(self) -> int:
        return self._s

    def read(self, address: int) -> int:
        """Multiplexor de lectura de Basys3.vhd."""
        addr = address & 0xFFF
        if addr == 1:
            return self.switches & WORD_MASK
        if addr == 3:
            # Debouncer: el emulador no modela el rebote, solo el valor.
            return self.buttons & 0x1F
        if addr == 4:
            return self._s
        if addr == 5:
            return self._ms
        if addr == 6:
            return self._us
        return self.ram[addr]

    def _write(self, address: int, value: int) -> None:
        """Escritura de RAM + registros de salida (ambos reciben write_ram)."""
        addr = address & 0xFFF
        value &= WORD_MASK
        self.ram[addr] = value
        if addr == 0:
            self.leds = value
        elif addr == 2:
            self.display = value
        elif addr in SHADOWED_ADDRESSES and self.pc >= self.init_words:
            # Escribir aqui guarda en RAM, pero leer la misma direccion
            # devuelve la entrada o el timer: el dato no se puede recuperar.
            self.shadow_warnings[addr] = self.shadow_warnings.get(addr, 0) + 1
        self.last_write = (addr, value)
        self.written_addresses.add(addr)

    # -- entradas guionadas --------------------------------------------------

    def schedule_input(self, cycle: int, field: str, value: int) -> None:
        """Programa un cambio de entrada en un ciclo dado.

        ``field`` es ``"switches"`` o ``"buttons"``.  Sirve para probar
        programas interactivos sin la placa; el cambio se aplica al comenzar
        el ciclo indicado.
        """
        if field not in ("switches", "buttons"):
            raise ValueError("field debe ser 'switches' o 'buttons'")
        self.input_events.append((int(cycle), field, int(value) & WORD_MASK))
        self.input_events.sort()
        self._input_index = 0

    def _apply_inputs(self) -> None:
        while (
            self._input_index < len(self.input_events)
            and self.input_events[self._input_index][0] <= self.cycles
        ):
            _, field, value = self.input_events[self._input_index]
            if field == "switches":
                self.switches = value
            else:
                self.buttons = value & 0x1F
            self._input_index += 1

    # -- ejecucion -----------------------------------------------------------

    def _tick_timer(self) -> None:
        if self._prescaler == 99:
            self._prescaler = 0
            if self._us == 999:
                self._us = 0
                if self._ms == 999:
                    self._ms = 0
                    self._s = (self._s + 1) & WORD_MASK
                else:
                    self._ms += 1
            else:
                self._us += 1
        else:
            self._prescaler += 1

    def step(self) -> None:
        """Ejecuta un ciclo (una instruccion)."""
        self._apply_inputs()
        pc = self.pc
        word = self.rom[pc & 0xFFF]
        control = word & CTRL_MASK
        literal = (word >> LITERAL_SHIFT) & WORD_MASK

        decoded = self._decode_cache.get(control)
        if decoded is None:
            decoded = decode_control(control)
            self._decode_cache[control] = decoded
        (
            op, lreg, reg1, reg2, regdst,
            one, two, seldin, write_ram,
            seladd, incsp, decsp, cond, selpc,
        ) = decoded

        registers = self.registers
        first = registers[reg1]
        second = registers[reg2]

        if one == 0b001:
            a = first
        elif one == 0b010:
            a = 1
        else:
            a = 0

        if two == 0b0001:
            b: int | None = second
        elif two == 0b0010:
            b = 0
        elif two == 0b0100:
            b = literal
        else:
            b = None  # se lee de RAM/I-O

        if seladd == 0b001:
            address = literal & 0xFFF
        elif seladd == 0b010:
            address = second & 0xFFF
        else:
            address = self.sp & 0xFFF

        mem_out = self.read(address)
        if b is None:
            b = mem_out

        result, c, z, n = alu(a, b, op)
        datain = result if seldin == 0b01 else ((pc + 1) & WORD_MASK)

        # loadPC usa el estado anterior al flanco.
        taken = condition_holds(cond, self.c, self.z, self.n)

        self.last_pc = pc
        self.last_write = None

        if lreg:
            registers[regdst] = result
        if write_ram:
            self._write(address, datain)

        # RegisterFile.vhd: el status se carga en *todos* los flancos.
        real_alu_op = (control & 0xFF) != 0
        if self.flags_mode == "hardware" or real_alu_op:
            self.c, self.z, self.n = c, z, n

        if taken:
            self.pc = (literal & 0xFFF) if selpc == 0b01 else (mem_out & 0xFFF)
        else:
            self.pc = (pc + 1) & WORD_MASK

        if incsp:
            self.sp = (self.sp + 1) & WORD_MASK
        elif decsp:
            self.sp = (self.sp - 1) & WORD_MASK

        if self.warn_branch_without_cmp and cond in CONDITIONAL:
            self._check_flag_source(pc & 0xFFF)

        self._prev_key = self._key_at(pc & 0xFFF)
        self._tick_timer()
        self.cycles += 1

    def _key_at(self, address: int) -> str:
        if 0 <= address < len(self.keys):
            return self.keys[address]
        return "?"

    def _check_flag_source(self, address: int) -> None:
        previous = self._prev_key
        if previous is None or previous.startswith("CMP"):
            return
        record = self.flag_warnings.get(address)
        if record is None:
            self.flag_warnings[address] = FlagWarning(address, previous)
        else:
            record.count += 1

    def run(self, steps: int) -> None:
        for _ in range(steps):
            self.step()

    def run_frames(self, frames: int) -> None:
        self.run(frames * self.cycles_per_frame)

    def run_until_pc(self, address: int, max_steps: int = 1_000_000) -> bool:
        for _ in range(max_steps):
            if (self.pc & 0xFFF) == address:
                return True
            self.step()
        return False

    # -- informes ------------------------------------------------------------

    @property
    def flags_text(self) -> str:
        return f"C={self.c} Z={self.z} N={self.n}"

    @property
    def registers_text(self) -> str:
        return " ".join(
            f"{name}={value:04X}" for name, value in zip(REGISTER_NAMES, self.registers)
        )

    def state_text(self) -> str:
        return (
            f"ciclos={self.cycles} PC={self.pc & 0xFFF:04X} SP={self.sp & 0xFFF:03X} "
            f"{self.registers_text} {self.flags_text} "
            f"timer={self._s:03d}.{self._ms:03d}.{self._us:03d}"
        )

    def warnings_text(self) -> str:
        lines = [
            w.render()
            for w in sorted(self.flag_warnings.values(), key=lambda w: w.address)
        ]
        for address in sorted(self.shadow_warnings):
            count = self.shadow_warnings[address]
            lines.append(
                f"escritura en [{address:03X}] desde el programa: es una "
                f"direccion de E/S, leerla no devuelve el valor guardado "
                f"({count} vez/veces)"
            )
        return "\n".join(lines)

    def ram_dump(self, start: int, end: int) -> str:
        start = max(0, start)
        end = min(RAM_WORDS, end)
        lines = []
        for base in range(start, end, 8):
            chunk = self.ram[base: min(base + 8, end)]
            cells = " ".join(f"{value:04X}" for value in chunk)
            lines.append(f"{base:04X}: {cells}")
        return "\n".join(lines)


def timing_report(clock_hz: int = 50_000_000) -> str:
    """Tiempos derivados del VHDL; util para razonar sobre el timer."""
    frame_us = CYCLES_PER_FRAME / clock_hz * 1e6
    ms_cycles = CYCLES_PER_MILLISECOND
    tick_s = ms_cycles / clock_hz
    return (
        f"reloj asumido {clock_hz/1e6:.1f} MHz (Clock_Divider speed=\"00\"):\n"
        f"  {CYCLES_PER_FRAME} ciclos/frame = {frame_us/1000:.2f} ms "
        f"({clock_hz/CYCLES_PER_FRAME:.1f} Hz)\n"
        f"  un tick de timer_milisegundos = {ms_cycles} ciclos = "
        f"{tick_s*1000:.2f} ms reales\n"
        f"  timer_segundos avanza cada {CYCLES_PER_SECOND/clock_hz:.2f} s reales\n"
        f"  el contador de ms envuelve cada "
        f"{1000 * CYCLES_PER_MILLISECOND / clock_hz:.2f} s reales"
    )
