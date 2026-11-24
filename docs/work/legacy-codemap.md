# Codemap: legacy-prisberäkning

Status: analys, ingen källkod ändrad. Underlag för plan (`docs/work/02-plan.md`) och eventuell ADR i `docs/adr/`.

## 1. Filer och placering

| Fil | Roll |
|-----|------|
| `src/legacy/price_calc.py` | Python-modul och CLI. Räknar netto, moms och total för en order. |
| `src/pricing/legacyPrice.ts` | TypeScript-brygga (`calcPrice`) som startar Python som underprocess. |
| `jobs/nightly_report.py` | Cron-jobb som summerar dagens betalda ordrar. Importerar `calc_price` och `conn` från `price_calc`. |
| `src/legacy/price_calc.log` | Loggfil som skrivs av `price_calc.py`. Ligger i `.gitignore`. |

Notera om sökvägen: `legacyPrice.ts` ligger i `src/pricing/`, inte i `src/services/`. CLAUDE.md, `docs/api.md` och `docs/standard.md` stämmer, så kursdokumentets uppgift om `src/services/` är fel. Filen importeras från `src/routes/orders.ts` som `../pricing/legacyPrice`.

## 2. Anropskedja

```
Klient
  GET /orders/:id/price                      (src/routes/orders.ts, rad 41)
    requireCustomer                          -> req.customerId
    parseId(raw)                             -> 400 invalid_input om id inte är heltal > 0
    getOrder(id, customerId)                 (src/services/orderService.ts) ägarkontroll: 404 / 403
    calcPrice(id)                            (src/pricing/legacyPrice.ts)
      execFile("python3", [price_calc.py, id], { env: process.env })
        price_calc.py som __main__:
          calc_price(int(argv[1]))
            3 SQL-frågor mot Postgres (se avsnitt 4)
            _kapa() på net och vat
            append till price_calc.log
          print(json {net, vat, total} som str)
      stdout -> JSON.parse -> ok(Price)
      vilket fel som helst -> err("not_found", ...)
    sendResult(res, result)                  -> 200 { net, vat, total } eller felkod

Cron (driftserver)
  python3 jobs/nightly_report.py [YYYY-MM-DD]
    importerar price_calc  -> öppnar DB-anslutning vid import
    SELECT id ... status = 'paid' ... created_at::date = '<dag>'
    för varje id: calc_price(id)   -> 3 SQL + 1 loggrad per order
    skriver ut "<dag>: N betalda ordrar, totalt X kr"
```

Det finns alltså två helt separata sätt att nå samma Python-funktion. API:t startar en ny Python-process per request. Rapporten kör `calc_price` in-process i en loop.

## 3. Funktioner och ansvar

### `src/legacy/price_calc.py`

| Symbol | Ansvar |
|--------|--------|
| `DB` | `DATABASE_URL` eller hårdkodad default `postgresql://postgres:postgres@localhost:5432/butik`. |
| `conn` | Global `psycopg.connect(DB, autocommit=True)`. Skapas vid import, dvs. som sidoeffekt av `import price_calc`. |
| `MOMS = 25` | Momssats i procent. Heltal, hårdkodat. |
| `LOGG` | Sökväg till `price_calc.log`, relativt modulens egen katalog. |
| `class Pris` | Dataholder med `net`, `vat`, `total` (Decimal). |
| `_kapa(x)` | `Decimal(int(x * 100)) / 100`. Trunkerar mot noll till 2 decimaler. Se avsnitt 6. |
| `calc_price(order_id)` | Läser order, rader och rabatt, räknar pris, loggar, returnerar `Pris` eller `None` om ordern saknas. |
| `__main__` | CLI. Skriver JSON `{"net","vat","total"}` på stdout, eller `{"error": "finns inte"}` med exit 1. |

Beräkningsordning i `calc_price`:

1. `summa = sum(quantity * unit_price)` över orderrader (Decimal, eftersom `unit_price` är NUMERIC).
2. Om `discount_code` finns och koden finns i `discounts`: `summa = summa - summa * percent / 100`. Ingen avrundning här.
3. `net = _kapa(summa)`.
4. `vat = _kapa(net * 25 / 100)`. Momsen räknas på redan trunkerat netto.
5. `total = net + vat`. Ingen ytterligare avrundning.

### `src/pricing/legacyPrice.ts`

