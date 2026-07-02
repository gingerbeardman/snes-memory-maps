# Contributing

Contributions are welcome, especially anonymised linker-map fixtures from
additional SNES toolchains.

## Before submitting

1. Keep runtime dependencies within the Python standard library.
2. Preserve Python 3.9 compatibility.
3. Add or update a fixture when changing a linker-map parser.
4. Run:

   ```sh
   python3 -m unittest discover -s tests -v
   ```

5. Regenerate examples when visual output intentionally changes:

   ```sh
   ./rommap.py tests/fixtures/game.map \
     --linker-script tests/fixtures/game.ld \
     -o examples/rommap

   ./rammap.py tests/fixtures/game.map \
     --linker-script tests/fixtures/game.ld \
     -o examples/rammap
   ```

Please do not commit proprietary linker maps. Reduce new fixtures to the
smallest synthetic example that demonstrates the format or bug.
