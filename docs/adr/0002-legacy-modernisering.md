# ADR 0002: Modernisering av prisberäkningen i Python

- Status: Accepterad
- Datum: 2026-11-24
- Underlag: `docs/work/legacy-codemap.md`, `docs/work/db-migration-plan.md`

## Kontext

`src/legacy/price_calc.py` hade strängformaterad SQL (andra ordningens injektion via rabattkod), oslutna cursors/anslutning, filloggning utan `with` och bar `except`, samt ingen tydlig felkontrakt mot `legacyPrice.ts`. Alla fel blev `not_found` i API:t.

## Beslut

1. **`_kapa` är orörd.** Trunkeringen till 2 decimaler är avstämd med ekonomi (CLAUDE.md) och låst av karakteriseringstester. Icke-normaliserade strängar (`"950"`, `"237.5"`) bevaras tills ekonomi beslutar om svarsformatet.
2. **Parametriserad SQL** och cursors/anslutning stängs säkert.
3. **Separation:** DB-åtkomst (`hamta_order`, `hamta_rabatt_procent`), ren logik (`berakna_pris`) och loggning (`_logga`) är separata funktioner.
4. **CLI-kontrakt** mot `legacyPrice.ts`: exit 0 = pris, 1 = order saknas, 2 = ogiltig indata/internt fel.
5. **Ny felkod `internal` (HTTP 500)** i `Result`/`http.ts` så att modulfel inte maskeras som 404. `GET /orders/:id/price` kan nu svara 500 (se `docs/api.md`). `legacyPrice.ts` har även timeout (10 s).

## Konsekvenser

- Kända brister som INTE åtgärdats och kräver beslut: utgångna rabatter ignoreras, avsaknad av 2-decimalsformat, Python-processen använder egen DB-anslutning utanför `pg.Pool`.