| Symbol | Ansvar |
|--------|--------|
| `Price` | `{ net, vat, total }` som strängar. |
| `SCRIPT` | Absolut sökväg till `../legacy/price_calc.py` via `__dirname`. |
| `calcPrice(orderId)` | Startar `python3`, tolkar stdout som JSON och returnerar `Result<Price>`. |

### `jobs/nightly_report.py`

Skript utan funktioner, körs på modulnivå. Tar valfritt datum som `argv[1]`, annars `date.today()`. Summerar `p.total` för alla ordrar med `status = 'paid'` och `created_at::date = dag`. Skriver en rad till stdout.

## 4. Databasberoenden

### Tabeller och kolumner som läses (inga skrivningar till DB)

| Tabell | Kolumner | Använd av |
|--------|----------|-----------|
| `orders` | `id`, `discount_code`, `status`, `created_at` | `calc_price`, `nightly_report` |
| `order_lines` | `order_id`, `quantity` (INTEGER), `unit_price` (NUMERIC(10,2)) | `calc_price` |
| `discounts` | `code`, `percent` (INTEGER) | `calc_price` |

Schemat (`db/schema.sql`) saknar främmande nycklar, index (utöver primärnycklar) och CHECK-villkor. `discounts.valid_from` och `valid_to` finns men läses aldrig av legacykoden.

### SQL-frågor (alla strängformaterade med `%`)

| # | Fil och rad | SQL | Indata |
|---|-------------|-----|--------|
| 1 | `price_calc.py:30` | `select discount_code from orders where id = %s` | `order_id` (int från `parseId` eller `int(argv)`) |
| 2 | `price_calc.py:36` | `select quantity, unit_price from order_lines where order_id = %s` | `order_id` |
| 3 | `price_calc.py:42` | `select percent from discounts where code = '%s'` | `kod` från `orders.discount_code`, ursprungligen fri text från kunden |
| 4 | `nightly_report.py:8` | `select id from orders where status = 'paid' and created_at::date = '%s'` | `dag` från `argv[1]`, helt oval­iderad |

Alla fyra bryter mot `docs/standard.md` (parametriserad SQL).

### Anslutningar och cursors

- En global anslutning `conn` per Python-process, autocommit, aldrig stängd.
- `calc_price` skapar en ny `cursor()` per anrop och stänger den aldrig. I rapportjobbet blir det en cursor per order.
- `nightly_report.py` skapar dessutom en egen cursor på samma `conn` och itererar över `fetchall()` medan `calc_price` använder samma anslutning. Det fungerar bara eftersom `fetchall()` redan har läst allt.
- API-vägen: varje `GET /orders/:id/price` ger en ny Python-process och en ny Postgres-anslutning, helt utanför `pg.Pool` i `src/db.ts`. Under belastning ger det många samtidiga anslutningar och kostnad för uppstart av Python och anslutning per request.
- Ingen transaktion runt de tre SELECT:arna. Med autocommit kan en order ändras mellan fråga 1 och 2 (inkonsistent läsning).

## 5. Filloggning (`price_calc.log`)

- Skrivs i slutet av `calc_price`: `"<ISO-tid> <order_id> <total>\n"`, öppnad med `open(LOGG, "a")`.
- Format exempel: `2026-11-24T14:14:04.223809 1042 1187.5`. Filen innehåller i dag 11 rader, alla för order 1042.
- Skrivs av båda anropsvägarna (API-processen och nattjobbet). Alltså en loggrad per prisberäkning, även för rena läsningar (GET).
- Fel sväljs av en bar `except: pass`. Om filen inte går att skriva (rättigheter, fullt disk, read-only container) sker ingenting och inget larmas.
- Filen stängs inte med `with`. Om `write` kastar läcker filhandtaget tills processen avslutas.
- Ingen rotation, ingen låsning. Samtidiga appendar från flera processer är i praktiken atomiska för korta rader på POSIX men är inte garanterat på Windows.
- Innehåll: tidsstämpel, order-id och totalbelopp. Ingen kund, namn eller e-post, så inga direkta personuppgifter i dag. Order-id plus belopp och tid är dock kopplingsbara till en kund via `orders.customer_id`, vilket gör filen till pseudonymiserad persondata om den delas. Den är ändå gitignorerad.
- Sökvägen är relativ modulens katalog, dvs. inne i `src/`. Skrivbar källkatalog i drift är olämpligt.
- Loggformatet för total är `str(Decimal)`, så `1187.5` i stället för `1187.50`.
- Tidsstämpeln är lokal tid utan tidszon (`datetime.now().isoformat()`).

