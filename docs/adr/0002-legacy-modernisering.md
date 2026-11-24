# ADR 0002: Modernisering av prisberäkningen i Python

- Status: Accepterad
- Datum: 2026-11-24
- Underlag: `docs/work/legacy-codemap.md`, `docs/work/db-migration-plan.md`, `docs/work/legacy-review.md`

## Kontext

`src/legacy/price_calc.py` hade strängformaterad SQL (andra ordningens injektion via rabattkod), oslutna cursors/anslutning, filloggning utan `with` och bar `except`, samt ingen tydlig felkontrakt mot `legacyPrice.ts`. Alla fel blev `not_found` i API:t.

## Beslut

1. **`_kapa` är orörd.** Trunkeringen till 2 decimaler är avstämd med ekonomi (CLAUDE.md) och låst av karakteriseringstester. Icke-normaliserade strängar (`"950"`, `"237.5"`) bevaras tills ekonomi beslutar om svarsformatet.
2. **Parametriserad SQL** och cursors/anslutning stängs säkert.
3. **Separation:** DB-åtkomst (`hamta_order`, `hamta_rabatt_procent`), ren logik (`berakna_pris`) och loggning (`_logga`) är separata funktioner.
4. **CLI-kontrakt** mot `legacyPrice.ts`: exit 0 = pris, 1 + `{"error":"finns inte"}` = order saknas, 2 = ogiltig indata/internt fel. Python använder också exit 1 vid ohanterade undantag (t.ex. DB nere vid import), därför kräver `legacyPrice.ts` payloaden för `not_found`; allt annat blir `internal`.
5. **Ny felkod `internal` (HTTP 500)** i `Result`/`http.ts` så att modulfel inte maskeras som 404. `GET /orders/:id/price` kan nu svara 500 (se `docs/api.md`). `legacyPrice.ts` har även timeout (10 s). `docs/standard.md` är uppdaterad med 500.

## Konsekvenser

- Kända brister som INTE åtgärdats: DB-anslutningen öppnas vid import (fallback-lösenordet `postgres:postgres` ligger kvar i kod), N+1-frågor och inga tester för `nightly_report.py`, ingen mypy/ruff för Python. Kräver också beslut: utgångna rabatter ignoreras, avsaknad av 2-decimalsformat, Python-processen använder egen DB-anslutning utanför `pg.Pool`.
