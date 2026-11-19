# Granskning: Kunden kan avbryta en beställning inom 30 minuter

Granskade commits: `7bbcd70` (test) och `cb8b925` (feat). Underlag: `docs/work/02-plan.md` (AK1-AK13, API-kontrakt), `docs/adr/0001-avbryta-bestallning.md`, `docs/standard.md`. Ingen kod har ändrats. Radnummer avser nuvarande innehåll i arbetskatalogen (filerna är oförändrade sedan commit). LF/CRLF-varningar ignoreras. Granskningen är statisk: testsviten har inte körts i den här granskningen.

## Sammanfattning

Implementationen följer planen och ADR:en väl. Ordningen på kontrollerna är korrekt (404, 403, 409 redan avbruten, 409 status, 409 tid), 403 kommer före alla 409, SQL är genomgående parametriserad, transaktionen har `FOR UPDATE` plus ett villkorat `UPDATE`, och klienten släpps i `finally`. Tjänstelagret returnerar `Result` för alla förväntade fall. Inga loggar och inga personuppgifter tillkommer. Inga tester har tagits bort eller skippats (commit 7bbcd70 lägger bara till filer), och gränstesterna ligger på 29:59 och 30:01 som planen beslutade.

Inga blockerande fynd. Tre punkter bör åtgärdas eller beslutas: ett oväntat fel i `cancelOrder` kan göra att anropet hänger (Express 4), `UPDATE`-resultatet kontrolleras inte, och "exakt 30:00" (AK2) testas inte bokstavligt. Resten är noteringar.

## Anmärkningar

### Blockerande

Inga.

### Bör åtgärdas

**1. Oväntat fel kastas ur tjänsten och fångas inte i routen (hängande anrop i Express 4)**
- Fil: `src/services/orderService.ts:136-138` (`throw e`), `src/routes/orders.ts:31-38`, `src/app.ts:5-14`.
- Fel: Vid ett oväntat databasfel (t.ex. tappad anslutning) kastas felet vidare. Routen är en `async`-handler utan try/catch och appen saknar felhanterare. I Express 4 (`^4.22.3`) leder en avvisad promise i en async-handler inte till `next(err)`, så klienten får inget svar (timeout) och processen kan få en unhandled rejection.
- Risk: Hängande anrop och möjligt processfall vid databasstörning. Mönstret är detsamma som i `createOrder` (`orderService.ts:65-67`), så det är ärvt snarare än nytt. Kastet gäller inte förväntade fall, så regeln "tjänsten kastar inte för förväntade fall" är uppfylld.
- Kontroll i riggen: Ingen. `check-standard.mjs` letar bara efter `throw new Error` i `src/services/`, inte `throw e`. Förslag: en central felhanterare i `createApp` (eller omslag för async-routes) som svarar 500 med `{ error: { code, message } }`. Standarden definierar ingen 500-kod i dag.

**2. `UPDATE` kontrolleras inte (`rowCount`)**
- Fil: `src/services/orderService.ts:130-134`.
- Fel: Resultatet av `UPDATE ... WHERE id = $1 AND status = $3` kontrolleras inte. Om 0 rader ändras (kan inte hända så länge `FOR UPDATE` håller, men villkoret finns just som skydd för det fallet) fortsätter koden till `COMMIT` och svarar 200 via `getOrder` med oförändrad status.
- Risk: Försvaret på djupet fungerar tyst felaktigt om låset någon gång ändras eller tas bort vid en refaktorering. Ett falskt 200 för en icke-avbruten order är värre än ett 409.
- Kontroll i riggen: AK6 och AK7 skulle sannolikt fånga en regression i låset, men ingen hook kontrollerar detta. Åtgärd: kontrollera `rowCount === 1`, annars `ROLLBACK` och `err("conflict", ...)`.