## 6. Avrundning i `_kapa` (får INTE ändras utan explicit beslut)

```python
def _kapa(x):
    return Decimal(int(x * 100)) / 100
```

Beteende:

- `int()` trunkerar mot noll, alltså ingen halvuppåt- eller bankers-avrundning. Antalet decimaler är 2.
- Eftersom indata är `Decimal` är `x * 100` exakt, så trunkeringen är deterministisk. Om någon skickar in `float` kan `int(x * 100)` ge fel på grund av binär representation (t.ex. 0.29 * 100 = 28.999...). Dagens flöde ger bara Decimal.
- Avrundningen sker på två ställen, och ordningen är en del av det avstämda beteendet: (1) rabatt dras av utan avrundning och trunkeras först i `net`, (2) moms räknas på trunkerat `net` och trunkeras igen. `total = net + vat` summeras utan avrundning.
- Resultatet av `Decimal(int)/100` normaliseras inte till 2 decimaler. `Decimal(95000)/100` blir `Decimal('950')`, och `Decimal(23750)/100` blir `Decimal('237.5')`.

Räkneexempel mot seed-data (härledda ur koden, inte körda):

| Order | Rabatt | Netto före trunkering | net | vat | total |
|-------|--------|-----------------------|-----|-----|-------|
| 1042 | ingen | 950.00 | 950 | 237.5 | 1187.5 (matchar loggen) |
| 1044 | VAR10 (10 %) | 199.90 - 19.990 = 179.910 | 179.91 | 44.97 (44.9775 trunkerat, avrundat hade gett 44.98) | 224.88 |
| 1045 | GAMMAL15 (15 %) | 649.00 * 0.85 = 551.65 | 551.65 | 137.91 (137.9125) | 689.56 |
| 1041 | SOMMAR20 (20 %) | 736.00 - 147.20 = 588.80 | 588.8 | 147.2 | 736.0 |

Konsekvens för API-kontraktet: `docs/standard.md` kräver belopp som strängar med 2 decimaler, men legacy ger t.ex. `"950"` och `"237.5"`. Ett fix kräver formattering (`quantize`/`format`) som inte ändrar själva trunkeringen. Det ska i så fall beslutas explicit, eftersom det ändrar svarsformatet.

## 7. Dolda antaganden och beteenden

1. Rabattkodens giltighetsperiod (`valid_from`, `valid_to`) ignoreras. Order 1045 med utgången `GAMMAL15` (2024) får ändå 15 % rabatt.
2. Okänd rabattkod ger tyst ingen rabatt (inget fel).
3. Ordrar prissätts oavsett status, även `cancelled`. Rapporten filtrerar på `paid`, men `shipped` räknas då inte med trots att de är betalda (seed har 1040 och 1041 som `shipped`). Det kan vara avsiktligt eller en lucka.
4. `created_at::date` använder databassessionens tidszon, inte nödvändigtvis svensk tid. Kolumnen är TIMESTAMPTZ. Ordrar nära midnatt kan hamna på fel dag.
5. Moms 25 % för alla produkter, ingen sats per rad.
6. Rabatt är ett heltalsprocent. Rabatt är på hela ordern, inte per rad.
7. Ordern utan rader ger net 0, vat 0, total 0 utan fel.
8. `calc_price` returnerar `None` för saknad order. Det hanteras olika: CLI skriver JSON-fel och exit 1, men `nightly_report.py` gör `p.total` direkt och kraschar med `AttributeError` om en order raderats mellan SELECT och beräkning.
9. `nightly_report.py` startar med `summa = 0` (int) och adderar Decimal. Fungerar, men utskriften har inte 2 decimaler och saknar tusentalsformat.
10. Importen av `price_calc` är inte sidoeffektfri: den öppnar DB-anslutning direkt. Det går inte att testa enhetsvis utan en databas.
11. Pythonkommandot heter `python3` i TS. På Windows heter det normalt `python`, vilket ger fel i utvecklingsmiljön här (plattformen är Windows).
12. `psycopg` (v3) måste vara installerat i den Python som körs. Det finns ingen `requirements.txt` eller motsvarande beskriven i repot.
13. Hårdkodade default-uppgifter `postgres:postgres` finns i både `price_calc.py` och `src/db.ts`.
14. Inga tester finns för legacykoden (bekräftat i `docs/api.md`).

