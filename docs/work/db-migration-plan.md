# Migreringsplan för databasen (expand/contract)

Underlag: `db/schema.sql`, `docs/work/legacy-codemap.md`, ADR 0002. Planen är skriven, inte körd. Inga SQL-ändringar är gjorda i repot.

## Mål

Två förändringar som hör ihop med moderniseringen av `price_calc.py`:

- **A. Integritet.** Schemat saknar främmande nycklar, index och CHECK. `orders.discount_code` kan peka på en rabattkod som inte finns, och `order_lines.order_id` på en order som inte finns (nattrapporten kraschade tidigare på det).
- **B. Persistera beräknat pris.** Priset räknas om vid varje anrop och skrivs bara till `src/legacy/price_calc.log`. Ett `order_price_snapshots` ger spårbarhet (vilket belopp visades) och ersätter filloggen.

`_kapa` ändras inte i någon del av planen. Snapshot-beloppen lagras som `NUMERIC(10,2)` av redan trunkerade värden, så formatet "950" mot `950.00` är en visningsfråga och påverkar inte avrundningen.

## Princip

Varje steg är ett eget deployment som är bakåtkompatibelt med både föregående och nästa appversion. Ordningen är alltid: expand (additivt) → migrera data/dual-write → byt läsning → contract (destruktivt). Bara contract-stegen förlorar något, och de körs sist efter en karenstid.

## Del A: Integritet

| Steg | Fas | Åtgärd | Backa? |
|---|---|---|---|
| A0 | Förkontroll | Kör kontrollfrågor (se nedan). Ändrar inget. | Inget att backa |
| A1 | Expand | `CREATE INDEX CONCURRENTLY idx_order_lines_order_id ON order_lines(order_id)` och `idx_orders_customer_id`. | Ja, `DROP INDEX`. Ingen dataförlust. |
| A2 | Expand | `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID` för `order_lines.order_id → orders.id`, `orders.customer_id → customers.id`, `orders.discount_code → discounts.code`. Och `CHECK (percent BETWEEN 0 AND 100) NOT VALID` på `discounts`. NOT VALID kontrollerar bara nya skrivningar. | Ja, `DROP CONSTRAINT`. Ingen dataförlust. |
| A3 | Backfill | Åtgärda befintliga överträdelser som A0 hittade. För orphan-rader: exportera dem först till `_orphans_backup_<datum>`, sedan beslut (ta bort eller peka om). Rabattkod som saknas sätts till NULL **efter** beslut med ekonomi. | Ja, om backup-tabellen finns kvar: återinför raderna. **Utan backup är radering inte backbar.** |
| A4 | Validate | `ALTER TABLE ... VALIDATE CONSTRAINT ...` (tar bara `SHARE UPDATE EXCLUSIVE`, blockerar inte skrivningar). | Ja, constraint blir kvar som NOT VALID om man vill, eller `DROP CONSTRAINT`. |
| A5 | Contract | Efter en release utan constraintfel: ta bort `_orphans_backup_*`. | **Nej** efter att backupen är borta. Gör bara efter godkännande. |

Förkontroll A0:

```sql
SELECT count(*) FROM order_lines l LEFT JOIN orders o ON o.id = l.order_id WHERE o.id IS NULL;
SELECT count(*) FROM orders o LEFT JOIN customers c ON c.id = o.customer_id WHERE c.id IS NULL;
SELECT o.id, o.discount_code FROM orders o
  LEFT JOIN discounts d ON d.code = o.discount_code
  WHERE o.discount_code IS NOT NULL AND d.code IS NULL;
SELECT code, percent FROM discounts WHERE percent NOT BETWEEN 0 AND 100;
```

Appen behöver inga ändringar för A, bortsett från att skrivningar som bryter en constraint nu ger fel (hanteras som `internal` tills de fångas specifikt).

## Del B: Persistera pris (`order_price_snapshots`)

| Steg | Fas | Åtgärd | Backa? |
|---|---|---|---|
| B1 | Expand | `CREATE TABLE order_price_snapshots (id BIGSERIAL PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), net NUMERIC(10,2) NOT NULL, vat NUMERIC(10,2) NOT NULL, total NUMERIC(10,2) NOT NULL, calculated_at TIMESTAMPTZ NOT NULL DEFAULT now())` och index på `(order_id, calculated_at DESC)`. Ingen app läser eller skriver tabellen än. | Ja, `DROP TABLE`. Ingen dataförlust (tabellen är tom). |
| B2 | Dual-write | `price_calc.py` skriver en snapshot-rad **utöver** filloggen i samma `calc_price`. Skrivfel i snapshot loggas men stoppar inte beräkningen (samma princip som `_logga`). Parametriserad SQL. | Ja, deploya föregående appversion. Redan skrivna snapshot-rader är harmlösa och kan ligga kvar eller tas bort. Ingen förlust i befintliga tabeller. |
| B3 | Backfill | Räkna om priset för historiska betalda/skickade ordrar med den **orörda** `calc_price` och skriv snapshots (markera med `calculated_at = orders.created_at` eller en flagga). Körs i batchar, idempotent (hoppa över order som har snapshot). Rabatter utan giltighetskontroll ger samma belopp som idag. | Ja, `DELETE FROM order_price_snapshots WHERE <backfill-markering>`. Ingen förlust i källdata. |
| B4 | Verifiera | Jämför för ett urval att senaste snapshot = live `calc_price` (karakteriseringstesterna är facit). Kör nattrapporten mot både gamla och nya källan. Avvikelse stoppar planen. | Inget att backa |
| B5 | Byt läsning | Nattrapporten läser summa från snapshots (med fallback till `calc_price` om snapshot saknas). API:t räknar fortfarande live. Bakom flagga/miljövariabel. | Ja, stäng av flaggan. |
| B6 | Contract | Ta bort filloggningen (`_logga`, `LOGG`, `price_calc.log`) när snapshots har varit stabila en hel månadsrapport. | Koden: ja via git revert. **Loggfilens historik: nej** om filen raderas, så arkivera den först. |
| B7 | Contract | Ta bort fallback-vägen i nattrapporten. | Ja via git revert. |

## Sammanfattning: vad kan backas utan dataförlust

- **Fullt bakbara utan förlust:** A1, A2, A4, B1, B2, B4, B5, B7.
- **Bakbara om en backup finns:** A3 (orphan-export), B3 (backfill-markering).
- **Inte bakbara efter genomförande:** A5 (radera backup) och radering av `price_calc.log` i B6. Båda kräver explicit godkännande och arkivering först.

Ett steg flyttas aldrig framåt förrän föregående steg har varit i drift utan problem under minst en release.

## Risker och öppna frågor (till ekonomi/ägare)

- Vad ska hända med ordrar vars rabattkod saknas i `discounts` (A3)? Beslut krävs, ändra inte tyst.
- `GAMMAL15` är utgången men ger rabatt på order 1045 idag. Backfill i B3 **bevarar** det beteendet; att börja kontrollera `valid_from`/`valid_to` är ett separat beslut och en egen migrering.
- Python-processen använder egen anslutning utanför `pg.Pool`. Snapshot-skrivningar i B2 ökar antalet skrivande anslutningar något. Följ upp anslutningsantal.
- Persondata: snapshots innehåller bara `order_id` och belopp, ingen kund-PII.
- Låsning: `CREATE INDEX CONCURRENTLY` får inte köras i en transaktion. `db/schema.sql` droppar och återskapar tabeller, så planen gäller en riktig databas, inte `db:reset`. `schema.sql` ska uppdateras först när sista expand-steget är godkänt.
