# Granskning av moderniseringen (code-reviewer)

Omfång: commits 403e623..1a05dd2, `docs/work/db-migration-plan.md`, ADR 0002. Åtgärder gjorda i uppföljande commit.

| # | Allvar | Fynd | Åtgärd |
|---|---|---|---|
| 1 | Hög | Pythons exit 1 vid krasch (t.ex. DB nere vid import) tolkades som 404 | `legacyPrice.ts` kräver payload `{"error":"finns inte"}` för `not_found`, annars `internal` |
| 2 | Hög | TS-sidan av kontraktet otestad | Ny `tests/legacyPrice.test.ts` (6 fall, mockad `execFile`) |
| 3 | Medel | Planen: backup täckte inte ändrade rader, fel om NOT VALID, B3 saknade markering, B1 backbar bara före B2, FK-fel kastas av `pg` | Planen rättad (`source`-kolumn, backup av originalvärden, SQLSTATE 23503/23514 → `invalid_input`) |
| 4 | Medel | B2 skriver per läsning; B6 kräver ändring av låsta tester | Idempotens och explicit beslut tillagda i planen |
| 5 | Medel | ADR refererade ospårad fil, standard.md saknade 500 | Planen committad, `docs/standard.md` uppdaterad, ADR förtydligad |
| 6 | Medel | `nightly_report.py`: ingen felhantering/test, N+1 | Ej åtgärdat, listat som känd brist i ADR |
| 7 | Medel/låg | Orsak till 500 försvinner; anslutning stängs ej vid ogiltigt id | Klassnamn till stderr, `conn.close()` före exit 2 |
| 8 | Låg | Hårdkodat fallback-lösenord, `PYTHON_BIN` default `python3` på Windows | Ej åtgärdat, dokumenterat (fanns före ändringen) |
| 9 | Låg | `exec`-baserade CLI-tester sköra, ingen mypy/ruff | Ej åtgärdat; `price_calc.log` är gitignorerad (verifierat) |
