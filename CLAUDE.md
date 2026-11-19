# Projektinstruktioner – Butikens API

## Arkitektur & Kodbas

- **REST-API (`src/`)**: TypeScript, Express, PostgreSQL.
  - `src/routes/`: HTTP-lager. Hämtar kund via `requireCustomer` (`req.customerId`). Svarar via `sendResult`/`sendError`.
  - `src/services/`: Affärslogik. Kastar INTE fel – returnerar `Result` (`ok(val)` / `err(code, message)` från `src/result.ts`).
  - `src/pricing/`: All prisberäkning går via `calcPrice`.
- **Legacy (`src/legacy/price_calc.py`)**: Python-modul som anropas av `src/pricing/legacyPrice.ts` och `jobs/nightly_report.py`. OBS: Avrundningen i `_kapa` (trunkering till 2 decimaler) är avstämd med ekonomi och får INTE ändras utan explicit beslut.

## Kodstandard (`docs/standard.md`)

- camelCase för variabler/funktioner/JSON-fält, PascalCase för typer.
- All SQL parametriserad: `db.query(sql, [värden])`. Aldrig strängmallar i SQL.
- Belopp hanteras med `Decimal` / `NUMERIC` och strängar med 2 decimaler – aldrig flyttal (`float`/`number`).
- Inga hemligheter i kod och inga personuppgifter (namn, e-post) i loggar.

## Arbetsregler

- All styrning ligger i repot. Dokumentera arkitekturbeslut i `docs/adr/`.
- Håll `docs/api.md` uppdaterad vid ändrade endpoints.
- Ta ALDRIG bort tester eller använd `.skip` / `.only`.
- Följ flödet: Research -> Plan (fil) -> TDD (Red-Green-Refactor) -> Granskning -> Verifiering -> Sessionslogg.
