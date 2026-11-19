# ADR 0001: Avbryta en beställning inom 30 minuter

- Status: Accepterad
- Datum: 2026-11-19
- User story: "Kunden kan avbryta en beställning inom 30 minuter" (nr 2 i `docs/user-stories.md`)
- Underlag: `docs/work/01-research.md`, `docs/work/02-plan.md`

## Kontext

Kunden ska kunna avbryta en egen beställning kort efter att den lagts. Idag finns ingen kod som ändrar orderstatus. `orders.status` är `TEXT` utan CHECK, `created_at` är `TIMESTAMPTZ DEFAULT now()` och statusvärdet `cancelled` finns redan i seed-data. Inget lager, ingen betalning och ingen återbetalning finns i systemet.

Huvudbeslutet gäller var och hur tidsgränsen avgörs, eftersom det styr korrekthet (klockor, samtidighet) och testbarhet. Övriga beslut är samlade här så att de ligger på ett ställe.

## Beslut

1. **Endpoint:** `POST /orders/:id/cancel`. Ordern raderas inte, bara statusen ändras, och ingen body behövs.
2. **Tillåten status:** Endast `new` får avbrytas. Alla andra statusar (`paid`, `shipped`, `cancelled`) ger 409 `conflict`.
3. **Tidsgräns:** Inklusive, alltså `now() - created_at <= 30 minutes`. Värdet är en konstant i koden (`CANCEL_WINDOW_MINUTES = 30`), inte en miljövariabel.
4. **Idempotens:** En redan avbruten order ger 409 `conflict` med ett tydligt meddelande. Anropet är alltså inte idempotent på svarsnivå, men tillståndet förblir korrekt vid upprepade anrop.
5. **Tidskälla:** Databasens `now()`, utvärderat i SQL i samma transaktion som ändringen. Samma klocka sätter `created_at` och avgör gränsen, så app- och databasklockor kan inte skilja sig åt.
6. **Schema:** Ingen ny migrering och ingen `cancelled_at`. Status sätts till `'cancelled'`. `Order`-objektet i API-svaret utökas med `createdAt` (ISO 8601-sträng), vilket även påverkar `GET /orders/:id`.

### Genomförande (översikt)

- `cancelOrder(orderId, customerId): Promise<Result<Order>>` i `src/services/orderService.ts`, i en transaktion: `SELECT ... FOR UPDATE`, kontroller i ordningen finns, ägare, status, tid, därefter `UPDATE orders SET status = 'cancelled' WHERE id = $1 AND status = 'new'`.
- Tidsvillkoret beräknas i SQL (`now() - created_at <= make_interval(mins => $2) AS "withinWindow"`) med minutantalet som parameter. Ingen strängmall i SQL.
- Statusvärden samlas som typ/konstant (`OrderStatus`) i stället för utspridda strängar.
- Tjänsten returnerar `Result` via `err("conflict", ...)` och kastar inte för förväntade fall.

## Alternativ som övervägdes

- **Tidskontroll i Node med `Date.now()`:** Enklare att testa men ger risk för klockskillnad mellan app och databas, samt en tidlucka mellan kontroll och ändring. Avvisat.
- **Injicerad klocka i tjänsten:** Bättre testbarhet men kräver extra parameter genom hela lagret och löser inte klockskillnaden. Avvisat.
- **Idempotent 200 för redan avbruten order:** Vänligare vid nätfel, men beslutet blev 409 för tydlig och enhetlig semantik.
- **Konfigurerbar gräns via miljövariabel:** Onödigt nu. Konstanten är lätt att flytta till konfiguration senare.
- **`cancelled_at` med migrering:** Ger spårbarhet men kräver schemaändring (och uppdatering av `db/schema.sql`). Uppskjutet.
- **`DELETE /orders/:id` eller `PATCH /orders/:id`:** Fel semantik (raderar inte) respektive bredare yta än behövs.

## Konsekvenser

- Positivt: Atomisk och korrekt gräns med en enda tidskälla. Dubbla eller samtidiga anrop ger exakt en lyckad avbokning tack vare radlåset och det villkorade `UPDATE`.
- Negativt: Tester kan inte styra klockan. De måste flytta `created_at` med en parametriserad `UPDATE` i testdatabasen (t.ex. `now() - interval`).
- Ingen spårbarhet för när en order avbröts, eftersom `cancelled_at` saknas. Kan läggas till senare med en backbar migrering.
- `now()` är transaktionens starttid. Om `FOR UPDATE` väntar på ett lås kan avgörandet ligga marginellt före låsets förvärv. Det accepteras.
- Ingen lagerhantering finns. Om lager införs måste avbokningen återföra saldo i samma transaktion.
- Beställningar som avbryts ändrar inte nattrapporten (`jobs/nightly_report.py` räknar bara `paid`). `GET /orders/:id/price` räknar fortfarande pris för avbrutna ordrar (oförändrat beteende).
- Legacy-modulen (`price_calc.py`, `_kapa`) berörs inte.
