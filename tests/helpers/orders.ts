import { db } from "../../src/db";

export interface OrderRow {
  id: number;
  customerId: number;
  status: string;
  createdAtMs: number;
}

// Flyttar orderns created_at så att ordern är `seconds` sekunder gammal enligt databasens now().
export async function setOrderAge(orderId: number, seconds: number): Promise<void> {
  await db.query("UPDATE orders SET created_at = now() - make_interval(secs => $2) WHERE id = $1", [
    orderId,
    seconds,
  ]);
}

export async function setOrderStatus(orderId: number, status: string): Promise<void> {
  await db.query("UPDATE orders SET status = $2 WHERE id = $1", [orderId, status]);
}

// Läser orderraden direkt från databasen (för att verifiera att den är oförändrad eller ändrad).
export async function getOrderRow(orderId: number): Promise<OrderRow> {
  const result = await db.query(
    `SELECT id, customer_id AS "customerId", status,
            (extract(epoch FROM created_at) * 1000)::float8 AS "createdAtMs"
       FROM orders WHERE id = $1`,
    [orderId],
  );
  return result.rows[0] as OrderRow;
}
