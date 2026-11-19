---
name: tdd
description: Strikt Test-Driven Development (Red -> Green -> Refactor) utifrån acceptanskriterier.
---

Följ TDD-cykeln strikt utan att hoppa över något steg:

1. **RED**: Be subagenten `test-engineer` skriva automatiserade tester för acceptanskriterierna (lyckat fall + felkoder 400/401/403/404). Kör `npm test` och bekräfta att de nya testerna misslyckas.
2. **GREEN**: Skriv minsta möjliga produktionskod i `src/services/` (med `Result`) och `src/routes/` för att få alla tester gröna. Kör `npm test`, `npm run lint` och `npm run typecheck`.
3. **REFACTOR**: Städa upp koden så att den följer `docs/standard.md` perfekt utan att ändra beteende. Kör `npm test` igen och verifiera att alla tester förblir gröna.