## 8. Risker och brister

Allvarlighet: H = hög, M = medel, L = låg.

| # | Sev | Brist | Plats | Kommentar |
|---|-----|-------|-------|-----------|
| 1 | H | Strängformaterad SQL, andra ordningens SQL-injektion | `price_calc.py:42` | `discountCode` sparas parametriserat via `POST /orders`, men läses sedan tillbaka och interpoleras i `'%s'`. En kod som `x' OR '1'='1` eller en enkel apostrof ger felaktigt resultat eller fel. Detta är nåbart av en inloggad kund via API:t. |
| 2 | H | Strängformaterad SQL med okontrollerad CLI-indata | `nightly_report.py:8` | `argv[1]` interpoleras. Begränsad risk (cron styr argumentet) men bryter mot standarden. |
| 3 | M | Strängformaterad SQL för ordre-id | `price_calc.py:30,36` | Id är `int` i båda anropsvägarna, så praktiskt låg risk, men samma mönster. |
| 4 | M | Alla fel blir `not_found` | `legacyPrice.ts:13-15` | DB nere, Python saknas, syntaxfel och verkligt saknad order ger alla 404. Ger vilseledande svar och döljer driftfel. |
| 5 | M | Okontrollerad `JSON.parse` | `legacyPrice.ts:17` | Om stdout inte är giltig JSON kastas ett undantag inne i execFile-callbacken. Promise löses aldrig och processen kan krascha. Ingen validering av formen. |
| 6 | M | Ingen timeout eller concurrency-gräns på underprocessen | `legacyPrice.ts:12` | Hängande Python eller DB blockerar requests utan tak. En process och en DB-anslutning per request. |
| 7 | M | Resursläckor | `price_calc.py` | `conn` och cursors stängs aldrig. Loggfilen öppnas utan `with`. Rapporten skapar en cursor per order. |
| 8 | M | Flyttal i kringkod runt belopp | `orderService.ts:4,32` | `unitPrice` är `number` vid indata. Legacykoden själv använder Decimal, men inkommande belopp passerar JS-flyttal innan de lagras i NUMERIC. Nattjobbets summa startar som int. Båda strider mot standarden om Decimal/NUMERIC. Notera att `_kapa` blir fel om någon matar in `float`. |
| 9 | M | Beloppsformat bryter mot standard | `price_calc.py:66` | Strängar utan garanterade 2 decimaler (`"950"`, `"237.5"`). |
| 10 | M | Tyst felhantering | `price_calc.py:55` | Bar `except: pass` sväljer även `KeyboardInterrupt` och `SystemExit`. Loggfel syns aldrig. |
| 11 | M | Sidoeffekt (filskrivning) i beräkningsfunktion | `price_calc.py:51-56` | En GET skriver till disk i källkatalogen. Svårtestat, och ger loggbrus (nattjobbet loggar varje order). |
| 12 | L | PII i loggar | `price_calc.log` | Inga namn eller e-postadresser i dag. Order-id kopplat till belopp och tid är indirekt koppling till en kund. Måste hållas så vid refaktorering (logga aldrig kunduppgifter, rabattkoder eller råa SQL-fel som kan innehålla data). |
| 13 | M | Ingen konsistent läsning | `price_calc.py:30-42` | Tre separata autocommit-frågor, ingen transaktion. |
| 14 | M | Hårdkodade default-inloggningsuppgifter | `price_calc.py:9`, `src/db.ts:5` | Strider mot "inga hemligheter i kod". |
| 15 | M | Affärsregelluckor | se avsnitt 7 punkt 1-3 | Utgångna rabatter appliceras, status ignoreras. |
| 16 | L | Rapport kraschar vid `None` | `nightly_report.py:13` | Hela nattrapporten faller på en raderad order. |
| 17 | L | N+1-frågor | `nightly_report.py` | 1 + 3 frågor per order. |
| 18 | L | Portabilitet | `legacyPrice.ts:12` | `python3` fungerar inte på Windows. |
| 19 | L | Duplicerad logik-risk | `docs/standard.md:26` | All prisberäkning ska gå via `calcPrice`. `nightly_report.py` går förbi den och anropar Python direkt. En migrering måste ge rapporten samma väg. |

