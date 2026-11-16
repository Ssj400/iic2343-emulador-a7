#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ensamblador del computador de ACF7: .suasm -> palabras ROM de 62 bits.

La palabra ROM tiene 62 bits: 16 de literal (bits 61..46) y 46 de control
(bits 45..0).  El archivo ``minki_opcodes.json`` del MinkiAssembler 2.0.2
contiene unicamente los 46 bits de control de cada mnemonico; el ensamblador
agrega el literal cuando la instruccion lo usa.

Reglas de fidelidad
-------------------
* La tabla de opcodes se usa tal cual: no se "corrigen" sus rarezas.
* El bloque DATA se inicializa al arranque con ``MOV A, valor`` +
  ``MOV (dir), A`` (dos palabras por valor).  Esto reproduce el diseno del
  ensamblador de ACF4, pero **NO esta verificado** contra MinkiAssembler.exe
  (es un binario de Windows y no se ejecuto).  Ver DISENO.md.
* La sintaxis aceptada es la documentada: ``DATA:`` / ``CODE:``, comentarios
  ``//`` y ``;``, literales decimal / ``0x`` / ``0b`` / sufijos ``d``, ``h``,
  ``b``, arreglos de varios valores y simbolos.  Los bordes no documentados
  se rechazan con error en vez de adivinarse.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

__all__ = [
    "AsmError",
    "DataEntry",
    "ListingRow",
    "Program",
    "assemble",
    "assemble_file",
    "build_key",
    "default_opcodes_path",
    "load_opcodes",
    "parse_instruction",
    "parse_int",
    "render_listing",
]

