# Research: Avbryta en beställning inom 30 minuter

User story (nr 2 i `docs/user-stories.md`): "Som kund vill jag kunna avbryta en beställning inom 30 minuter efter att jag lagt den."

Ingen källkod har ändrats. Analysen bygger på `db/schema.sql`, `db/seed.sql`, `docs/api.md`, `docs/standard.md`, `src/` och `tests/`.

## 1. Nuläge

### Databas (`db/schema.sql`)
- `orders`: `id SERIAL PK`, `customer_id INTEGER NOT NULL` (ingen FK), `status TEXT NOT NULL DEFAULT 'new'` (ingen CHECK/enum), `discount_code TEXT`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
- `order_lines`: `order_id INTEGER NOT NULL` (ingen FK, ingen ON DELETE), `product`, `quantity`, `unit_price NUMERIC(10,2)`.
- Det finns ingen kolumn `cancelled_at` och inget `updated_at`.
- `created_at` är `TIMESTAMPTZ`, alltså tidszonsmedvetet. Tidszon är inget problem om jämförelsen görs i databasen eller med absoluta tidpunkter. Seed-data anger `+02`.
- Ingen lagerkolumn eller lagertabell finns (user story 6 är inte byggd).

### Orderstatusar som förekommer
- Seed: `new`, `paid`, `shipped`, `cancelled`. Order 1046 är redan `cancelled`, så statusen finns redan som värde.
- `createOrder` sätter ingen status explicit (använder default `new`).
- Det finns ingen kod som ändrar status idag, så ingen betalnings- eller leveransflöde finns i API:t. `paid` och `shipped` finns bara i seed.
- `jobs/nightly_report.py` filtrerar på `status = 'paid'` (och bygger SQL med strängformatering, vilket bryter mot standarden, men ligger utanför denna story). Att en avbruten order får status `cancelled` påverkar alltså inte rapporten, men en order som hunnit bli `paid` och sedan avbryts försvinner ur rapporten för det datumet.
- `src/legacy/price_calc.py` och `legacyPrice.ts` nämner inte status (grep). `GET /orders/:id/price` räknar alltså pris även för avbrutna ordrar. Beslut behövs om det ska vara tillåtet (förslag: ja, oförändrat beteende).

### Endpoints (`docs/api.md`, `src/routes/`)
| Endpoint | Fil |
|---|---|
| `GET /health` | `src/app.ts` |
| `POST /customers`, `GET /customers/me`, `GET /customers/me/orders` | `src/routes/customers.ts` |
| `POST /orders`, `GET /orders/:id`, `GET /orders/:id/price` | `src/routes/orders.ts` |

Ingen endpoint för avbokning finns. `app.ts` monterar `customers` och `orders` som routers utan prefix.

### Felformat och statuskoder
- Alla felsvar: `{ "error": { "code": "...", "message": "..." } }`.
- `ErrorCode` i `src/result.ts`: `not_found`, `invalid_input`, `forbidden`, `conflict`. `STATUS` i `src/http.ts` mappar dem till 404, 400, 403, 409.
- 401 skrivs direkt av `requireCustomer` i `src/auth.ts` med kod `unauthorized`. Den koden finns inte i `ErrorCode`.
- `sendResult(res, result, okStatus = 200)` skickar `result.value` som JSON vid ok.
- `docs/standard.md` tillåter 409 för konflikt, vilket passar "för sent att avbryta" och "fel status".

### Auth
- `requireCustomer` läser `X-Customer-Id`, kräver heltal > 0, sätter `(req as AuthedRequest).customerId`. Saknas/ogiltigt: 401.
- Routes använder `(req as AuthedRequest).customerId` och skickar det till tjänstelagret. Standarden: id aldrig från body/query, och ägarkontrollen ska göras i tjänstelagret.
- Observera: `requireCustomer` verifierar inte att kunden finns i databasen.

