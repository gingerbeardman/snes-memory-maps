# Visual options

Both SVGs use a 1200×900 view box, matching the SNES display's 4:3 aspect ratio.
They contain no scripts, external fonts, or linked assets.

## Theme

The SVG uses `prefers-color-scheme` and renders appropriately in light and dark
viewers. Text uses system monospace fonts with portable fallbacks.

## Free space

Free or statically unallocated space has a transparent fill by default:

```sh
python3 rommap.py game.map --linker-script game.ld
```

Enable a checkerboard when the distinction from the surrounding background is
useful:

```sh
python3 rommap.py game.map --linker-script game.ld --checkerboard
```

## Colour keys

Colour legends are opt-in:

```sh
python3 rommap.py game.map --linker-script game.ld --colour-key
```

The ROM key explains bank headers, linker-region rectangles, symbol shades, and
free space. The RAM key identifies allocation classes.

## Capacity warnings

Percentage text uses its normal inherited colour unless explicitly enabled:

```sh
python3 rommap.py game.map --linker-script game.ld --coloured-percentages
```

The thresholds are:

| Capacity | Treatment |
|---:|---|
| below 75% | unchanged |
| 75–89.9% | amber |
| 90% or above | red |

The threshold uses the displayed one-decimal percentage.