**3. "Exakt 30 minuter" (AK2) testas inte bokstavligt, så gränsen inklusive är inte låst i test**
- Fil: `tests/cancelOrder.test.ts:53-61` och `:63-72`.
- Fel: AK2 i planen beskriver både 29 min och exakt 30 min. Testerna använder 29:59 och 30:01 (godkänt i planens risksektion, rad 121), men inget test skiljer `<=` från `<`. En ändring till `<` i `orderService.ts:102` skulle fortfarande ge gröna tester.
- Risk: Beslut 3 (gräns inklusive) saknar skydd mot regression.
- Åtgärd: Antingen ett test med mycket liten marginal (t.ex. 30 min minus 200 ms) eller en uttrycklig notering i testet/ADR att gränsen inte kan testas exakt utan injicerbar klocka.

### Notering

**4. Dubblerad `ROLLBACK`-logik och risk för att dölja ursprungsfelet**
- Fil: `src/services/orderService.ts:107, 112, 116, 120, 124, 137`.
- Sex `ROLLBACK`-anrop. Alla tidiga returer rullar tillbaka korrekt och klienten släpps alltid i `finally` (`:140`), så det är korrekt idag. Om `ROLLBACK` i catch (`:137`) självt kastar döljs det ursprungliga felet, och en trasig klient släpps tillbaka till poolen utan `release(err)`. Förslag: samla valideringen i en hjälpfunktion som returnerar `Result` och gör `ROLLBACK` på ett ställe.

**5. Avslutande `getOrder` ligger utanför transaktionen**
- Fil: `src/services/orderService.ts:142`.
- Läsningen sker efter `COMMIT` på poolen. Eftersom ordern är avbruten och ägaren redan verifierad är risken försumbar. Kostar en extra fråga/anslutning per anrop. Acceptabelt.

**6. `now()` är transaktionens starttid**
- Fil: `src/services/orderService.ts:102`.
- Om `FOR UPDATE` väntar på ett lås avgörs tidsgränsen något före låsets förvärv. Dokumenterat och accepterat i ADR (Konsekvenser). Samtidighetsmodellen är i övrigt korrekt: under READ COMMITTED läser det andra anropet om raden efter första COMMIT och ser `cancelled`, vilket ger 409 (AK7).

**7. 404 respektive 403 avslöjar om ett order-id finns**
- Fil: `src/services/orderService.ts:106-114`.
- Följer planen och befintligt beteende i `getOrder` (`:80-86`). Ägarkontrollen sker före alla 409, så status och ålder på andras ordrar läcker inte. Id:t är ett löpnummer (`SERIAL`), så existens kan räknas upp. Känd avvägning, ingen ändring begärd.

**8. Autentisering är en förenklad header**
- Fil: `src/auth.ts:27-38`.
- `customerId` kommer från `req.customerId` (aldrig body/query) och ändringen följer standarden. Headern kan förfalskas av vem som helst, vilket är dokumenterat som en övningsförenkling i filen. Utanför avbokningens scope.

**9. Testhjälpare och testdesign**
- Fil: `tests/helpers/orders.ts:11-16`, `tests/cancelOrder.test.ts:123-133`.
- `setOrderAge` använder parametriserad SQL och `make_interval(secs => $2)`, vilket är korrekt. `now()` i hjälparen och i tjänsten ligger i olika transaktioner, så åldern är minst det angivna värdet plus testets körtid. Marginalen på 1 s för 29:59 är tillräcklig i normala fall men kan bli flaky på en mycket belastad CI-maskin. AK7 (`Promise.all`) bevisar att exakt ett anrop lyckas men inte om det är radlåset eller det villkorade `UPDATE` som ger skyddet; det räcker för kravet.
- `tests/helpers/orders.ts:30` castar `result.rows[0] as OrderRow` utan kontroll. Ofarligt i test.

**10. Testtäckning mot `docs/standard.md`**
- Fil: `tests/cancelOrder.test.ts`.
- Lyckat fall samt 400 (`:175`), 401 (`:182`), 403, 404 (`:168`) och alla 409-fall finns. AK1-AK13 är täckta. Saknas: 401 för ogiltigt (icke-numeriskt) `X-Customer-Id` på just denna route. Det tillhör `requireCustomer` och täcks sannolikt redan i andra tester.

