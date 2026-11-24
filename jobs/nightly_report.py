# nattlig rapport: summerar dagens betalda ordrar. körs av cron på driftservern.
import os, sys, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "legacy"))
from price_calc import calc_price, conn

dag = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
with conn.cursor() as cur:
    cur.execute("select id from orders where status = 'paid' and created_at::date = %s", (dag,))
    order_ids = [oid for (oid,) in cur.fetchall()]
summa = 0
antal = 0
try:
    for oid in order_ids:
        p = calc_price(oid)
        summa += p.total
        antal += 1
finally:
    conn.close()
print("%s: %d betalda ordrar, totalt %s kr" % (dag, antal, summa))
