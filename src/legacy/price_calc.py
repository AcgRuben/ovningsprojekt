# price_calc.py
# prisberakning for ordrar. skriven 2019, flyttad hit fran gamla admin-systemet.
# OBS rör inte avrundningen, ekonomi har stämt av mot den.

from __future__ import annotations

import os, sys, json, datetime
from decimal import Decimal
from typing import Any, Optional, Sequence

import psycopg

DB = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/butik")
conn = psycopg.connect(DB, autocommit=True)

MOMS = 25
LOGG = os.path.join(os.path.dirname(__file__), "price_calc.log")


class Pris:
    net: Decimal
    vat: Decimal
    total: Decimal

    def __init__(self, net: Decimal, vat: Decimal, total: Decimal) -> None:
        self.net = net
        self.vat = vat
        self.total = total


def _kapa(x: Decimal) -> Decimal:
    # två decimaler
    return Decimal(int(x * 100)) / 100


# --- databasatkomst (inga berakningar) -------------------------------------

def hamta_order(cur: Any, order_id: int) -> Optional[tuple[Optional[str], list[tuple[int, Decimal]]]]:
    """Returnerar (rabattkod, [(antal, styckpris), ...]) eller None om ordern saknas."""
    cur.execute("select discount_code from orders where id = %s", (order_id,))
    rad = cur.fetchone()
    if rad is None:
        return None
    cur.execute("select quantity, unit_price from order_lines where order_id = %s", (order_id,))
    return rad[0], cur.fetchall()


def hamta_rabatt_procent(cur: Any, kod: str) -> Optional[int]:
    """Returnerar rabatt i procent for koden, eller None om den saknas."""
    cur.execute("select percent from discounts where code = %s", (kod,))
    r = cur.fetchone()
    return r[0] if r else None


# --- ren prisberakning (ingen I/O) ------------------------------------------

def berakna_pris(rader: Sequence[tuple[int, Decimal]], rabatt_procent: Optional[int]) -> Pris:
    summa = Decimal(0)
    for q, p in rader:
        summa = summa + q * p
    if rabatt_procent is not None:
        summa = summa - summa * rabatt_procent / 100
    net = _kapa(summa)
    vat = _kapa(net * MOMS / 100)
    return Pris(net, vat, net + vat)


# --- loggning ----------------------------------------------------------------

def _logga(order_id: int, total: Decimal) -> None:
    try:
        with open(LOGG, "a", encoding="utf-8") as f:
            f.write("%s %s %s\n" % (datetime.datetime.now().isoformat(), order_id, total))
    except OSError:
        # Loggfel far inte stoppa prisberakningen.
        pass


def calc_price(order_id: int) -> Optional[Pris]:
    """Returnerar Pris, eller None om ordern saknas. Kastar vid DB-fel."""
    with conn.cursor() as cur:
        order = hamta_order(cur, order_id)
        if order is None:
            return None
        kod, rader = order
        rabatt = hamta_rabatt_procent(cur, kod) if kod else None

    pris = berakna_pris(rader, rabatt)
    _logga(order_id, pris.total)
    return pris


def main(argv: Sequence[str]) -> int:
    """CLI-kontrakt mot legacyPrice.ts: 0=pris, 1=order saknas, 2=ogiltig indata/internt fel."""
    try:
        order_id = int(argv[1])
    except (IndexError, ValueError):
        conn.close()
        print(json.dumps({"error": "ogiltigt order-id"}))
        return 2
    try:
        p = calc_price(order_id)
    except Exception as e:  # DB-fel m.m. -> internt fel, ingen stacktrace pa stdout
        print(type(e).__name__, file=sys.stderr)  # bara klassnamn, inget som kan vara PII
        print(json.dumps({"error": "internt fel"}))
        return 2
    finally:
        conn.close()
    if p is None:
        print(json.dumps({"error": "finns inte"}))
        return 1
    print(json.dumps({"net": str(p.net), "vat": str(p.vat), "total": str(p.total)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
