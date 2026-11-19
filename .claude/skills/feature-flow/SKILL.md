---
name: feature-flow
description: Driver en user story från krav till granskad kod och lämnar en artefaktfil per fas.
---

Genomför arbetet i exakt fem faser. Varje fas måste lämna en fil i repot:

1. **Research (`docs/work/01-research.md`)**: Anropa `researcher` för att kartlägga user storyn mot `db/`, `src/` och `docs/api.md`.
2. **Plan & ADR (`docs/work/02-plan.md` + `docs/adr/`)**: Skriv Givet/När/Så-acceptanskriterier, API-kontrakt (endpoint, statuskoder, felformat) och skapa en ADR för viktigaste designbeslutet.
3. **Bygg med tester först**: Kör `/tdd` för att implementera testerna först och därefter koden. Uppdatera `docs/api.md`.
4. **Granska (`docs/work/03-review.md`)**: Anropa `code-reviewer` och spara granskningsrapporten. Åtgärda eventuella anmärkningar.
5. **Verifiera & Logga**: Kör `npm test && npm run lint && npm run typecheck`, gör små spårbara commits och avsluta med `session-scribe`.
