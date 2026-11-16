#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rasterizador de los sprites VGA de ACF7 (sin monitor).

Reproduce lo que hacen ``GraphicsProcessor.vhd`` y los cuatro *sprite
managers* del proyecto entregado:

* ``backgroundSM``   300x300 en las direcciones 0/0, **sin** prueba de caja
* ``mainShipSM``      69x90  en las direcciones 10/11
* ``enemyShipSM``     30x30  en las direcciones 12/13
* ``ammoSM``          10x10  en las direcciones 14/15

Reglas copiadas del VHDL (``../_x/``):

1. Se lee ``x1`` e ``y1`` cuando el programa escribe esas direcciones.
   Mientras nadie escriba, el registro vale ``x1 = 640`` (casi fuera de
   pantalla: deja una franja de 2 columnas en el borde derecho).
2. La ventana es ``x1-2 <= x < x1+ancho-2`` y ``y1 <= y < y1+alto`` con
   ``hDiff = 2``.  El ``-2`` compensa el retardo de dos ciclos del pipeline
   (registro de direccion + BRAM).
3. El indice dentro de la imagen es ``(x + 2 - x1) + (y - y1) * ancho``.
4. Un pixel cuyo color es ``000000`` es **transparente**: ``inside_area``
   vale 0 y se ve el sprite siguiente.
5. Prioridad fija: nave > enemigo > municion > fondo.
6. El fondo no comprueba ventana: su direccion es
   ``(x + 2 - x1) + (y - y1) * 300`` en todo el cuadro.  Como 640 > 300, a
   partir de x = 298 la direccion se corre a la fila siguiente de la imagen;
   para y >= 300 pasa de las 90 000 palabras y el BRAM devuelve 0 (negro);
   y desde y = 435 el truncamiento de esa cuenta a 17 bits la trae de vuelta
   dentro de la imagen.  Las tres cosas las hace el hardware; no son errores
   del emulador.
7. El fondo lee ``Ax1 = Ay1 = 000``, la misma direccion que el registro de
   LEDs (direccion 0).  Escribir los LEDs corre el fondo en diagonal.

No se modela el *tearing* real (en la placa la CPU escribe mientras el raster
barre, asi que se ven parpadeos a media pantalla): aqui cada imagen es una
foto consistente de la RAM en un instante.

Extension del emulador, **no del proyecto entregado**: ``extra_enemies=N``
anade N enemigos mas (30x30, ``nave_azul``) que escuchan ``x`` en 16+2k e
``y`` en 17+2k, con la misma transparencia y prioridad que ``enemyShipSM``.
Sirve para practicar el caso de >=10 aliens. Es una *suposicion*: la base
evaluada de A7 no esta publicada y podria traer ya las instancias (o usar
otras direcciones). Con ``N = 0`` no cambia nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = [
    "HDIFF",
    "SCREEN_W",
    "SCREEN_H",
    "SPRITES",
    "EXTRA_ENEMY_AX",
    "SpriteDef",
    "SpriteImage",
    "extra_enemy_defs",
    "sprites_with_extras",
    "load_coe",
    "load_sprite_images",
    "positions",
    "render",
    "describe",
]

SCREEN_W = 640
SCREEN_H = 480
HDIFF = 2

COE_DIR = Path(__file__).resolve().parent / "coe"


# ----------------------------------------------------------------------------
# Imagenes (.coe de Xilinx)
# ----------------------------------------------------------------------------

