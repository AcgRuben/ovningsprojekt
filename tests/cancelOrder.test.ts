import request from "supertest";
import { createApp } from "../src/app";
import { closeDb, resetDb } from "./helpers/db";
import { getOrderRow, setOrderAge, setOrderStatus } from "./helpers/orders";

const app = createApp();

// Seed: order 1043 tillhör kund 3 (new), 1042 tillhör kund 1, 1047 tillhör kund 2.
const OWN_ORDER = 1043;
const OWNER = "3";
const OTHER_CUSTOMER = "2";

const MIN = 60;

// customerId = null skickar anropet utan X-Customer-Id (undefined skulle ge standardvärdet).
function cancel(id: number | string, customerId: string | null = OWNER) {
  const req = request(app).post(`/orders/${id}/cancel`);
  return customerId === null ? req : req.set("X-Customer-Id", customerId);
}

// Gör ordern till en färsk, avbrytbar order med given ålder i sekunder.
async function prepare(orderId: number, status: string, ageSeconds: number): Promise<void> {
  await setOrderStatus(orderId, status);
  await setOrderAge(orderId, ageSeconds);
}

beforeEach(resetDb);
afterAll(closeDb);

describe("POST /orders/:id/cancel", () => {
  it("AK1: avbryter en egen new-order som är 10 minuter gammal", async () => {
    await prepare(OWN_ORDER, "new", 10 * MIN);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(200);
    expect(res.body.id).toBe(OWN_ORDER);
    expect(res.body.status).toBe("cancelled");
    expect(typeof res.body.createdAt).toBe("string");
    expect(Number.isNaN(Date.parse(res.body.createdAt))).toBe(false);
    expect((await getOrderRow(OWN_ORDER)).status).toBe("cancelled");
  });

  it("AK2: avbryter en order som är 29 minuter gammal", async () => {
    await prepare(OWN_ORDER, "new", 29 * MIN);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(200);
    expect((await getOrderRow(OWN_ORDER)).status).toBe("cancelled");
  });

  it("AK2: avbryter en order som är 29 min 59 s gammal (strax innanför gränsen)", async () => {
    await prepare(OWN_ORDER, "new", 29 * MIN + 59);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(200);
    expect(res.body.status).toBe("cancelled");
    expect((await getOrderRow(OWN_ORDER)).status).toBe("cancelled");
  });

  it("AK2/AK3: nekar en order som är 30 min 1 s gammal (strax utanför gränsen)", async () => {
    await prepare(OWN_ORDER, "new", 30 * MIN + 1);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe("conflict");
    expect((await getOrderRow(OWN_ORDER)).status).toBe("new");
  });

  it("AK3: nekar en order som är 31 minuter gammal med meddelande om utgången tid", async () => {
    await prepare(OWN_ORDER, "new", 31 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe("conflict");
    expect(res.body.error.message).toContain("30 minuter");
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
    expect(before.status).toBe("new");
  });

  it.each(["paid", "shipped"])("AK4: nekar en egen order med status %s", async (status) => {
    await prepare(OWN_ORDER, status, 10 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe("conflict");
    expect(res.body.error.message).toContain(status);
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
  });

  it("AK5: nekar en redan avbruten order med tydligt meddelande", async () => {
    await prepare(OWN_ORDER, "cancelled", 10 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER);

    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe("conflict");
    expect(res.body.error.message).toContain("redan avbruten");
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
  });

  it("AK6: första avbokningen ger 200 och den andra 409 (redan avbruten)", async () => {
    await prepare(OWN_ORDER, "new", 10 * MIN);

    const first = await cancel(OWN_ORDER);
    const second = await cancel(OWN_ORDER);

    expect(first.status).toBe(200);
    expect(second.status).toBe(409);
    expect(second.body.error.code).toBe("conflict");
    expect(second.body.error.message).toContain("redan avbruten");
    expect((await getOrderRow(OWN_ORDER)).status).toBe("cancelled");
  });

  it("AK7: vid två samtidiga anrop lyckas exakt ett", async () => {
    await prepare(OWN_ORDER, "new", 10 * MIN);

    const results = await Promise.all([cancel(OWN_ORDER), cancel(OWN_ORDER)]);

    const statuses = results.map((r) => r.status).sort();
    expect(statuses).toEqual([200, 409]);
    const loser = results.find((r) => r.status === 409);
    expect(loser?.body.error.code).toBe("conflict");
    expect((await getOrderRow(OWN_ORDER)).status).toBe("cancelled");
  });

  it("AK8: returnerar 403 för en annan kunds order och lämnar den oförändrad", async () => {
    await prepare(OWN_ORDER, "new", 10 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER, OTHER_CUSTOMER);

    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe("forbidden");
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
  });

  it("AK8: 403 går före 409 när en annan kunds order är för gammal", async () => {
    await prepare(OWN_ORDER, "new", 60 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER, OTHER_CUSTOMER);

    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe("forbidden");
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
  });

  it("AK8: 403 går före 409 när en annan kunds order har fel status", async () => {
    await prepare(OWN_ORDER, "shipped", 10 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER, OTHER_CUSTOMER);

    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe("forbidden");
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
  });

  it("AK9: returnerar 404 för en order som inte finns", async () => {
    const res = await cancel(9999);

    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe("not_found");
  });

  it.each(["abc", "0", "-1", "1.5"])("AK10: returnerar 400 för ogiltigt id %s", async (id) => {
    const res = await cancel(id);

    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("invalid_input");
  });

  it("AK11: returnerar 401 utan X-Customer-Id och lämnar ordern oförändrad", async () => {
    await prepare(OWN_ORDER, "new", 10 * MIN);
    const before = await getOrderRow(OWN_ORDER);

    const res = await cancel(OWN_ORDER, null);

    expect(res.status).toBe(401);
    expect(await getOrderRow(OWN_ORDER)).toEqual(before);
  });

  it("AK12: avbruten order syns som cancelled i GET /orders/:id och i kundens lista", async () => {
    await prepare(OWN_ORDER, "new", 10 * MIN);
    const cancelRes = await cancel(OWN_ORDER);
    expect(cancelRes.status).toBe(200);

    const single = await request(app).get(`/orders/${OWN_ORDER}`).set("X-Customer-Id", OWNER);
    expect(single.status).toBe(200);
    expect(single.body.status).toBe("cancelled");
    expect(typeof single.body.createdAt).toBe("string");

    const list = await request(app).get("/customers/me/orders").set("X-Customer-Id", OWNER);
    expect(list.status).toBe(200);
    const listed = list.body.find((o: { id: number }) => o.id === OWN_ORDER);
    expect(listed.status).toBe("cancelled");
  });
});

describe("createdAt på Order (AK13)", () => {
  it("GET /orders/:id innehåller createdAt som ISO 8601 och övriga fält oförändrade", async () => {
    const res = await request(app).get("/orders/1042").set("X-Customer-Id", "1");

    expect(res.status).toBe(200);
    expect(res.body.createdAt).toBe("2026-10-01T07:05:00.000Z");
    expect(res.body.id).toBe(1042);
    expect(res.body.customerId).toBe(1);
    expect(res.body.status).toBe("paid");
    expect(res.body.discountCode).toBeNull();
    expect(res.body.lines).toHaveLength(2);
  });

  it("POST /orders returnerar createdAt som ISO 8601 nära nuvarande tid", async () => {
    const beforeMs = Date.now();
    const res = await request(app)
      .post("/orders")
      .set("X-Customer-Id", "3")
      .send({ lines: [{ product: "Musmatta", quantity: 2, unitPrice: 200 }] });
    const afterMs = Date.now();

    expect(res.status).toBe(201);
    expect(typeof res.body.createdAt).toBe("string");
    expect(new Date(res.body.createdAt).toISOString()).toBe(res.body.createdAt);
    const createdMs = Date.parse(res.body.createdAt);
    expect(createdMs).toBeGreaterThan(beforeMs - 60_000);
    expect(createdMs).toBeLessThan(afterMs + 60_000);
    expect(res.body.status).toBe("new");
    expect(res.body.lines).toEqual([{ product: "Musmatta", quantity: 2, unitPrice: "200.00" }]);
  });
});