### orderService (`src/services/orderService.ts`)
- `createOrder(customerId, input)`: validerar med `validateLines` (Result), tar en klient från poolen, `BEGIN`, INSERT order, INSERT rader i loop, `COMMIT`, returnerar `getOrder`. Kastar vid oväntade fel efter ROLLBACK (oväntat DB-fel är inte ett förväntat fall, det ger 500 via Express).
- `getOrder(orderId, customerId)`: SELECT order, `not_found` om saknas, `forbidden` om `customerId` skiljer, därefter rader. Returnerar `Result<Order>`.
- Typen `Order` saknar `createdAt` (och `getOrder` hämtar inte `created_at`). Svaret från `GET /orders/:id` innehåller alltså inte skapandetid. `OrderSummary` i `customerService.ts` har `createdAt` (returneras som Date serialiserad till ISO-sträng av JSON).
- Observera: `unitPrice` kommer som sträng från pg (NUMERIC), vilket stämmer med standarden. `OrderLineInput.unitPrice` är `number` vid indata (befintlig avvikelse från "aldrig number", utanför denna story).
- Ägarkontrollen `getOrder` kan återanvändas, men en avbokning bör göra egen läsning med lås (se risker).

### Tester och hjälpare
- Jest + supertest. `tests/orders.test.ts` och `tests/customers.test.ts` kör `createApp()` mot testdatabasen.
- `tests/helpers/env.ts` sätter `DATABASE_URL` till `TEST_DATABASE_URL` eller `postgresql://postgres:postgres@localhost:5432/butik_test`.
- `tests/helpers/db.ts`: `resetDb()` kör hela `schema.sql` (DROP + CREATE) och `seed.sql` före varje test (`beforeEach(resetDb)`), `closeDb()` i `afterAll`.
- Mönster i befintliga tester: `.set("X-Customer-Id", "<id>")`, kontroll av status och `res.body.error.code`. Täcker lyckat fall, 400, 401, 403, 404.
- Inget sätt att styra tid i testerna. Seed-ordrarna har datum i oktober 2026 (äldre än 30 min). Dagens datum i miljön är 2026-11-19, så alla seedade ordrar är äldre än 30 minuter, och `new`-ordrarna 1043 och 1047 är alltså "för gamla" för att avbrytas.
- För "inom 30 min"-testet behövs antingen en order skapad via `POST /orders` (created_at = now()), eller en test-UPDATE av `created_at` via `db.query` (t.ex. `now() - interval '29 minutes'` respektive `'31 minutes'`). Inga nya seed-rader behövs om testerna sätter `created_at` själva. Ett par nya hjälpare vore bra, t.ex. `setOrderAge(orderId, minutes)`.

### Relevanta regler i `docs/standard.md`
- camelCase i JSON och TS, SQL med `AS "camelCase"`.
- Parametriserad SQL, `db.query(sql, [värden])`. Aldrig strängmallar.
- Skrivningar som hör ihop i transaktion.
- Tjänstelagret kastar inte för förväntade fall: `Result` med `ok`/`err`.
- Felsvar `{ error: { code, message } }`; 400/401/403/404/409.
- Ägarkontroll i tjänstelagret, kund från `req.customerId`.
- Varje endpoint ska ha tester för lyckat fall samt 400, 401, 403, 404 där möjliga.
- Inga personuppgifter i loggar. Ta aldrig bort/skippa tester.
- Arkitekturbeslut dokumenteras i `docs/adr/`. `docs/api.md` ska uppdateras.

## 2. Förslag till berörda delar (att bekräfta i planen)

### Endpoint
`POST /orders/:id/cancel` (alternativ: `DELETE /orders/:id` eller `PATCH /orders/:id` med status). Rekommendation: `POST /orders/:id/cancel`, eftersom ordern inte raderas utan statusändras, och ingen body behövs. Svar 200 med uppdaterad order (`Order`-formen, gärna med `status: "cancelled"`). Möjliga svar: 200, 400 (ogiltigt id), 401, 403, 404, 409.

### Databas
- Minimalt: ingen schemaändring. Status sätts till `cancelled` via `UPDATE`.
- Önskvärt (kräver migrering i backbara steg enligt user-stories.md): `cancelled_at TIMESTAMPTZ NULL` för spårbarhet. Beslut behövs. Det finns ingen migreringsmapp idag, bara `db/schema.sql` som tests läser och droppar/skapar om. En eventuell migrering måste även föras in i `schema.sql` för att testerna ska se den.
- Eventuell CHECK på `status` är utanför scope men noteras som svaghet.