def load_coe(path: Path) -> list[int]:
    """Lee un ``.coe`` de Xilinx y devuelve la lista de valores.

    Solo se aceptan los que traen ``memory_initialization_radix`` y
    ``memory_initialization_vector``, que es el formato de los 12 archivos del
    proyecto entregado.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if "memory_initialization_vector" not in text:
        raise ValueError(f"{path}: no tiene memory_initialization_vector")
    radix = 16
    match = re.search(r"memory_initialization_radix\s*=\s*(\d+)", text)
    if match:
        radix = int(match.group(1))
    body = text.split("memory_initialization_vector", 1)[1]
    body = body.split("=", 1)[1] if "=" in body else body
    body = body.split(";", 1)[0]
    values = []
    for token in re.split(r"[\s,]+", body):
        token = token.strip()
        if token:
            values.append(int(token, radix))
    if not values:
        raise ValueError(f"{path}: vector vacio")
    return values


@dataclass(frozen=True)
class SpriteDef:
    """Un componente *sprite manager* del proyecto."""

    name: str
    label: str
    width: int
    height: int
    ax: int
    ay: int
    default_x: int = 640
    default_y: int = 0
    has_window: bool = True
    rom: str = ""


# Los comentarios de cada linea dicen que componente del VHDL lo respalda.
SPRITES: tuple[SpriteDef, ...] = (
    # backgroundSM.vhd: 300x300, Ax1=Ay1=000, x1=y1=0, sin ventana.
    SpriteDef("background", "fondo", 300, 300, 0x000, 0x000,
              default_x=0, default_y=0, has_window=False,
              rom="background"),
    # ammoSM.vhd: 10x10, Ax1=00E, Ay1=00F.
    SpriteDef("ammo", "municion", 10, 10, 0x00E, 0x00F, rom="good_ammo"),
    # enemyShipSM.vhd: 30x30, Ax1=00C, Ay1=00D.
    SpriteDef("enemyShip", "nave enemiga", 30, 30, 0x00C, 0x00D, rom="nave_azul"),
    # mainShipSM.vhd: 69x90, Ax1=00A, Ay1=00B.
    SpriteDef("mainShip", "nave", 69, 90, 0x00A, 0x00B, rom="nave_principal"),
)

# Extension del emulador (ver el docstring): un enemigo extra ocupa el par de
# direcciones 16/17, el siguiente 18/19, etc.  Es una suposicion de practica,
# no una constante del proyecto entregado, que solo trae un enemyShipSM.
EXTRA_ENEMY_AX = 0x010
RAM_LAST_ADDRESS = 0xFFF


def extra_enemy_defs(count: int) -> tuple[SpriteDef, ...]:
    """``count`` enemigos extra de 30x30 con ``nave_azul``.

    El ``k``-esimo (``k = 0..count-1``) escucha ``x`` en ``16 + 2k`` e ``y`` en
    ``17 + 2k``.  Arranca en ``x1 = 640`` igual que los demas componentes y solo
    se dibuja cuando el programa escribe esas direcciones.
    """
    if count < 0:
        raise ValueError("extra_enemies no puede ser negativo")
    if count:
        last = EXTRA_ENEMY_AX + 2 * (count - 1) + 1
        if last > RAM_LAST_ADDRESS:
            raise ValueError(
                f"extra_enemies={count} pide la direccion {last}, "
                f"fuera de las 4096 palabras de RAM"
            )
    return tuple(
        SpriteDef(
            name=f"extraEnemy{k}",
            label=f"enemigo extra {k}",
            width=30,
            height=30,
            ax=EXTRA_ENEMY_AX + 2 * k,
            ay=EXTRA_ENEMY_AX + 2 * k + 1,
            rom="nave_azul",
        )
        for k in range(count)
    )


def sprites_with_extras(
    extra_enemies: int = 0,
    sprites: tuple[SpriteDef, ...] = SPRITES,
) -> tuple[SpriteDef, ...]:
    """Copia de ``sprites`` (ordenada por prioridad) mas los enemigos extra.

    Los extra empatan en prioridad con ``enemyShipSM`` y se colocan justo
    despues, o sea quedan igualmente por debajo de la nave y por encima de la
    municion.  Entre ellos gana el de indice mayor (ultimo pintado).
    """
    extras = extra_enemy_defs(extra_enemies)
    if not extras:
        return sprites
    result: list[SpriteDef] = []
    inserted = False
    for sprite in sprites:
        result.append(sprite)
        if sprite.name == "enemyShip":
            result.extend(extras)
            inserted = True
    if not inserted:
        # Si se paso una lista sin el enemigo base, los extra van al final
        # (arriba de todo); documentado, no es el uso normal.
        result.extend(extras)
    return tuple(result)


def _image_for(
    definition: SpriteDef,
    images: dict[str, SpriteImage],
) -> SpriteImage | None:
    """Imagen de un sprite; los extra reutilizan la de su ``rom``."""
    image = images.get(definition.name)
    if image is not None:
        return image
    for candidate in images.values():
        if candidate.definition.rom == definition.rom:
            return candidate
    return None


@dataclass
class SpriteImage:
    """Los tres canales de un sprite, ya separados en 4 bits por componente."""

    definition: SpriteDef
    red: np.ndarray = field(repr=False)
    green: np.ndarray = field(repr=False)
    blue: np.ndarray = field(repr=False)

    @property
    def size(self) -> int:
        return int(self.red.size)


def load_sprite_images(coe_dir: Path | None = None) -> dict[str, SpriteImage]:
    """Carga los 12 ``.coe`` (4 sprites x 3 canales)."""
    directory = Path(coe_dir) if coe_dir else COE_DIR
    images: dict[str, SpriteImage] = {}
    for definition in SPRITES:
        channels = {}
        for name in ("RED", "GREEN", "BLUE"):
            path = directory / f"{definition.rom}_{name}.coe"
            if not path.exists():
                raise FileNotFoundError(
                    f"falta {path}. Si acabas de clonar el repositorio, ejecuta primero "
                    "`python3 preparar_materiales.py <ZIP del proyecto base> "
                    "<ZIP de MinkiAssembler>` (ver README)."
                )
            channels[name] = np.array(load_coe(path), dtype=np.uint8)
        expected = definition.width * definition.height
        for name, values in channels.items():
            if values.size != expected:
                raise ValueError(
                    f"{definition.rom}_{name}.coe tiene {values.size} valores, "
                    f"se esperaban {expected} "
                    f"({definition.width}x{definition.height})"
                )
        images[definition.name] = SpriteImage(
            definition,
            channels["RED"],
            channels["GREEN"],
            channels["BLUE"],
        )
    return images


# ----------------------------------------------------------------------------
# Posiciones
# ----------------------------------------------------------------------------

def positions(machine, sprites: tuple[SpriteDef, ...] = SPRITES) -> dict[str, tuple[int, int]]:
    """Posicion ``(x1, y1)`` de cada sprite segun la RAM actual.

    Si el programa nunca escribio la direccion, se usa el valor de arranque del
    componente (``x1 = 640``), que es lo que hace el VHDL antes de cualquier
    escritura.
    """
    result: dict[str, tuple[int, int]] = {}
    for sprite in sprites:
        if sprite.ax in machine.written_addresses:
            x1 = machine.ram[sprite.ax] & 0xFFFF
        else:
            x1 = sprite.default_x
        if sprite.ay in machine.written_addresses:
            y1 = machine.ram[sprite.ay] & 0xFFFF
        else:
            y1 = sprite.default_y
        result[sprite.name] = (x1, y1)
    return result


# ----------------------------------------------------------------------------
# Rasterizado
# ----------------------------------------------------------------------------

_X = np.arange(SCREEN_W, dtype=np.int64)[None, :]
_Y = np.arange(SCREEN_H, dtype=np.int64)[:, None]


def _layer(image: SpriteImage, x1: int, y1: int) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve ``(mascara, rgb)`` de un sprite en el cuadro completo."""
    definition = image.definition
    addr = (_X + HDIFF - x1) + (_Y - y1) * definition.width

    if definition.has_window:
        inside = (
            (_X >= x1 - HDIFF)
            & (_X < x1 + definition.width - HDIFF)
            & (_Y >= y1)
            & (_Y < y1 + definition.height)
        )
    else:
        # backgroundSM.vhd no comprueba ventana; el rango de la direccion hace
        # de limite.  El VHDL la convierte a 17 bits, asi que se replica el
        # desbordamiento.
        inside = np.ones((SCREEN_H, SCREEN_W), dtype=bool)
        addr = addr % (1 << 17)

    in_range = (addr >= 0) & (addr < image.size)
    index = np.clip(addr, 0, image.size - 1)
    red = image.red[index]
    green = image.green[index]
    blue = image.blue[index]
    # inside_area <= '0' when inter_pixel = "000000000000"
    opaque = (red | green | blue) != 0
    mask = inside & in_range & opaque

    rgb = np.stack(
        [red.astype(np.uint16), green.astype(np.uint16), blue.astype(np.uint16)],
        axis=-1,
    )
    return mask, rgb


