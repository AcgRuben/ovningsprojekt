---
name: modernize-legacy
description: Moderniserar src/legacy/price_calc.py säkert med codemap, karakteriseringstester, små refaktoreringssteg och expand/contract-migreringsplan.
---

Följ dessa steg för säker modernisering av legacy-kod:

1. **Codemap (`docs/work/legacy-codemap.md`)**: Anropa `researcher` för att kartlägga `src/legacy/price_calc.py`, `src/pricing/legacyPrice.ts` och `jobs/nightly_report.py`.
2. **Karakteriseringstester**: Anropa `test-engineer` för att skriva minst 5 karakteriseringstester i Python som låser nuvarande beteende (inklusive trunkeringsavrundningen i `_kapa`). Kör `npm run test:legacy` tills allt är grönt.
3. **Minst 3 små refaktoreringssteg**:
   - Steg 1: Byt strängformaterad SQL mot parametriserade frågor + stäng cursors/anslutningar säkert. Kör `npm run test:legacy` och committa.
   - Steg 2: Separera databasåtkomst från ren prisberäkningslogik (och ersätt osäker filloggning). Kör `npm run test:legacy` och committa.
   - Steg 3: Lägg till typannoteringar och tydlig felhantering/kontrakt mot `legacyPrice.ts` och `nightly_report.py`. Kör `npm run test:legacy` och `npm test`, och committa.
4. **Migreringsplan (`docs/work/db-migration-plan.md`)**: Skriv en reversibel databas-migreringsplan i **expand/contract-steg** (inklusive vilka steg som kan backas utan dataförlust).
5. **Granskning & Logg**: Anropa `code-reviewer` och avsluta med `session-scribe`.
