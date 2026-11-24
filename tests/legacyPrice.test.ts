import { execFile } from "node:child_process";
import { calcPrice } from "../src/pricing/legacyPrice";

jest.mock("node:child_process", () => ({ execFile: jest.fn() }));

const mockExec = execFile as unknown as jest.Mock;

function respond(error: (Error & { code?: number | string }) | null, stdout: string) {
  mockExec.mockImplementation((_cmd, _args, _opts, cb) => cb(error, stdout, ""));
}

function exitError(code: number | string) {
  return Object.assign(new Error("exit"), { code });
}

describe("calcPrice (brygga mot price_calc.py)", () => {
  it("ger pris vid exit 0 och giltig JSON", async () => {
    respond(null, '{"net":"950","vat":"237.5","total":"1187.5"}');
    expect(await calcPrice(1042)).toEqual({
      ok: true,
      value: { net: "950", vat: "237.5", total: "1187.5" },
    });
  });

  it("ger not_found vid exit 1 med payload finns inte", async () => {
    respond(exitError(1), '{"error": "finns inte"}');
    const r = await calcPrice(1);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.code).toBe("not_found");
  });

  it("ger internal vid exit 1 utan payload (Python-krasch)", async () => {
    respond(exitError(1), "");
    const r = await calcPrice(1);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.code).toBe("internal");
  });

  it("ger internal vid exit 2", async () => {
    respond(exitError(2), '{"error": "internt fel"}');
    const r = await calcPrice(1);
    if (!r.ok) expect(r.error.code).toBe("internal");
    expect(r.ok).toBe(false);
  });

  it("ger internal vid timeout/signal", async () => {
    respond(Object.assign(exitError("ETIMEDOUT"), { killed: true }), "");
    const r = await calcPrice(1);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.code).toBe("internal");
  });

  it("ger internal vid ogiltig JSON eller fel form", async () => {
    for (const out of ["inte json", '{"net":1}', "null"]) {
      respond(null, out);
      const r = await calcPrice(1);
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.error.code).toBe("internal");
    }
  });
});