def render(
    machine,
    images: dict[str, SpriteImage] | None = None,
    sprites: tuple[SpriteDef, ...] = SPRITES,
    extra_enemies: int = 0,
) -> np.ndarray:
    """Compone el cuadro de 640x480 que se veria en el monitor.

    Devuelve un arreglo ``(480, 640, 3)`` de ``uint8`` (4 bits -> 8 bits
    multiplicando por 17, que es como se conectan los pines de color).

    ``extra_enemies=N`` anade N enemigos de practica en 16+2k/17+2k; con
    ``N = 0`` el resultado es identico al de siempre.
    """
    if images is None:
        images = load_sprite_images()
    order = sprites_with_extras(extra_enemies, sprites)
    pos = positions(machine, order)

    frame = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    # El orden va de menor a mayor prioridad (fondo, municion, enemigos, nave):
    # se pinta en ese orden para que el que gana (la nave) quede encima.
    for definition in order:
        image = _image_for(definition, images)
        if image is None:
            continue
        x1, y1 = pos[definition.name]
        mask, rgb = _layer(image, x1, y1)
        frame[mask] = (rgb[mask] * 17).astype(np.uint8)
    return frame


def describe(
    machine,
    sprites: tuple[SpriteDef, ...] = SPRITES,
    extra_enemies: int = 0,
) -> str:
    """Linea por sprite: posicion, si se ve y cuantos pixeles pinta."""
    images = load_sprite_images()
    order = sprites_with_extras(extra_enemies, sprites)
    pos = positions(machine, order)
    lines = []
    for definition in order:
        image = _image_for(definition, images)
        if image is None:
            continue
        x1, y1 = pos[definition.name]
        mask, _ = _layer(image, x1, y1)
        shown = int(mask.sum())
        # Se informa "fuera de pantalla" solo si la ventana no toca el cuadro.
        if definition.has_window:
            toca = (
                x1 - HDIFF < SCREEN_W
                and x1 + definition.width - HDIFF > 0
                and y1 < SCREEN_H
                and y1 + definition.height > 0
            )
        else:
            toca = True
        if shown:
            state = f"{shown} pixeles"
        elif toca:
            state = "en pantalla, todo transparente"
        else:
            state = "fuera de pantalla"
        lines.append(
            f"{definition.label:15s} x1={x1:5d} y1={y1:5d} "
            f"({definition.width}x{definition.height}) -> {state}"
        )
    return "\n".join(lines)
