# Super Draft 26/27

Liga-site for FPL Draft-ligaen 780: tabeller, bundpokal, held og uheld, runde-log og rekorder.

## Sådan virker det

- `scripts/build_data.py` henter data fra det offentlige Draft-API og skriver JSON-filer til `docs/data/`.
- GitHub Actions (`.github/workflows/update.yml`) kører scriptet hver tredje time og committer kun, hvis noget har ændret sig. Brug "Run workflow" under Actions for at opdatere med det samme.
- GitHub Pages serverer `docs/`.

## Data

| Fil | Indhold |
|---|---|
| `docs/data/config.json` | Bundpokalens blokke, præmie, hvornår en runde fryses. Rettes i hånden. |
| `docs/data/gameweeks/gwNN.json` | Én fil per færdigspillet runde. Fryses (`"final": true`) 72 timer efter rundens sidste kamp og bliver derefter aldrig ændret af scriptet. |
| `docs/data/blocks.json` | Bundpokalens historik. En blok fryses, når alle dens runder er frosne. |
| `docs/data/current.json` | Alt, siden viser lige nu. Genberegnes ved hver kørsel. |

Skal et frosset resultat rettes, så ret filen i hånden og commit. Historikken i git viser hvem og hvornår.

## Lokalt

```bash
python scripts/build_data.py
python -m http.server 8765 --directory docs
```