**11. `docs/api.md` stämmer med implementationen**
- Fil: `docs/api.md` (ny tabellrad för `POST /orders/:id/cancel`, stycket om `createdAt` på rad 16).
- Statuskoderna 200/400/401/403/404/409 och villkoren (högst 30 minuter, inklusive, endast `new`) stämmer med koden. Mindre: tabellraderna för `POST /orders` och `GET /orders/:id` nämner inte `createdAt` uttryckligen, men stycket på rad 16 täcker beställningsobjektet. Felformatet beskrivs inte i den nya raden men gäller globalt.

**12. Vad riggen faktiskt skyddar mot här**
- `.claude/hooks/check-standard.mjs`: fångar `throw new Error` i `src/services/`, SQL med `${...}`, `req.body|query.customerId` och `parseFloat` i `pricing/`. Inget av detta förekommer i ändringarna. Notera att `throw e` inte fångas.
- `.claude/hooks/protect-tests.mjs`: stoppar `.skip`/`.only` och tömda testfiler vid Edit/Write, men inte ändringar via Bash. Inga sådana mönster finns i `tests/`.
- Inget i riggen kontrollerar transaktionsdisciplin (ROLLBACK/release), ordningen 403 före 409, race conditions eller N+1. Det kräver granskning och tester, vilket denna rapport och AK6/AK7/AK8 gör.

## Vad som är bra

- Rätt kontrollordning och 403 före alla 409, bevisat av tre separata tester (AK8).
- Tidsgränsen avgörs i SQL med databasens `now()` och parametriserat minutantal (`orderService.ts:101-104`). Ingen strängmall i SQL och ingen klockskillnad mellan app och databas.
- `SELECT ... FOR UPDATE` plus `UPDATE ... AND status = $3` ger robust samtidighetsskydd. Konstanterna `OrderStatus` och `CANCEL_WINDOW_MINUTES` ersätter utspridda strängar och magiska tal.
- `ROLLBACK` före varje tidig retur och `client.release()` i `finally`.
- Tjänstelagret returnerar `Result` via `err(...)` för alla förväntade fall. Routen använder `sendResult`/`sendError` och befintlig `parseId`, och `customerId` hämtas från `req.customerId`.
- Felmeddelandena innehåller inga personuppgifter och inga nya loggar tillkommer.
- Tester: testcommit före implementation, kontroll av oförändrad rad via `getOrderRow` + `toEqual`, gränsvärden enligt plan, inget skippat eller borttaget, hjälpare med parametriserad SQL.
- `createdAt` är en additiv ändring med eget test (AK13), och `docs/api.md` och ADR är uppdaterade i linje med koden.

## Slutsats

Godkänd med anmärkningar. Inget blockerar sammanslagning. Bör åtgärdas före leverans eller läggas som uppföljning: (1) central felhantering så att oväntade fel inte hänger anropet, (2) kontrollera `rowCount` på `UPDATE`, (3) besluta hur gränsen "inklusive" ska skyddas av test. Övriga punkter är noteringar. Verifiering (`npm test && npm run lint && npm run typecheck`) ska köras separat enligt flödet.

## Åtgärdsstatus

| Punkt | Status |
|---|---|
| 1. Central felhantering för oväntade fel (`throw e`, ingen felhanterare i `app.ts`) | Medvetet lämnad som dokumenterad notering. Gäller även `createOrder` och bör hanteras som en egen uppföljning. |
| 2. Kontroll av `rowCount === 1` efter `UPDATE` | Åtgärdad i commit `11aa01a`. |
| 3. Test som låser gränsen "inklusive" (`<=`) | Medvetet lämnad som dokumenterad notering. Testerna använder 29:59 och 30:01 enligt godkänd plan. |

Slutverifiering efter åtgärd av punkt 2: `npm test` (38 av 38), `npm run lint` och `npm run typecheck` var gröna.
