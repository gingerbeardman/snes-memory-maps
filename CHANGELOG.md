# Changelog

## Unreleased

- CSV output is now opt-in (`--csv`); SVG is written by default.
- SVG footer now shows the tool's repository URL as its attribution.
- Added `--delimiter` to set the field separator used throughout the SVG
  (headers, tooltips, captions, footer; default: bullet `·`).

## 1.0.0 — 2026-07-02

- Added physical-bank ROM SVG and CSV generation.
- Added address-preserving WRAM SVG and CSV generation.
- Added llvm-mos/ld.lld and vbcc65816/vlink map parsing.
- Added light/dark themes and optional checkerboard, colour keys, and capacity
  warning colours.
