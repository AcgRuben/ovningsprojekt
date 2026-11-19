# Plan: Kunden kan avbryta en beställning inom 30 minuter

Status: Godkänd. Gränstester använder 29 min 59 s (200) och 30 min 1 s (409).
Underlag: `docs/work/01-research.md`. Beslut: `docs/adr/0001-avbryta-bestallning.md`.

## Beslut (från användaren)

1. Endpoint: `POST /orders/:id/cancel`.
2. Endast status `new` får avbrytas. Alla andra ger 409 `conflict`.
3. Gräns inklusive (`<= 30 minuter`), konstanten `CANCEL_WINDOW_MINUTES = 30`.
4. Redan `cancelled` ger 409 `conflict` med tydligt meddelande.
5. Tidskälla: databasens `now()` i SQL i samma transaktion.
6. Inget nytt schema och ingen migrering (`status = 'cancelled'`). `createdAt` läggs till på `Order` i API-svaret.

## API-kontrakt

### `POST /orders/:id/cancel`

- Headers: `X-Customer-Id: <heltal > 0>` (krävs). Ingen body.
- Path: `:id` är ett heltal > 0.

**200 OK** – ordern efter avbokning (samma form som `GET /orders/:id`, nu med `createdAt`):

```json
{
  "id": 1043,
  "customerId": 7,
  "status": "cancelled",
  "discountCode": null,
  "createdAt": "2026-11-19T10:15:00.000Z",
  "lines": [{ "product": "Kaffe", "quantity": 2, "unitPrice": "49.00" }]
}
```

**Felsvar** – alltid `{ "error": { "code": "...", "message": "..." } }`:

| Status | `code` | När | Meddelande (förslag) |
|---|---|---|---|
| 400 | `invalid_input` | `:id` är inte ett heltal > 0 | "Ogiltigt order-id." |
| 401 | `unauthorized` | `X-Customer-Id` saknas/ogiltig | (befintligt från `requireCustomer`) |
| 403 | `forbidden` | Ordern tillhör en annan kund | "Beställningen tillhör en annan kund." |
| 404 | `not_found` | Ordern finns inte | "Beställning {id} finns inte." |
| 409 | `conflict` | Redan avbruten | "Beställningen är redan avbruten." |
| 409 | `conflict` | Status är inte `new` (t.ex. `paid`, `shipped`) | "Beställningen kan inte avbrytas i status {status}." |
| 409 | `conflict` | Mer än 30 minuter sedan beställningen lades | "Tiden för att avbryta beställningen (30 minuter) har gått ut." |

### Ändring av befintligt svar

`Order` (och därmed `GET /orders/:id`, `POST /orders` och avbokningssvaret) får fältet `createdAt` (ISO 8601-sträng, från `orders.created_at`). Övriga fält är oförändrade.

### Ordning på kontroller

id-validering (400) → auth (401) → finns (404) → ägare (403) → redan avbruten (409) → status ≠ `new` (409) → tidsgräns (409). 403 kommer före alla 409 så att ingen information om andras ordrar läcker.

## Acceptanskriterier (Givet/När/Så)

**AK1 – Lyckad avbokning**
Givet en egen order med status `new` som lades för 10 minuter sedan, när kunden anropar `POST /orders/:id/cancel`, så svarar API:t 200 med `status: "cancelled"` och `createdAt` satt, och databasen har status `cancelled`.

**AK2 – Gräns inklusive**
Givet en egen `new`-order som är 29 minuter gammal, när kunden avbryter, så svarar API:t 200.
Givet en egen `new`-order som är exakt 30 minuter gammal (`created_at = now() - 30 minuter` vid anropet), när kunden avbryter, så svarar API:t 200.
(Testet sätter `created_at` strax innanför gränsen för att inte bli flaky mot transaktionens `now()`, se risker.)

**AK3 – För sent**
Givet en egen `new`-order som är 31 minuter gammal, när kunden avbryter, så svarar API:t 409 `conflict` med meddelandet om utgången tid, och ordern är oförändrad (status `new`).

**AK4 – Fel status**
Givet en egen order med status `paid` eller `shipped` som lades för 10 minuter sedan, när kunden avbryter, så svarar API:t 409 `conflict` ("kan inte avbrytas i status …") och ordern är oförändrad.

**AK5 – Redan avbruten**
Givet en egen order med status `cancelled`, när kunden avbryter, så svarar API:t 409 `conflict` med meddelandet "redan avbruten" och ordern är oförändrad.

**AK6 – Dubbel avbokning**
Givet en egen, giltig `new`-order, när kunden anropar avbryt två gånger i följd, så svarar första anropet 200 och andra 409 (redan avbruten).

**AK7 – Samtidighet**
Givet en egen, giltig `new`-order, när två avbryt-anrop skickas samtidigt, så svarar exakt ett 200 och det andra 409, och ordern har status `cancelled`.

