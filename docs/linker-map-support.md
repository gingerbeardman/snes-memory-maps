# Linker map support

## llvm-mos/ld.lld

`rommap.py` expects:

- an ld.lld map containing VMA, LMA, size, alignment, input-section, and symbol
  rows;
- a linker script containing a GNU-style `MEMORY { ... }` block;
- ROM regions at CPU addresses `$xx:8000` or above.

Input sections named `.text.*`, `.rodata.*`, and `.data.*` become ROM
allocations. Named bank containers such as `.text.bank3` are expanded using
their nested symbols so the container and its contents are not counted twice.

`rammap.py` accepts any allocated input section whose VMA falls in one of these
ranges:

| Range | Capacity |
|---|---:|
| `$7E:0000–00FF` | 256 B |
| `$7E:0100–1FFF` | 7.75 KiB |
| `$7E:2000–FFFF` | 56 KiB |
| `$7F:0000–FFFF` | 64 KiB |

Low WRAM may be expressed as a 16-bit address (`$0200`) or as a native bank
`$7E` address (`$7E:0200`).

No linker script is required for the RAM map.

Section-name prefixes classify RAM as `.data`, `.bss`, or `.noinit`. Unknown
section names remain visible as `allocated`.

## vbcc65816/vlink

The scripts recognise the `Section mapping (numbers in hex):` table emitted by
vlink. Common text, read-only data, initialized data, and BSS section names are
reduced to their symbol names where possible.

For vlink RAM entries, allocation type is reported as `allocated` because the
section mapping does not always retain enough portable information to
distinguish initialization policy.

## cc65 (ca65/ld65)

Produce a map with `ld65 --mapfile` (or `cl65 --mapfile`):

```sh
cl65 -t none -C mygame.cfg -o mygame.bin --mapfile mygame.map  main.s ...
#   or, if you invoke the linker directly:
ld65 -C mygame.cfg -o mygame.bin -m mygame.map  main.o ...

rommap.py mygame.map --linker-script mygame.cfg
```

The `--linker-script` is your ordinary cc65 **linker config** — the same `.cfg`
you already pass to `cl65`/`ld65` with `-C`. It is **optional**: with it, ROM
regions are named after its `MEMORY {}` areas; without it (or for `rammap.py`),
the map falls back to LoROM physical banks. Either way sizes stay exact.

Leaves are **segments**, read from the map's `Segment list:` table (`Name`,
`Start`, `End`, `Size`, `Align`). Sizes and free space are therefore exact, at
segment granularity — per-symbol sizes are not present in an ld65 map. RAM
segments are classified by name: `*BSS*`/`*ZP*` → `bss`, `*DATA*` → `data`,
otherwise `allocated`.

## wla-dx and asar (symbol files)

Point the tool at the symbol file each emits:

```sh
# wla-dx: wlalink writes a WLA `.sym` ([labels]) next to the linked ROM
wlalink -S -A linkfile.link mygame.sfc       # -> mygame.sym
rommap.py mygame.sym

# asar: choose the WLA or no$sns symbol format
asar --symbols=wla   --symbols-path=mygame.sym  mygame.asm mygame.sfc
asar --symbols=nocash --symbols-path=mygame.sym mygame.asm mygame.sfc
rommap.py mygame.sym
```

No `--linker-script` is used. `.sym` files list labels and their addresses
only — no sizes and no memory layout. The tool therefore:

- assumes a LoROM physical-bank layout (bank `$xx`, offset `$8000–$FFFF`);
- infers each label's size as the gap to the next label, sorted per bank;
- extends the last label in a bank to the bank end.

Consequently **sizes are approximate**: trailing free space inside a bank is
absorbed by that bank's final label, unlabeled data between labels is attributed
to the preceding label, and the footer marks the map `(approx sizes)`. RAM
labels are reported as `allocated`. For exact sizes, use a linker map (ld.lld,
vlink, or ld65) instead.

## ROM layout assumptions

The current visualisation targets a sixteen-bank, 512 KiB physical ROM with
32 KiB bank windows. This matches the project's LoROM layout.

For the `rom_bank_fixed`/`code_bank_*` convention, fixed-region bytes are copied
into every code bank in the physical view. CSV rows remain linker allocations
and therefore list the fixed region only once.

HiROM vlink addresses are projected into sequential 32 KiB physical chunks for
display. This is a visualisation convention, not a replacement for a full SNES
bus-address decoder.

## Static data only

Linker maps describe static placement. They cannot show:

- runtime stack high-water marks;
- heap allocation;
- decompressed or streamed buffers sharing an address range over time;
- overlays not represented as distinct linker inputs.

Treat transparent/free RAM as statically unallocated, not guaranteed unused.
