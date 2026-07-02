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