**AK8 – Annan kunds order**
Givet en order som tillhör en annan kund, när kunden avbryter, så svarar API:t 403 `forbidden` och ordern är oförändrad. Detta gäller även om ordern är för gammal eller har fel status (403 går före 409).

**AK9 – Order saknas**
Givet ett order-id som inte finns, när kunden avbryter, så svarar API:t 404 `not_found`.

**AK10 – Ogiltigt id**
Givet ett ogiltigt id (`abc`, `0`, `-1`, `1.5`), när kunden avbryter, så svarar API:t 400 `invalid_input`.

**AK11 – Utan inloggning**
Givet att `X-Customer-Id` saknas, när anropet görs, så svarar API:t 401.

**AK12 – Synlighet efter avbokning**
Givet att en avbokning lyckats, när kunden hämtar `GET /orders/:id` och `GET /customers/me/orders`, så visas status `cancelled`, och `GET /orders/:id` innehåller `createdAt`.

**AK13 – `createdAt` på Order**
Givet en befintlig order, när kunden hämtar `GET /orders/:id` eller skapar en order via `POST /orders`, så innehåller svaret `createdAt` som ISO 8601-sträng och övriga fält är oförändrade.

## Implementationsplan (efter godkännande)

Följer `/tdd` (Red → Green → Refactor), en liten commit per steg.

1. **Testhjälpare** i `tests/helpers/`: `setOrderAge(orderId, minutes)` (parametriserad `UPDATE orders SET created_at = now() - make_interval(mins => $2) WHERE id = $1`) och en hjälpare för att sätta status. Inga nya seed-rader krävs.
2. **Red:** Tester för AK1–AK13 i `tests/orders.test.ts` (eller ny `tests/cancelOrder.test.ts`). Befintliga tester tas inte bort eller skippas.
3. **Green, typ och SQL:** Lägg till `createdAt` på `Order` och hämta `created_at AS "createdAt"` i `getOrder`. Inför `OrderStatus`-typ/konstanter och `CANCEL_WINDOW_MINUTES = 30`.
4. **Green, service:** `cancelOrder(orderId, customerId): Promise<Result<Order>>` i `src/services/orderService.ts`: `BEGIN`, `SELECT ... FOR UPDATE` med `withinWindow` beräknad i SQL, kontroller i fastställd ordning, `UPDATE ... WHERE id = $1 AND status = 'new'`, `COMMIT`, returnera `getOrder`. Ingen `throw` för förväntade fall. `ROLLBACK` vid oväntade fel.
5. **Green, route:** `orders.post("/orders/:id/cancel", requireCustomer, ...)` med befintlig `parseId` och `sendResult`.
6. **Refactor:** Städa upp och samla gemensam logik. Kör lint och typecheck.
7. **Dokumentation:** Uppdatera `docs/api.md` (ny rad för `POST /orders/:id/cancel` med 200/400/401/403/404/409, samt notering om `createdAt` på order). ADR:en sätts till "Accepterad".
8. **Granskning** (`code-reviewer` → `docs/work/03-review.md`), **verifiering** (`npm test && npm run lint && npm run typecheck`) och **sessionslogg** (`session-scribe`).

## Berörda filer

- `src/routes/orders.ts` (ny route)
- `src/services/orderService.ts` (`cancelOrder`, `createdAt`, `OrderStatus`)
- `tests/orders.test.ts` eller `tests/cancelOrder.test.ts`, `tests/helpers/` (ny hjälpare)
- `docs/api.md`, `docs/adr/0001-avbryta-bestallning.md`
- Ingen ändring i `db/schema.sql`, `src/legacy/price_calc.py` eller `jobs/nightly_report.py`.

## Risker och noteringar

- **Gränstest vid exakt 30 minuter:** `now()` är transaktionens starttid och tiden går mellan testets `UPDATE` och anropet. Ett test med `created_at = now() - 30 min` exakt kan därför falla utanför gränsen. Testet sätter åldern strax innanför (t.ex. 29 min 59 s) och 30 min + 1 s för "precis utanför". Detta behöver bekräftas av dig, eftersom det betyder att "exakt 30:00" inte testas bokstavligt.
- **Svarsändring:** `createdAt` på `Order` är en additiv ändring. Befintliga tester använder inte `toEqual` på hela objektet enligt research.
- **Inget `cancelled_at`:** Ingen spårbarhet över när avbokningen skedde (se ADR).
- **Lager och betalning:** Finns inte. Ingen återlagring eller återbetalning ingår.
- **Avbrutna ordrar och `GET /orders/:id/price`:** Prisberäkning fungerar som tidigare.
- **Radslut:** `git status` visar många `src/`- och `tests/`-filer som modifierade, men det är enbart LF/CRLF-varningar (`diff` är tom när radslut ignoreras). Ingen innehållsändring.

## Godkännande

Inget skrivs i `tests/` eller `src/` förrän du godkänner planen och ADR:en. Därefter fortsätter vi med Fas 3 (`/tdd`).
