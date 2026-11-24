# price_calc.py
# prisberakning for ordrar. skriven 2019, flyttad hit fran gamla admin-systemet.
# OBS rör inte avrundningen, ekonomi har stämt av mot den.

import os, sys, json, datetime
from decimal import Decimal
import psycopg

DB = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/butik")
conn = psycopg.connect(DB, autocommit=True)

MOMS = 25
LOGG = os.path.join(os.path.dirname(__file__), "price_calc.log")


class Pris:
    def __init__(self, net, vat, total):
        self.net = net
        self.vat = vat
        self.total = total


def _kapa(x):
    # två decimaler
    return Decimal(int(x * 100)) / 100


# --- databasatkomst (inga berakningar) -------------------------------------

def hamta_order(cur, order_id):
    """Returnerar (rabattkod, [(antal, styckpris), ...]) eller None om ordern saknas."""
    cur.execute("select discount_code from orders where id = %s", (order_id,))
    rad = cur.fetchone()
    if rad is None:
        return None
    cur.execute("select quantity, unit_price from order_lines where order_id = %s", (order_id,))
    return rad[0], cur.fetchall()


def hamta_rabatt_procent(cur, kod):
    """Returnerar rabatt i procent for koden, eller None om den saknas."""
    cur.execute("select percent from discounts where code = %s", (kod,))
    r = cur.fetchone()
    return r[0] if r else None


# --- ren prisberakning (ingen I/O) ------------------------------------------

def berakna_pris(rader, rabatt_procent):
    summa = Decimal(0)
    for q, p in rader:
        summa = summa + q * p
    if rabatt_procent is not None:
        summa = summa - summa * rabatt_procent / 100
    net = _kapa(summa)
    vat = _kapa(net * MOMS / 100)
    return Pris(net, vat, net + vat)


# --- loggning ----------------------------------------------------------------

def _logga(order_id, total):
    try:
        with open(LOGG, "a", encoding="utf-8") as f:
            f.write("%s %s %s\n" % (datetime.datetime.now().isoformat(), order_id, total))
    except OSError:
        # Loggfel far inte stoppa prisberakningen.
        pass


def calc_price(order_id):
    with conn.cursor() as cur:
        order = hamta_order(cur, order_id)
        if order is None:
            return None
        kod, rader = order
        rabatt = hamta_rabatt_procent(cur, kod) if kod else None

    pris = berakna_pris(rader, rabatt)
    _logga(order_id, pris.total)
    return pris


if __name__ == "__main__":
    try:
        p = calc_price(int(sys.argv[1]))
    finally:
        conn.close()
    if p is None:
        print(json.dumps({"error": "finns inte"}))
        sys.exit(1)
    print(json.dumps({"net": str(p.net), "vat": str(p.vat), "total": str(p.total)}))