REGISTERS = ("A", "B", "C", "D")
WORD_BITS = 62
CTRL_BITS = 46
LITERAL_SHIFT = CTRL_BITS
CTRL_MASK = (1 << CTRL_BITS) - 1
RAM_WORDS = 4096

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AsmError(Exception):
    """Error de ensamblado con numero de linea cuando se conoce."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        self.message = message
        super().__init__(f"linea {line}: {message}" if line else message)


@dataclass
class DataEntry:
    name: str
    address: int
    values: list[int]
    line: int = 0

    @property
    def size(self) -> int:
        return len(self.values)


@dataclass
class ListingRow:
    """Una palabra de ROM con su origen, para el listado legible."""

    address: int
    literal: int
    control: int
    key: str
    source: str
    line: int = 0
    is_init: bool = False

    @property
    def literal_hex(self) -> str:
        return f"{self.literal & 0xFFFF:04X}"

    @property
    def control_hex(self) -> str:
        return f"{self.control:012X}"

    def render(self) -> str:
        return (
            f"{self.address:04X}  {self.literal_hex}  {self.control_hex}  "
            f"{self.source}"
        )


@dataclass
class Program:
    source_name: str = "<memoria>"
    rom: list[int] = field(default_factory=list)
    data: list[DataEntry] = field(default_factory=list)
    symbols: dict[str, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)
    listing: list[ListingRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def data_words(self) -> int:
        return sum(e.size for e in self.data)

    @property
    def code_start(self) -> int:
        """Direccion ROM de la primera instruccion del bloque CODE."""
        return 2 * self.data_words

    @property
    def size(self) -> int:
        return len(self.rom)

    def row_at(self, address: int) -> ListingRow | None:
        if 0 <= address < len(self.listing):
            return self.listing[address]
        return None


# ----------------------------------------------------------------------------
# Tabla de opcodes
# ----------------------------------------------------------------------------


def default_opcodes_path() -> Path:
    return Path(__file__).resolve().with_name("minki_opcodes.json")


def load_opcodes(path: str | Path | None = None) -> dict[str, list[str]]:
    """Carga la tabla de control y normaliza cada valor a una lista de palabras."""
    table_path = Path(path) if path else default_opcodes_path()
    try:
        raw = json.loads(table_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AsmError(
            f"no se pudo leer la tabla de opcodes {table_path}: {exc}. "
            "Si acabas de clonar el repositorio, falta el material del curso: "
            "ejecuta primero `python3 preparar_materiales.py <ZIP del proyecto base> "
            "<ZIP de MinkiAssembler>` (ver README)."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AsmError(f"tabla de opcodes invalida {table_path}: {exc}") from exc

    table: dict[str, list[str]] = {}
    for key, value in raw.items():
        norm = " ".join(key.split())
        words = [value] if isinstance(value, str) else list(value)
        for word in words:
            if len(word) != CTRL_BITS or set(word) - {"0", "1"}:
                raise AsmError(
                    f"la entrada '{key}' no es una palabra de control de "
                    f"{CTRL_BITS} bits"
                )
        table[norm] = words
    return table


# ----------------------------------------------------------------------------
# Literales y simbolos
# ----------------------------------------------------------------------------


def parse_int(token: str) -> int:
    """Interpreta un literal: decimal, 0x.., 0b.., sufijos d/h/b, con signo.

    Lanza ValueError si el token no es un numero.
    """
    text = token.strip().replace("_", "")
    if not text:
        raise ValueError("literal vacio")
    sign = 1
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1
        text = text[1:]
        if not text:
            raise ValueError(f"literal invalido: {token!r}")
    low = text.lower()
    if low.startswith("0x"):
        return sign * int(text[2:], 16)
    if low.startswith("0b"):
        return sign * int(text[2:], 2)
    if low.endswith("h"):
        return sign * int(text[:-1], 16)
    if low.endswith("d"):
        return sign * int(text[:-1], 10)
    if low.endswith("b"):
        return sign * int(text[:-1], 2)
    return sign * int(text, 10)


def _split_comment(line: str) -> str:
    cut = len(line)
    for marker in ("//", ";"):
        index = line.find(marker)
        if index != -1:
            cut = min(cut, index)
    return line[:cut]


def parse_instruction(text: str, line: int) -> tuple[str, list[str]]:
    parts = text.split(None, 1)
    mnemonic = parts[0].upper()
    if len(parts) == 1:
        return mnemonic, []
    operands = [op.strip() for op in parts[1].split(",")]
    if any(not op for op in operands):
        raise AsmError(f"operandos vacios en '{text}'", line)
    return mnemonic, operands


def is_register(token: str) -> bool:
    """True si el operando es un nombre de registro (A, B, C o D).

    Los registros son sensibles a mayusculas a proposito: si ``b`` tambien
    fuera registro, una variable llamada ``b`` seria ambigua.  La tabla de
    opcodes usa exclusivamente mayusculas, y el material del curso tambien.
    """
    return token in REGISTERS


def is_indirect(token: str) -> bool:
    return token.startswith("(") and token.endswith(")")


def is_indirect_register(token: str) -> bool:
    return is_indirect(token) and is_register(token[1:-1].strip())


def build_key(mnemonic: str, operands: Sequence[str]) -> str:
    """Traduce operandos concretos a la forma abstracta de la tabla."""
    parts: list[str] = []
    for operand in operands:
        text = operand.strip()
        if is_register(text):
            parts.append(text)
        elif is_indirect(text):
            inner = text[1:-1].strip()
            parts.append(f"({inner})" if is_register(inner) else "(dir)")
        else:
            parts.append("Lit")
    if not parts:
        return mnemonic
    return f"{mnemonic} " + ", ".join(parts)


def _bits(control: str, hi: int, lo: int) -> str:
    return control[CTRL_BITS - 1 - hi: CTRL_BITS - lo]


def uses_literal(control: str) -> bool:
    """True si la palabra de control lee el campo literal de 16 bits."""
    sel_two = _bits(control, 27, 24)
    sel_add = _bits(control, 33, 31)
    sel_pc = _bits(control, 45, 44)
    return sel_two == "0100" or sel_add == "001" or sel_pc == "01"


def _encode(control: str, literal: int) -> int:
    return ((literal & 0xFFFF) << LITERAL_SHIFT) | int(control, 2)


# ----------------------------------------------------------------------------
# Ensamblado
# ----------------------------------------------------------------------------


@dataclass
class _CodeItem:
    line: int
    label: str | None
    source: str
    mnemonic: str
    operands: list[str]
    key: str
    address: int


class _Assembler:
    def __init__(self, table: dict[str, list[str]], source_name: str):
        self.table = table
        self.source_name = source_name
        self.program = Program(source_name=source_name)
        self._raw_data: list[tuple[int, str, list[str]]] = []
        self._raw_code: list[tuple[int, str | None, str | None]] = []
        self._code_items: list[_CodeItem] = []

    # -- lectura de lineas ---------------------------------------------------

    def read(self, text: str) -> None:
        section: str | None = None
        for number, original in enumerate(text.splitlines(), 1):
            line = _split_comment(original).strip()
            if not line:
                continue
            head = line.upper()
            if head == "DATA:":
                section = "data"
                continue
            if head == "CODE:":
                section = "code"
                continue
            if section is None:
                raise AsmError("contenido antes de 'DATA:' o 'CODE:'", number)
            if section == "data":
                self._read_data(line, number)
            else:
                self._read_code(line, number)
        if section is None:
            self.program.warnings.append("el archivo no tiene DATA: ni CODE:")

    def _read_data(self, line: str, number: int) -> None:
        parts = line.replace(",", " ").split()
        name = parts[0]
        values = parts[1:]
        if not _IDENT_RE.match(name):
            raise AsmError(f"nombre de variable invalido: {name!r}", number)
        if not values:
            raise AsmError(f"la variable '{name}' no tiene valores", number)
        self._raw_data.append((number, name, values))

    def _read_code(self, line: str, number: int) -> None:
        label: str | None = None
        rest = line
        if ":" in line:
            head, tail = line.split(":", 1)
            head = head.strip()
            if not _IDENT_RE.match(head):
                raise AsmError(f"etiqueta invalida: {head!r}", number)
            label = head
            rest = tail.strip()
        self._raw_code.append((number, label, rest or None))

    # -- pasadas -------------------------------------------------------------

    def build(self) -> Program:
        self._layout_data()
        self._layout_code()
        self._emit_prologue()
        self._emit_code()
        self._check_rom()
        return self.program

    def _layout_data(self) -> None:
        address = 0
        for number, name, raw_values in self._raw_data:
            if name in self.program.symbols:
                raise AsmError(f"simbolo duplicado: '{name}'", number)
            self.program.symbols[name] = address
            values = [self._resolve(raw, number) for raw in raw_values]
            entry = DataEntry(name=name, address=address, values=values, line=number)
            self.program.data.append(entry)
            address += entry.size
            if address > RAM_WORDS:
                raise AsmError("el bloque DATA no cabe en 4096 palabras", number)

    def _layout_code(self) -> None:
        address = self.program.code_start
        for number, label, source in self._raw_code:
            if label is not None:
                if label in self.program.symbols:
                    raise AsmError(f"simbolo duplicado: '{label}'", number)
                self.program.symbols[label] = address
                self.program.labels[label] = address
            if source is None:
                continue
            mnemonic, operands = parse_instruction(source, number)
            key = build_key(mnemonic, operands)
            if key not in self.table:
                raise AsmError(self._unknown_key_message(key, mnemonic), number)
            self._code_items.append(
                _CodeItem(
                    line=number,
                    label=label,
                    source=source,
                    mnemonic=mnemonic,
                    operands=operands,
                    key=key,
                    address=address,
                )
            )
            address += len(self.table[key])

    def _unknown_key_message(self, key: str, mnemonic: str) -> str:
        forms = sorted(k for k in self.table if k.split(" ", 1)[0] == mnemonic)
        if not forms:
            return f"mnemonico desconocido: '{mnemonic}'"
        shown = "; ".join(forms[:12])
        extra = "" if len(forms) <= 12 else f" (y {len(forms) - 12} formas mas)"
        return f"no existe la forma '{key}'. Formas de {mnemonic}: {shown}{extra}"

    def _resolve(self, token: str, line: int) -> int:
        try:
            return parse_int(token)
        except ValueError:
            pass
        if token in self.program.symbols:
            return self.program.symbols[token]
        hint = ""
        if len(token) == 1 and token.upper() in REGISTERS:
            hint = f" (los registros se escriben en mayuscula: '{token.upper()}')"
        raise AsmError(f"simbolo o literal desconocido: {token!r}{hint}", line)

    def _literal_for(self, item: _CodeItem) -> int:
        controls = self.table[item.key]
        needs = any(uses_literal(c) for c in controls)
        found: str | None = None
        for operand in item.operands:
            text = operand.strip()
            if is_register(text):
                continue
            if is_indirect(text):
                inner = text[1:-1].strip()
                if is_register(inner):
                    continue
                found = inner
            else:
                found = text
            break
        if found is None:
            if not needs:
                return 0
            if item.mnemonic == "DEC":
                # DEC A/B/C/D usa el literal implicito 1 (SelTwo = 0100).
                return 1
            raise AsmError(
                f"'{item.source}' usa el campo literal pero no indica ningun "
                f"operando con valor",
                item.line,
            )
        return self._resolve(found, item.line)

    def _emit_prologue(self) -> None:
        mov_lit = self.table["MOV A, Lit"][0]
        mov_dir = self.table["MOV (dir), A"][0]
        for entry in self.program.data:
            for index, value in enumerate(entry.values):
                address = entry.address + index
                for control, literal, kind in (
                    (mov_lit, value, "valor"),
                    (mov_dir, address, "direccion"),
                ):
                    self._append(
                        control=control,
                        literal=literal,
                        key=f"init {entry.name}[{index}] {kind}",
                        source=f"; init {entry.name}[{index}] = {value}",
                        line=entry.line,
                        is_init=True,
                    )

    def _emit_code(self) -> None:
        for item in self._code_items:
            literal = self._literal_for(item)
            for control in self.table[item.key]:
                self._append(
                    control=control,
                    literal=literal,
                    key=item.key,
                    source=item.source,
                    line=item.line,
                )

    def _append(
        self,
        *,
        control: str,
        literal: int,
        key: str,
        source: str,
        line: int,
        is_init: bool = False,
    ) -> None:
        address = len(self.program.rom)
        if address >= RAM_WORDS:
            raise AsmError("el programa no cabe en 4096 palabras de ROM", line)
        word = _encode(control, literal)
        self.program.rom.append(word)
        self.program.listing.append(
            ListingRow(
                address=address,
                literal=literal & 0xFFFF,
                control=int(control, 2),
                key=key,
                source=source,
                line=line,
                is_init=is_init,
            )
        )

    def _check_rom(self) -> None:
        if not self.program.rom:
            return
        if self.program.size > RAM_WORDS:
            raise AsmError("el programa excede la ROM de 4096 palabras")


def assemble(
    text: str,
    table: dict[str, list[str]] | None = None,
    source_name: str = "<memoria>",
) -> Program:
    assembler = _Assembler(table or load_opcodes(), source_name)
    assembler.read(text)
    return assembler.build()


def assemble_file(
    path: str | Path,
    table: dict[str, list[str]] | None = None,
) -> Program:
    program_path = Path(path)
    try:
        text = program_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AsmError(f"no se pudo leer {program_path}: {exc}") from exc
    return assemble(text, table, source_name=str(program_path))


# ----------------------------------------------------------------------------
# Listado
# ----------------------------------------------------------------------------


def render_listing(program: Program, limit: int | None = None) -> str:
    rows = program.listing if limit is None else program.listing[:limit]
    lines = [
        f"Listado ROM de {program.source_name}: {program.size} palabras "
        f"({program.data_words} de DATA, "
        f"{program.size - 2 * program.data_words} de CODE)",
        "",
        "dir   lit   control       fuente",
    ]
    for row in rows:
        lines.append(row.render())
    if limit is not None and len(program.listing) > limit:
        lines.append(f"... ({len(program.listing) - limit} palabras mas)")
    return "\n".join(lines)


def render_symbols(program: Program) -> str:
    if not program.symbols:
        return "(sin simbolos)"
    width = max(len(name) for name in program.symbols)
    lines = []
    for name in sorted(program.symbols, key=lambda n: program.symbols[n]):
        kind = "RAM" if name in {e.name for e in program.data} else "ROM"
        lines.append(f"{name:<{width}}  {program.symbols[name]:04X}  {kind}")
    return "\n".join(lines)
