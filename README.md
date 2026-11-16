# Emulador ACF7 / A7 (IIC2343) — práctica sin placa ni monitor VGA

Ensamblador `.suasm` + emulador del computador básico de ACF7 + render de la pantalla
(PNG/GIF) para **practicar y depurar tu programa en ensamblador de A7 en casa**, sin Basys3 y
sin monitor VGA.

> **Antes de usarlo, lee [Qué es y qué no es](#qué-es-y-qué-no-es).** No es oficial, no está
> validado contra la placa y no reemplaza al MinkiAssembler ni a Vivado.

## Contenido

1. [Qué es y qué no es](#qué-es-y-qué-no-es)
2. [Requisitos e instalación](#requisitos-e-instalación)
3. [Inicio rápido](#inicio-rápido)
4. [Escribir tu programa](#escribir-tu-programa)
5. [Referencia de comandos](#referencia-de-comandos)
6. [Entradas: switches y botones](#entradas-switches-y-botones)
7. [Cómo leer la salida y los avisos](#cómo-leer-la-salida-y-los-avisos)
8. [Tiempo: cuánto dura un frame y un tick](#tiempo-cuánto-dura-un-frame-y-un-tick)
9. [Rarezas del hardware que el emulador reproduce](#rarezas-del-hardware-que-el-emulador-reproduce)
10. [Pantalla y sprites](#pantalla-y-sprites)
11. [Enemigos extra](#enemigos-extra)
12. [Errores frecuentes](#errores-frecuentes)
13. [Probar después en la placa](#probar-después-en-la-placa)
14. [Programas de ejemplo, archivos y pruebas](#programas-de-ejemplo-archivos-y-pruebas)
15. [No verificado](#no-verificado)
16. [Uso responsable y origen](#uso-responsable-y-origen)

---

## Qué es y qué no es

**Qué hace**

- Ensambla programas `.suasm` usando la **tabla de opcodes oficial** del paquete MinkiAssembler
  (389 mnemónicos), con las mismas expansiones de palabras de ROM.
- Ejecuta el computador básico de ACF7 **instrucción por instrucción**: registros `A`, `B`,
  `C`, `D`, ALU, banderas, pila, RAM de 4096 palabras, timer y mapa de E/S (switches, botones,
  display, LEDs).
- Simula pulsaciones de switches y botones **programadas en el tiempo** (`--input`).
- Dibuja el cuadro de 640x480 que mostraría el monitor (PNG o GIF), leyendo las posiciones de
  los sprites desde la RAM y aplicando la geometría, la transparencia y la prioridad del VHDL.
- Avisa de errores típicos: salto condicional sin `CMP`, escrituras sobre direcciones de E/S.

**Qué NO hace**

- No emula la señal VGA ni el VHDL, no sintetiza y **no comprueba tu VHDL**. Agregar
  componentes en VHDL se practica solo en Vivado.
- **No está validado contra la placa** (al construirlo no había Vivado ni Basys3). Reproduce lo
  que dice el VHDL del proyecto base según se leyó, no necesariamente lo que hace la placa.
- El ensamblador es una **reimplementación** a partir de la tabla de opcodes, no el
  MinkiAssembler real. Tu código debe ensamblarse al final con el MinkiAssembler del laboratorio.
- No trae la solución de ACF7 ni de A7: los programas de ejemplo son pequeños y propios.

---

## Requisitos e instalación

- **Python 3.10 o superior** (desarrollado con 3.14).
- `asm`, `run`, `trace` y `selftest`: **solo biblioteca estándar**.
- `frame` (PNG/GIF) y las pruebas de gráficos: `numpy` y `Pillow`.
- **Material del curso, que este repositorio NO incluye**: el ZIP del proyecto base
  (`IIC2343_ProyectoBaseACF_7.zip`) y el paquete del ensamblador
  (`MinkiAssemblerPkg-v2.0.2.zip`), ambos descargables desde Canvas.

```bash
git clone <URL-del-repositorio>
cd <carpeta-del-repositorio>

# Opcional: entorno virtual (solo hace falta para `frame`)
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Extrae del material del curso lo que el emulador necesita
python3 preparar_materiales.py RUTA/IIC2343_ProyectoBaseACF_7.zip RUTA/MinkiAssemblerPkg-v2.0.2.zip

# Comprueba que todo funciona
python3 cli.py selftest
python3 -m unittest discover -s tests
```

`preparar_materiales.py` copia, sin modificarlos, `minki_opcodes.json` (junto al emulador) y los
12 `.coe` de los sprites (carpeta `coe/`). Acepta ZIP o carpetas ya extraídas, en cualquier
orden; no pisa archivos distintos salvo que uses `--force`; es seguro repetirlo. Estos archivos
quedan fuera de git (`.gitignore`) porque son material del curso.

**Opcional:** si tienes `base_invaders.txt` (la plantilla `.suasm` del curso), cópiala junto al
emulador o define `BASE_INVADERS=ruta`. Solo la usan unas pocas pruebas del ensamblador; sin ella
se omiten con un aviso y el resto funciona igual.

---

## Inicio rápido

```bash
# Listado de ROM y símbolos (direcciones de tus variables)
python3 cli.py asm programas/01_suma.suasm --limit 4

# Ejecutar 70 ciclos y volcar la RAM en el rango 7..12 (FIN es exclusivo)
python3 cli.py run programas/01_suma.suasm --steps 70 --ram 7 13

# Traza instrucción por instrucción
python3 cli.py trace programas/02_pila.suasm --max 40

# Medir el tiempo (ciclos por frame, tick del timer, vuelta del contador)
python3 cli.py run programas/04_timer.suasm --steps 400000 --timing

# Dibujar el cuadro (necesita numpy y Pillow)
python3 cli.py frame programas/06_sprites.suasm --steps 300 --out nave.png --scale 2

# Animación: 12 frames, 6 muestras
python3 cli.py frame programas/06_sprites.suasm --frames 12 --gif nave.gif --shots 6
```

Resultado esperado de `01_suma`: `total` = 15 (`000F`) en la dirección 12. El PNG de `06_sprites`
muestra la nave abajo, un enemigo arriba y una bala.

---

## Escribir tu programa

Crea un archivo `.suasm` (por ejemplo `mi_programa.suasm`; ese patrón está en `.gitignore` para
que no subas tu trabajo por accidente) y ejecútalo con `run`, `trace` o `frame`.

### Formato

```
// Ejemplo mínimo: cuenta de 1 a 5 y muestra el valor en el display.
DATA:
leds 0
switches 0
displays 0
botones 0
timer_segundos 0
timer_milisegundos 0
timer_microsegundos 0
aux 0
contador 0

CODE:
inicio:
  MOV A, (contador)
  ADD A, 1
  MOV (contador), A
  MOV (displays), A
  CMP A, 5
  JNE inicio
fin:
  JMP fin
```

- `DATA:` declara variables `nombre valor`. **Las direcciones se asignan en orden, desde 0**: la
  primera variable es la dirección 0, la segunda la 1, etc. Cada una genera al arranque dos
  palabras de ROM (`MOV A, valor` + `MOV (dirección), A`), por eso `asm` muestra el prólogo
  antes de `CODE:`.
- `CODE:` contiene las instrucciones. Las etiquetas terminan en `:`.
- Comentarios con `//` o `;`.
- Números en decimal, `0x...`/`...h` (hexadecimal) o `0b...`/`...b` (binario).
- Los registros se escriben en **mayúscula** (`A`, `B`, `C`, `D`). En minúscula son símbolos, así
  que una variable puede llamarse `b`.
- `(nombre)` es el **valor** guardado en esa dirección; `nombre` solo es la **dirección**.

### Qué formas de instrucción existen

La lista autoritativa es la tabla de opcodes. Para verla completa:

```bash
python3 -c "import json; print('\n'.join(sorted(json.load(open('minki_opcodes.json')))))"
```

Si escribes una forma que no existe, el ensamblador te lo dice y lista las válidas de ese
mnemónico. Por ejemplo, **no existe `MOV (dir), Lit`** ni mover de memoria a memoria
(`MOV (a), (b)`): hay que pasar por un registro (`MOV A, 5` y luego `MOV (dir), A`).

### Mapa de memoria

| Dirección | Función | Nota |
|---|---|---|
| 0 | LEDs **y** coordenadas del fondo | escribir los LEDs mueve el fondo |
| 1 | switches (lectura) | al leer devuelve el estado de los switches |
| 2 | display de 7 segmentos (escritura) | |
| 3 | botones (lectura) | al leer devuelve los botones |
| 4 / 5 / 6 | timer: segundos / milisegundos / microsegundos (lectura) | |
| 7 en adelante | libres para tus datos | |
| 10 / 11 | `x` / `y` de la nave | los lee `mainShipSM` |
| 12 / 13 | `x` / `y` del enemigo | los lee `enemyShipSM` |
| 14 / 15 | `x` / `y` de la bala | los lee `ammoSM`; **no los uses para otras variables** |

Las direcciones 1, 3, 4, 5 y 6 devuelven la E/S al leerlas, nunca lo que escribiste ahí. El
`DATA` del template del curso pone la nave en 8/9, pero el VHDL la lee en 10/11: hay que correr
las direcciones (por ejemplo dejando dos variables de relleno en 8 y 9).

---

## Referencia de comandos

```
python3 cli.py <subcomando> PROGRAMA [opciones]
```

| Subcomando | Qué hace |
|---|---|
| `asm` | ensambla y muestra el listado ROM y la tabla de símbolos |
| `run` | ensambla y ejecuta; muestra registros, banderas, RAM y avisos |
| `trace` | traza instrucción por instrucción |
| `frame` | ejecuta y guarda el cuadro 640x480 en PNG (o GIF) |
| `selftest` | autoprueba mínima del entorno |

Las opciones van **después** del subcomando.

| Opción | Subcomandos | Uso |
|---|---|---|
| `--steps N` | `run`, `frame` | ejecutar N ciclos (1 ciclo = 1 instrucción) |
| `--frames N` | `run`, `frame` | ejecutar N frames completos (416 800 ciclos cada uno) |
| `--ram INI FIN` | `run` | volcar el rango de RAM `[INI, FIN)`; acepta `0x...` |
| `--timing` | `run` | informe de ciclos por frame, tick de ms y vuelta del contador |
| `--max N` / `--every N` | `trace` | pasos a ejecutar / imprimir 1 de cada N |
| `--limit N` | `asm` | mostrar solo las primeras N palabras |
| `--out RUTA` | `frame` | PNG de salida (por defecto `frame.png`) |
| `--scale N` | `frame` | ampliar la imagen N veces (vecino más cercano) |
| `--gif RUTA`, `--shots N` | `frame` | animación GIF y cuántos cuadros muestrear |
| `--extra-enemies N` | `frame` | añadir N enemigos de práctica ([ver abajo](#enemigos-extra)) |
| `--switches V` / `--buttons V` | todos | valor inicial de switches (16 bits) y botones (5 bits) |
| `--input CICLO:CAMPO:VALOR` | todos | cambio de entrada programado, repetible |
| `--flags-mode hardware\|sticky` | todos | banderas como el VHDL (`hardware`, por defecto) o variante hipotética |
| `--no-warn` | todos | silenciar el aviso de salto condicional sin `CMP` |
| `--clock HZ` | todos | reloj para los informes de tiempo (por defecto `50e6`) |
| `--opcodes RUTA` | todos | otra tabla de opcodes |

---

## Entradas: switches y botones

- **Switches**: 16 bits; el switch 15 es `0x8000`. Ejemplo: `--switches 0x8000`.
- **Botones**: 5 bits: bit 0 centro (`1`), bit 1 arriba (`2`), bit 2 izquierda (`4`), bit 3
  derecha (`8`), bit 4 abajo (`16`).
- **Cambios programados**: `--input CICLO:CAMPO:VALOR`, con `CAMPO` = `switches` o `buttons`. El
  cambio se aplica al comenzar ese ciclo. Se puede repetir.

```bash
# Nave a la izquierda desde el ciclo 40 y a la derecha desde el 250
python3 cli.py run programas/05_nave.suasm --steps 400 --ram 8 9 \
    --input 40:buttons:4 --input 250:buttons:8

# Subir el switch 15 en el ciclo 100 y soltarlo en el 5000
python3 cli.py run mi_programa.suasm --steps 8000 \
    --input 100:switches:0x8000 --input 5000:switches:0
```

---

## Cómo leer la salida y los avisos

`run` imprime el estado antes y después, el volcado de la RAM y, si los hay, los avisos:

```
ciclos=70 PC=001E SP=FFF A=000F B=000C C=0000 D=0000 C=0 Z=1 N=0 timer=000.000.000
--- RAM 0007..000D ---
0007: 0001 0002 0003 0004 0005 000F
```

- `PC`: posición en la ROM. `SP`: puntero de pila (arranca en `FFF`). `C Z N`: banderas.
- `timer=SSS.MMM.UUU`: segundos, milisegundos y microsegundos simulados.
- `trace` añade, por instrucción, `[dir]<=valor` cuando escribe en RAM.

**Avisos** (con `--no-warn` se silencian los de salto):

```
PC=0003: salto condicional tras 'JMP Lit' (no CMP); banderas recicladas, 14 vez/veces
```

Significa que un `JEQ`/`JNE`/... se ejecutó sin un `CMP` justo antes y por eso usó banderas que
dejó otra instrucción (ver [rarezas](#rarezas-del-hardware-que-el-emulador-reproduce)). También
avisa si el programa **escribe** en una dirección cuya lectura devuelve E/S.

---

## Tiempo: cuánto dura un frame y un tick

Un frame de VGA son 800x521 = **416 800 ciclos**, y un tick de `timer_milisegundos` son
**100 000 ciclos**: un frame equivale a unos **4,2 ticks de `ms`**, sin importar el reloj
(siempre que la CPU y la pantalla compartan el reloj reducido, como en el proyecto base).

| Reloj | Frame | Tick de `ms` | `ms` envuelve cada |
|---|---|---|---|
| 50 MHz (supuesto por defecto) | 8,34 ms (120 Hz) | 2 ms | 2 s |
| 25 MHz | 16,7 ms (60 Hz) | 4 ms | 4 s |

El VHDL usa `speed="00"` en el divisor de reloj, pero los comentarios y `Xelor` suponen 25 MHz;
**no está verificado** cuál es el real. Mídelo en la placa (por ejemplo mostrando `timer_segundos`
en el display y cronometrando) y usa `--clock 25e6` para ver los informes con ese valor.

Consecuencias prácticas:

- Un lazo de unas decenas de instrucciones sin ningún freno se ejecuta **miles de veces por
  frame**: un sprite que se mueva 1 píxel por pasada cruza la pantalla en microsegundos y en el
  monitor solo se ve parpadear o desaparecer.
- Comparar el timer por igualdad exacta (`CMP A, 100` + `JEQ`) es frágil: `ms` solo vale 100 una
  vez por vuelta (cada ~2 s) y, mientras vale 100, el lazo vuelve a pasar miles de veces. Conviene
  detectar **que cambió** el valor, o comparar contra una referencia capturada.
- El emulador renderiza una foto consistente de la RAM; en la placa la CPU escribe mientras el
  barrido avanza, así que además se ven parpadeos a media pantalla.

---

## Rarezas del hardware que el emulador reproduce

Salen de leer el VHDL del proyecto base (más detalle y fuentes en [`DISENO.md`](DISENO.md)). Son
las que más afectan a un programa de A7:

1. **Cualquier salto, `NOP` o `CALL` deja `C=0, Z=1, N=0`.** El registro de estado se carga en
   todos los flancos de reloj y esas instrucciones ejecutan una operación de la ALU con
   operando 0. `MOV` también pisa las banderas. Un condicional que no sigue a un `CMP` usa
   banderas basura; el emulador lo avisa.
2. **`N` solo significa algo después de `SUB`** (`N = not carry`), así que
   `JLT`/`JLE`/`JGT`/`JGE` solo tienen sentido tras un `CMP`.
3. **No existe `MOV (dir), Lit`** ni movimiento memoria-memoria: pasa por un registro.
4. **Las direcciones 1, 3, 4, 5 y 6 están tapadas por la E/S al leer.** Tus datos van desde la 7.
5. **La dirección 0 es a la vez LEDs y coordenadas del fondo**: escribir los LEDs mueve el fondo.
6. **Un tick de `timer_milisegundos` son 100 000 ciclos** (ver [Tiempo](#tiempo-cuánto-dura-un-frame-y-un-tick)).
7. **`RET` y `POP` ocupan dos palabras de ROM**: las etiquetas siguientes se corren.
8. **`x1 = 640` no oculta un sprite.** La ventana horizontal parte en `x1 - 2`, así que quedan
   visibles las columnas 638 y 639. Para ocultarlo de verdad, escribe `x >= 642` (por ejemplo 700)
   o `y >= 480`.
9. **El fondo no comprueba ventana y su cuenta se trunca a 17 bits.** Es una imagen de 300x300
   leída sobre 640 columnas: se ve torcida, hay una franja negra desde `y = 300` y desde
   `y = 435` el truncamiento repite el tope. Es lo que hace el VHDL entregado.
10. **La pila arranca en `FFF`** (12 bits útiles) y `INC SP`/`DEC SP` no existen como
    instrucciones; usa `PUSH`/`POP`/`CALL`/`RET`.
11. **Las naves traen un fondo celeste `(4,15,14)` que no es transparente.** Solo el negro
    `000000` se descarta, así que según los archivos entregados cada nave debería verse dentro
    de un rectángulo celeste; el emulador lo dibuja así. **No verificado en la placa**: confirmar
    en el laboratorio (ver [`DISENO.md`](DISENO.md) §11).

---

## Pantalla y sprites

| Componente | Tamaño | `Ax1` / `Ay1` | Ventana en pantalla |
|---|---|---|---|
| `backgroundSM` (fondo) | 300x300 | 0 / 0 | sin prueba de caja (ver rareza 9) |
| `mainShipSM` (nave) | 69x90 | 10 / 11 | `x1-2 .. x1+66`, `y1 .. y1+89` |
| `enemyShipSM` (enemigo) | 30x30 | 12 / 13 | `x1-2 .. x1+27`, `y1 .. y1+29` |
| `ammoSM` (bala) | 10x10 | 14 / 15 | `x1-2 .. x1+7`, `y1 .. y1+9` |

- **Prioridad fija: nave > enemigo > bala > fondo.** Un píxel `000000` es transparente (se ve la
  capa siguiente); cualquier otro color tapa.
- Los colores son de 4 bits por canal y se muestran multiplicados por 17.
- Antes de que el programa escriba una posición, el sprite está en `x1 = 640`, `y1 = 0` (deja una
  franja de 2 columnas a la derecha, ver rareza 8).

---

## Enemigos extra

La base trae **un** solo `enemyShipSM`. Para practicar el caso de 10 aliens existe
`frame --extra-enemies N` (y `render(..., extra_enemies=N)`): añade N enemigos de 30x30 con la
imagen `nave_azul`. El enemigo extra `k` escucha `x` en `16+2k` e `y` en `17+2k` (0 ≤ k < N),
con la misma transparencia y `hDiff = 2`, y la misma prioridad que el enemigo base (debajo de la
nave, encima de la bala; entre extras gana el de mayor índice). Con `N = 0` el cuadro es idéntico.

```bash
python3 cli.py frame mi_programa.suasm --steps 400000 --extra-enemies 9 --out mapa.png --scale 2
```

**Es una suposición del emulador.** La base evaluada de A7 puede traer ya las instancias o usar
otras direcciones; si es así, ajusta `EXTRA_ENEMY_AX` en `gpu.py`. Y al revés: si tu programa
escribe en 16/17, 18/19... para otras variables, aparecerá un enemigo extra ahí; deja libres esos
pares. El emulador **no** comprueba que tu VHDL tenga esas instancias.

---

## Errores frecuentes

| Síntoma | Causa probable |
|---|---|
| `no se pudo leer la tabla de opcodes` / `falta ...coe` | falta el material del curso: ejecuta `preparar_materiales.py` |
| `no existe la forma 'MOV (dir), (dir)'` | esa forma no existe en la tabla: pasa por un registro |
| El sprite se mueve «demasiado rápido» o desaparece | el lazo no tiene freno de tiempo (ver [Tiempo](#tiempo-cuánto-dura-un-frame-y-un-tick)) |
| Un `JEQ` se toma siempre | no hay un `CMP` justo antes; otro salto o un `MOV` pisó las banderas |
| `A = 1 - x` en vez de `x - 1` | en `SUB D, C` el resultado es `D - C`: carga primero la posición en `D` y resta el literal |
| Un sprite aparece en un lugar raro | tus variables chocan con direcciones de sprites (10 a 15, o 16+ con extras) |
| `ModuleNotFoundError: numpy` / `PIL` | `pip install -r requirements.txt` (solo `frame` y tests de gráficos) |

---

## Probar después en la placa

El emulador sirve para razonar sobre tu programa; **la verdad la dicen el MinkiAssembler real y
la placa**. Flujo recomendado:

1. Escribe y depura aquí (`asm`, `run`, `trace`, `frame`).
2. Ensambla el mismo `.suasm` con el MinkiAssembler del laboratorio y **anota las formas que
   rechaza** (si acepta algo que aquí falla, o al revés, hay una diferencia que conviene reportar).
3. Reprograma la placa con el bitstream de tu VHDL y sube el programa.
4. Compara lo que ves con lo que mostró el emulador. Mide el tick real del timer.

---

## Programas de ejemplo, archivos y pruebas

Los programas de `programas/` son **propios y mínimos; no son el juego de la actividad**.

| Archivo | Qué muestra | Resultado esperado |
|---|---|---|
| `01_suma.suasm` | puntero en registro, `CMP`/`JEQ`, mapa de memoria | `total` = 15 en la dirección 12 y en el display |
| `02_pila.suasm` | `CALL` anidados, orden LIFO, `SP` | `marca_a`=3, `marca_b`=1, `orden`=2, `SP`=FFF |
| `03_banderas.suasm` | la rareza de banderas | `marca`=1 con `hardware`, 0 con `sticky` |
| `04_timer.suasm` | leer el timer y detectar cambios | `cambios` ≈ 3 en 400 000 ciclos |
| `05_nave.suasm` | botones, `AND` de máscara, topes de pantalla | `nave_x` baja y sube de 2 en 2 y se detiene en 2 |
| `06_sprites.suasm` | nave, enemigo y bala en sus direcciones reales, con movimiento amarrado al timer | se ven en el PNG/GIF |

| Archivo | Contenido |
|---|---|
| `cli.py` | línea de comandos: `asm`, `run`, `trace`, `frame`, `selftest` |
| `suasm.py` | ensamblador: `DATA:`/`CODE:`, etiquetas, literales, prólogo de `DATA` |
| `cpu.py` | máquina instrucción por instrucción, con avisos |
| `gpu.py` | rasterizador: carga los `.coe`, ventanas, transparencia, prioridad |
| `preparar_materiales.py` | extrae del material del curso la tabla de opcodes y los `.coe` |
| `programas/` | programas de ejemplo |
| `tests/` | pruebas de ensamblador, máquina y gráficos |
| `DISENO.md` | especificación, hechos extraídos del VHDL y registro de decisiones |
| `minki_opcodes.json`, `coe/` | **no incluidos**: los crea `preparar_materiales.py` |
| `base_invaders.txt` | **no incluido** (opcional): plantilla del curso; solo la usan unas pruebas |

```bash
python3 -m unittest discover -s tests          # 131 pruebas (128 + 2 omitidas sin base_invaders.txt)
python3 -m unittest tests.test_cpu -v          # un archivo
```

---

## No verificado

- Que el MinkiAssembler real produzca exactamente el mismo prólogo de `DATA` (dos palabras por
  valor) y acepte/rechace las mismas formas: no se pudo ejecutar su `.exe` de Windows.
- Que el reloj reducido sea de 50 MHz (se asume por el `speed="00"` del VHDL; los comentarios
  dicen 25 MHz). Cambia los informes con `--clock`.
- Que la BRAM de sprites devuelva negro fuera de rango (así se generaron los `.coe`).
- El *tearing* real y cualquier comparación pixel a pixel con la placa.
- La rareza 11 (fondo celeste de las naves) y, en general, todo lo que dependa de cómo se ve la
  placa. Si ves algo distinto en el laboratorio, es información valiosa: anota el programa, lo
  que viste y lo que mostró el emulador.

---

## Uso responsable y origen

- Es una **herramienta de práctica en casa**. Las evaluaciones tienen sus propias reglas sobre
  qué herramientas se pueden usar (normalmente solo las del laboratorio): **no la uses en una
  evaluación** salvo que el enunciado lo permita expresamente.
- No contiene soluciones de ACF7 ni de A7, y **no debes publicar tus soluciones** aquí.
- El material del curso (tabla de opcodes, imágenes de sprites, proyecto base) pertenece al
  curso y no se redistribuye en este repositorio.
- Fue construido con **asistentes de IA** (OpenCode y Claude Code) leyendo el VHDL del proyecto
  base, y revisado con pruebas automáticas. No es oficial ni está respaldado por el curso.