### Service
Ny `cancelOrder(orderId, customerId): Promise<Result<Order>>` i `orderService.ts`. Skiss av logiken:
1. Transaktion, `SELECT ... FROM orders WHERE id = $1 FOR UPDATE`.
2. Finns inte: `not_found`. Fel ägare: `forbidden`.
3. Redan `cancelled`: se öppen fråga (idempotent 200 eller 409).
4. Status ej `new` (eller annan tillåten): `conflict`.
5. Tidsgräns i databasen: `now() - created_at <= interval '30 minutes'`, annars `conflict`.
6. `UPDATE orders SET status = 'cancelled' WHERE id = $1 AND status = 'new'` och COMMIT.
7. Returnera `getOrder`.

### Route
`orders.post("/orders/:id/cancel", requireCustomer, ...)` med samma `parseId` och mönster som `GET /orders/:id`.

### Dokumentation
- `docs/api.md`: ny rad i tabellen.
- ADR i `docs/adr/` för tidsfönster/tidskälla/statusregler.

## 3. Acceptanskriterier (utkast, Givet/När/Så)
1. Givet en egen order med status `new` skapad för 10 min sedan, när kunden anropar `POST /orders/:id/cancel`, så svarar API:t 200 och ordern har status `cancelled`.
2. Givet en egen order äldre än 30 min, när kunden avbryter, så svarar API:t 409 `conflict` och ordern är oförändrad.
3. Givet en order med status `paid` eller `shipped` (inom 30 min), när kunden avbryter, så 409.
4. Givet en annan kunds order, så 403 och ordern är oförändrad.
5. Givet ett id som inte finns, så 404. Givet ogiltigt id (`abc`), så 400. Utan `X-Customer-Id`, så 401.
6. Givet en redan avbruten order: beteende enligt beslut (se öppna frågor).
7. Givet exakt 30 minuter: gränsvärde enligt beslut (förslag: tillåtet vid <= 30 min).
8. Givet att avbokningen lyckas, så syns `cancelled` i `GET /orders/:id` och `GET /customers/me/orders`.

## 4. Edge cases
- Gränsvärden: 29:59, 30:00 och 30:01 minuter.
- Dubbel avbokning (dubbelklick, omförsök): ska inte ge fel tillstånd eller dubbla sidoeffekter.
- Order som inte finns, tillhör annan kund (403 före tidskontroll, så att man inte läcker info), ogiltigt id (`0`, `-1`, `1.5`, `abc` ger 400 via `parseId`).
- Ordning på kontroller: id-validering, finns, ägare, status, tid.
- Ordrar med status `new` men äldre än 30 min (seed 1043, 1047) ska ge 409.
- Order med rabattkod: ingen särskild hantering, rabattkoden saknar användningsräknare.
- Avbruten order och `GET /orders/:id/price`: fortfarande prisberäkning (se nuläge).
- Klockskillnad: `created_at` sätts av databasen (`now()`); om tidskontrollen görs i Node med `Date.now()` kan app- och db-klockan skilja.

## 5. Risker och öppna frågor

1. **Tidskälla.** Rekommendation: låt Postgres avgöra (`now() - created_at <= interval '30 minutes'` i samma fråga/transaktion) så att samma klocka används som vid `created_at`. `now()` i Postgres är transaktionens starttid, vilket duger. Nackdel: svårt att testa utan att manipulera `created_at`. Alternativ: injicera klocka i tjänsten (kräver parameter). Testmetod beslutas i planen.
2. **Gränsen 30 minuter.** Inklusive eller exklusive? Konfigurerbar (miljövariabel, t.ex. `CANCEL_WINDOW_MINUTES`, inga hemligheter men bra att inte hårdkoda) eller konstant?
3. **Vilka statusar får avbrytas?** Troligen bara `new`. Är `paid` inom 30 min tillåtet? Om ja, krävs återbetalning, som inte finns i systemet. Förslag: endast `new`, allt annat 409. Ingen kod sätter idag status `paid`, så detta är en produktfråga.
4. **Idempotens.** Redan `cancelled`: returnera 200 (idempotent) eller 409? Förslag: 409 med tydligt meddelande, eller 200 utan ändring, vilket är vänligare vid nätfel (jfr user story 1). Kräver beslut.
5. **Race conditions.**
   - Avbokning och betalning/leverans samtidigt: använd `SELECT ... FOR UPDATE` eller villkorad `UPDATE ... WHERE id = $1 AND status = 'new' AND created_at > now() - interval '30 minutes'` och kontrollera `rowCount`. Det senare är atomiskt och enklast. Behåll ändå separata selects för att kunna ge korrekt felmeddelande (404/403/409).
   - Två samtidiga avbokningar: villkorad UPDATE gör att bara en får `rowCount = 1`.
   - Skapande och avbokning samtidigt är ofarligt eftersom ordern syns först efter COMMIT.
   - Standardens regel om transaktion gäller om fler skrivningar tillkommer (t.ex. lager, `cancelled_at`).