## 9. Föreslagna refaktoreringssteg

Ordningen följer flödet Research -> Plan -> TDD. Varje steg ska vara litet och köras grönt innan nästa.

1. **Fastställ beslut och skydd först.** Skriv en ADR i `docs/adr/` som anger att `_kapa`-trunkering (och beräkningsordningen i avsnitt 6) är bindande kontrakt, och hur beloppsformatet (2 decimaler) ska hanteras. Inget steg nedan får ändra trunkeringen.
2. **Karakteriseringstester (golden master).** Kör nuvarande kod mot seed-orderna 1040-1047 och lås resultaten (se tabellen i avsnitt 6, även kantfall: 44.9775 trunkeras till 44.97, utgången kod, okänd kod, tom order, saknad order). Lägg till ett test för `_kapa` med decimaltal där trunkering och avrundning skiljer sig. Inga `.skip` eller `.only`.
3. **Gör Python testbar utan att ändra beteende.** Flytta anslutningen från importtid till en funktion (`get_conn()`), och låt `calc_price` ta emot anslutning/cursor som parameter. Ändra `nightly_report.py` i takt med detta.
4. **Parametrisera all SQL i Python.** Byt `%` mot `cur.execute(sql, (värde,))` för frågorna på rad 30, 36, 42 och i rapporten. Verifiera med test att en apostrof i rabattkod inte längre ger fel eller injektion. Beteendet för giltiga indata ska vara identiskt.
5. **Stäng resurser.** Använd `with conn.cursor() as cur` och `with open(...)`. Stäng anslutningen i CLI och rapport (`try/finally`). Ersätt bar `except:` med `except OSError` och rapportera fel till stderr eller en logger.
6. **Separera beräkning från sidoeffekt.** Dela `calc_price` i en ren funktion (rader + procent -> `Pris`) och ett I/O-lager (läs DB, skriv logg). Gör loggning valbar och flytta loggfilen ut ur `src/` (konfigurerbar sökväg via miljövariabel). Logga bara order-id och belopp, aldrig kunduppgifter.
7. **Gör felhantering tydlig i bryggan.** I `legacyPrice.ts`: separera "order saknas" (exit 1 + JSON-fel) från tekniska fel, mappa tekniska fel till ett eget felresultat (kräver ny kod i `result.ts`/`http.ts`, t.ex. `internal`, och uppdaterad `docs/api.md`), validera JSON-formen och sätt `timeout`. Gör kommandot (`python3`/`python`) konfigurerbart.
8. **Rapporten ska hantera `None` och dagsgräns.** Hoppa över eller rapportera saknade ordrar. Besluta explicit om tidszon för `created_at::date` och om `shipped` ska ingå. Använd `Decimal` för summan och formatera med 2 decimaler.
9. **Beslut om affärsregelluckor.** Ta ställning till giltighetsdatum för rabatter och orderstatus. Detta ändrar belopp och kräver ekonomins godkännande, så gör det som separata, dokumenterade beslut efter att refaktoreringen är grön.
10. **Beloppsformat.** Normalisera utdata till strängar med exakt 2 decimaler (`quantize(Decimal("0.01"))` efter trunkering, vilket inte ändrar värdet). Uppdatera `docs/api.md` och tester samtidigt.
11. **Portera till TypeScript (valfritt, sist).** Implementera samma beräkning i `src/pricing/` med parametriserad SQL via `db.query` och en decimalbibliotek (inte `number`). Kör golden master-testerna mot båda implementationerna parallellt, byt sedan över och ta bort Python-bryggan. Låt nattrapporten gå via samma `calcPrice` (standard.md rad 26) eller en gemensam modul.
12. **Städa.** Ta bort hårdkodade default-uppgifter, dokumentera krav (`psycopg`, Python-version), uppdatera `docs/api.md` (avsnittet "Den äldre modulen") och skriv sessionslogg.

## 10. Öppna frågor till ekonomi/produktägare

- Ska utgångna rabattkoder verkligen ge rabatt (avsnitt 7 punkt 1)?
- Ska `shipped` ingå i nattrapporten?
- Vilken tidszon gäller för "dagens" ordrar?
- Får beloppen i API-svaret formatteras med 2 decimaler (`"950.00"`) utan att det räknas som ändrad avrundning?
