# Granskning av PR 214: POST /orders/:id/returns

Granskad gren: `granskning/pr-214-returer` (commit 34631d0). Granskningen gjordes med riggens `code-reviewer`-agent mot `git diff main...HEAD`, säkerhet, struktur och `docs/standard.md`. Ingen kod rättades.

Radnummer kommer från agentens rapport och är inte oberoende kontrollerade.

## Brister min agent hittade

| Typ | Fil och rad | Vad bristen är |
|---|---|---|
| Säkerhet | `src/routes/returns.ts:12` | Kund-id tas från `req.body.customerId` och inte från `req.customerId`. Vem som helst kan returnera någon annans order. |
| Säkerhet | `src/services/returnService.ts:16-19` | Ägarkontroll saknas. `customer_id` hämtas men jämförs aldrig med den inloggade kunden. |
| Säkerhet | `src/services/returnService.ts:3` | Hårdkodad API-nyckel (`FRAKT_API_KEY`). Den ska läsas från miljövariabel och roteras. |
| Säkerhet | `src/services/returnService.ts:32-39` | Nyckeln hamnar i `label_url`, sparas i databasen och returneras till klienten. |
| Säkerhet | `src/services/returnService.ts:21-22` | Kundens e-post loggas med `console.log`, vilket är en personuppgift i loggen. |
| Säkerhet | `src/routes/returns.ts:17` | `(e as Error).message` skickas till klienten och kan läcka interna fel. |
| Säkerhet | `src/services/returnService.ts:34-37`, `db/schema.sql:41-48` | Ingen dubbelreturskontroll. Samma order kan återbetalas flera gånger, och `order_id` saknar UNIQUE och främmande nyckel. |
| Struktur | `src/services/returnService.ts:18` | `throw new Error` i tjänstelagret. Tjänsten ska returnera `err("not_found", …)`. |
| Struktur | `src/routes/returns.ts:9-18` | try/catch med `res.status(500)` i stället för `sendResult`/`sendError`. En saknad order ger 500 och inte 404. |
| Struktur | `src/services/returnService.ts:27-30` | Egen prisberäkning med `* 1.25` utanför `calcPrice`. Rabatt och den avstämda avrundningen i `_kapa` ignoreras. |
| Struktur | `src/services/returnService.ts:34-37` | Skrivningarna sker utan transaktion. |
| Struktur | `returnService.ts`, `returns.ts` | Orderstatus kontrolleras inte, och inget indata valideras (`reason` och `:id` kan vara NaN eller `undefined`, och 400 används aldrig). |
| Kodstandard | `src/services/returnService.ts:6-8, 32, 39` | snake_case (`return_id`, `refund_amount`, `label_url`) i stället för camelCase i typer, JSON och variabler. |
| Kodstandard | `src/services/returnService.ts:8, 27-36` | Pengar hanteras som flyttal (`number`, `parseFloat`). De ska vara `Decimal` och en sträng med 2 decimaler. |
| Kodstandard | `src/routes/returns.ts:17` | Felformatet är `{ message }` och inte `{ error: { code, message } }`. |
| Kodstandard | `tests/returns.test.ts` | Bara lyckat fall testas. 401, 403, 404, 400 och dubbelretur saknas. Testet "sparar returen" kontrollerar ingenting om returraden. `toBeCloseTo` döljer flyttalsfelet. |
| Kodstandard | `docs/api.md`, `docs/adr/` | Felkoderna är inte dokumenterade och `customerId` i body står som krav. Ingen ADR finns, och hela tabellen har formaterats om. |

## Riggens luckor

- Hooken `.claude/hooks/check-standard.mjs` har regler som borde ha fångat `throw` i services (regel 1) och `req.body.customerId` (regel 3). Båda finns ändå i committen, så hooken körs bara när filer skrivs via Claudes Edit- eller Write-verktyg.
- Regeln för pengar (regel 4) gäller bara `pricing/`, inte `services/`.
- Inget kontrollerar hemligheter i kod, e-post i loggar, `res.status(500)` utan `sendError`, snake_case i JSON eller testtäckning för felfall.
- CI och pre-commit-hook saknas (`.husky` och `.github/workflows`), så kontrollerna körs bara i Claude-sessioner.
