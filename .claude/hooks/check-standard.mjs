import fs from "node:fs";
import process from "node:process";
import console from "node:console";

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const filePath = (input.tool_input?.file_path || "").replace(/\\/g, "/");

if (!filePath.endsWith(".ts") || !fs.existsSync(filePath)) process.exit(0);

const code = fs.readFileSync(filePath, "utf8");
const errors = [];

// 1. Tjänstelagret får inte kasta fel
if (filePath.includes("src/services/") && /\bthrow\s+new\s+Error/.test(code)) {
  errors.push(
    "REGELBROTT [Felhantering]: src/services/ får inte använda 'throw new Error'. Rätta genom att returnera ok(värde) eller err(kod, meddelande) från src/result.ts.",
  );
}

// 2. SQL får aldrig byggas med strängmallar (${...})
if (/(SELECT|INSERT|UPDATE|DELETE)\b[\s\S]{0,120}\$\{/i.test(code)) {
  errors.push(
    "REGELBROTT [Databas/SQL]: SQL byggs med stränginterpolering (${...}). Rätta genom att använda parametriserad SQL: db.query('... $1', [värde]).",
  );
}

// 3. Kund-ID får aldrig hämtas från body eller query
if (/req\.(body|query)\.customerId\b/.test(code)) {
  errors.push(
    "REGELBROTT [Behörighet]: customerId hämtas från req.body/req.query. Rätta genom att använda requireCustomer och req.customerId.",
  );
}

// 4. Inga flyttal för pengar
if (filePath.includes("pricing/") && /\bparseFloat\b/.test(code)) {
  errors.push(
    "REGELBROTT [Pengar]: parseFloat är förbjudet i prisberäkning. Rätta genom att använda heltal i ören eller Decimal/NUMERIC och strängar med två decimaler.",
  );
}

if (errors.length > 0) {
  console.error(errors.join("\n"));
  process.exit(2);
}