6. **Lagerhantering.** Ingen lagerhantering finns (user story 6 ej byggd), så ingen återlagring behövs nu. Om lager införs senare måste avbokning återföra saldo i samma transaktion. Dokumentera i ADR som framtida koppling.
7. **Sidoeffekter/andra konsumenter.** `jobs/nightly_report.py` räknar bara `paid`. Kontrollera att avbrutna ordrar inte ska ingå (de gör det inte om status ändras till `cancelled`). Legacy-modulens avrundning (`_kapa`) berörs inte och får inte ändras.
8. **Svarsformat.** `Order` saknar `createdAt`. Ska svaret på avbokning/`GET /orders/:id` utökas med `createdAt` (och ev. `cancelledAt`)? En ändring av `Order` påverkar befintliga tester bara om de använder `toEqual` på hela objektet (idag gör de det inte). `docs/api.md` ska uppdateras.
9. **Felkoder.** 409 för "för sent"/"fel status" täcks av `conflict`. Överväg att skilja meddelandena (t.ex. "Tiden för att avbryta har gått ut", "Beställningen kan inte avbrytas i status X"). Ingen ny `ErrorCode` krävs, men en maskinläsbar kod för skillnaden kan efterfrågas av frontend.
10. **Auth-svagheter.** `X-Customer-Id` kan förfalskas (känd förenkling). Ingen kontroll av att kunden finns, men ägarkontrollen ger ändå 404/403.
11. **Schemasvagheter.** Ingen FK och inget CHECK på status. Statusvärdet `cancelled` skrivs som sträng; centralisera som konstant/typ (`OrderStatus`) i koden för att undvika stavfel.
12. **Tester.** Seeden är fast mot datum i oktober 2026, så tidsberoende tester måste sätta `created_at` explicit via `db.query("UPDATE orders SET created_at = now() - ($2 || ' minutes')::interval WHERE id = $1", ...)` (parametriserat). Vid ny migrering måste `schema.sql` uppdateras, eftersom `resetDb` läser den.
13. **Notis/e-post** till kund vid avbokning är inte specificerat och utelämnas. Inga personuppgifter i loggar om loggning läggs till.
14. **Omfång.** Kan kunden avbryta delar av en order (enskilda rader)? Antagande: nej, hela ordern.

## 6. Föreslagna tester (TDD-underlag)
Nya tester i `tests/orders.test.ts` (eller ny fil) för `POST /orders/:id/cancel`:
- 200 för egen `new`-order skapad nyss (via `POST /orders` sedan cancel).
- 200 vid 29 min, 409 vid 31 min (via helper som flyttar `created_at`).
- Gräns vid exakt 30 min enligt beslut.
- 409 för `paid`/`shipped` (seed 1042, 1040 med `created_at` flyttad till nu).
- 409 eller 200 för redan `cancelled` (seed 1046 med flyttad tid) enligt beslut.
- 403 annan kunds order, 404 saknas, 400 ogiltigt id, 401 utan header.
- Order förblir oförändrad efter 409/403 (kontrollera status i db).
- Samtidighet: två parallella cancel-anrop ger exakt en 200 (och en 409/200 enligt idempotensbeslut).
- Efter lyckad avbokning: `GET /customers/me/orders` visar `cancelled`.

## 7. Sammanfattning av beslut som behövs innan planen
1. Endpoint-form (`POST /orders/:id/cancel` rekommenderas).
2. Tillåtna statusar (rekommenderas: endast `new`).
3. Gräns inklusive/exklusive och om 30 min ska vara konfigurerbart.
4. Idempotens vid redan avbruten order.
5. Tidskälla (databasens `now()` rekommenderas).
6. Om `cancelled_at` ska läggas till (migrering) och om `Order` ska utökas med `createdAt`.
