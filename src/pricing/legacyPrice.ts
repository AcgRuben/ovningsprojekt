import { execFile, ExecFileException } from "node:child_process";
import path from "node:path";
import { Result, ok, err } from "../result";

export type Price = { net: string; vat: string; total: string };

const SCRIPT = path.join(__dirname, "..", "legacy", "price_calc.py");
const PYTHON = process.env.PYTHON_BIN ?? "python3";
const TIMEOUT_MS = 10_000;

// Kontrakt mot price_calc.py (CLI):
//   exit 0 + stdout {"net","vat","total"}  -> pris
//   exit 1 + stdout {"error":"finns inte"} -> ordern finns inte (not_found)
//   övrigt (exit 1 utan payload, exit 2, timeout, ogiltig JSON) -> internal
function isPrice(v: unknown): v is Price {
  if (typeof v !== "object" || v === null) return false;
  const p = v as Record<string, unknown>;
  return typeof p.net === "string" && typeof p.vat === "string" && typeof p.total === "string";
}

// Python avslutar med exit 1 även vid ohanterade undantag, så exit 1 räcker inte:
// payloaden måste också vara {"error":"finns inte"}.
function isNotFound(stdout: string): boolean {
  try {
    const v: unknown = JSON.parse(stdout);
    return typeof v === "object" && v !== null && (v as { error?: unknown }).error === "finns inte";
  } catch {
    return false;
  }
}

// Brygga till den äldre prisberäkningen i Python. Allt pris räknas fortfarande där.
export function calcPrice(orderId: number): Promise<Result<Price>> {
  return new Promise((resolve) => {
    execFile(
      PYTHON,
      [SCRIPT, String(orderId)],
      { env: process.env, timeout: TIMEOUT_MS },
      (error, stdout) => {
        if (error) {
          if ((error as ExecFileException).code === 1 && isNotFound(stdout)) {
            resolve(err("not_found", `Beställning ${orderId} finns inte.`));
          } else {
            resolve(err("internal", `Pris för beställning ${orderId} kunde inte räknas.`));
          }
          return;
        }
        try {
          const parsed: unknown = JSON.parse(stdout);
          if (isPrice(parsed)) {
            resolve(ok(parsed));
            return;
          }
        } catch {
          // faller igenom till internal
        }
        resolve(err("internal", `Ogiltigt svar från prismodulen för beställning ${orderId}.`));
      },
    );
  });
}
