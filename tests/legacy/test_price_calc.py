"""Karakteriseringstester for src/legacy/price_calc.py.

Testerna laser NUVARANDE beteende (golden master), inklusive kanda brister.
De kraver ingen Postgres: `psycopg` ersatts med en fake innan modulen
importeras (modulen oppnar annars en DB-anslutning vid import), och
`price_calc.conn` byts mot en fake-anslutning.

Ett test som blir rott betyder att beteendet har andrats. Andra INTE
forventade varden utan explicit beslut (se CLAUDE.md om _kapa).
"""
import importlib.util
import json
import os
import re
import sys
import types
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULE_PATH = os.path.join(ROOT, "src", "legacy", "price_calc.py")


class FakeCursor:
    """Tolkar de tre SQL-fragorna i price_calc.calc_price mot minnesdata."""

    def __init__(self, db):
        self.db = db
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        self.db.closed_cursors += 1

    def execute(self, sql, params=None):
        self.db.executed.append((sql, params))
        p = params or ()
        if sql == "select discount_code from orders where id = %s":
            oid = int(p[0])
            self._result = [(self.db.orders[oid],)] if oid in self.db.orders else None
            return
        if sql == "select quantity, unit_price from order_lines where order_id = %s":
            self._result = list(self.db.lines.get(int(p[0]), []))
            return
        if sql == "select percent from discounts where code = %s":
            pct = self.db.discounts.get(p[0])
            self._result = [] if pct is None else [(pct,)]
            return
        raise AssertionError("Oväntad SQL: %r" % sql)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class FakeConn:
    def __init__(self):
        self.orders = {}      # id -> discount_code (eller None)
        self.lines = {}       # id -> [(quantity, Decimal unit_price)]
        self.discounts = {}   # kod -> percent (heltal). Giltighetsdatum finns inte har.
        self.executed = []
        self.closed_cursors = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def _load_module():
    fake_psycopg = types.ModuleType("psycopg")
    fake_psycopg.connect = lambda *a, **k: FakeConn()
    saved = sys.modules.get("psycopg")
    sys.modules["psycopg"] = fake_psycopg
    try:
        spec = importlib.util.spec_from_file_location("price_calc_under_test", MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = saved
    return mod


@pytest.fixture
def pc(tmp_path, monkeypatch):
    mod = _load_module()
    mod.conn = FakeConn()
    # Loggen ska inte skrivas i src/ under test.
    monkeypatch.setattr(mod, "LOGG", str(tmp_path / "price_calc.log"))
    return mod


def D(s):
    return Decimal(s)


def add_order(pc, oid, lines, code=None):
    pc.conn.orders[oid] = code
    pc.conn.lines[oid] = [(q, D(p)) for q, p in lines]


# ---------------------------------------------------------------- _kapa

def test_kapa_trunkerar_mot_noll_och_avrundar_inte(pc):
    # 44.9775 hade avrundats till 44.98, men trunkeras till 44.97.
    assert pc._kapa(D("44.9775")) == D("44.97")
    assert pc._kapa(D("0.999")) == D("0.99")
    assert pc._kapa(D("137.9125")) == D("137.91")
    # Trunkering mot noll (int()), inte golv, for negativa varden.
    assert pc._kapa(D("-1.999")) == D("-1.99")


def test_kapa_normaliserar_inte_till_tva_decimaler(pc):
    # Format-brist: Decimal(int)/100 behaller inte avslutande nollor.
    assert str(pc._kapa(D("950.00"))) == "950"
    assert str(pc._kapa(D("237.50"))) == "237.5"
    assert str(pc._kapa(D("179.91"))) == "179.91"


def test_kapa_med_float_ger_fel_pa_grund_av_binar_representation(pc):
    # Dokumenterar latent bugg: float 0.29 * 100 = 28.999999999999996 -> 0.28.
    # Dagens flode skickar bara Decimal, men _kapa skyddar inte mot float.
    assert pc._kapa(0.29) == D("0.28")
    assert pc._kapa(D("0.29")) == D("0.29")


# ------------------------------------------------------------ calc_price

def test_order_utan_rabatt_ger_icke_normaliserade_strangar(pc):
    # Motsvarar order 1042: netto 950.00 -> "950" och "237.5" (bryter mot standarden).
    add_order(pc, 1042, [(2, "300.00"), (1, "350.00")])
    p = pc.calc_price(1042)
    assert (str(p.net), str(p.vat), str(p.total)) == ("950", "237.5", "1187.5")


def test_moms_trunkeras_44_97_inte_44_98(pc):
    # Order 1044: 199.90 med VAR10 -> 179.91; moms 44.9775 -> 44.97.
    add_order(pc, 1044, [(1, "199.90")], code="VAR10")
    pc.conn.discounts["VAR10"] = 10
    p = pc.calc_price(1044)
    assert str(p.net) == "179.91"
    assert str(p.vat) == "44.97"
    assert str(p.total) == "224.88"


def test_rabatt_dras_utan_avrundning_och_trunkeras_forst_i_net(pc):
    # Order 1045: 649.00 * 0.85 = 551.65; moms 137.9125 -> 137.91.
    add_order(pc, 1045, [(1, "649.00")], code="GAMMAL15")
    pc.conn.discounts["GAMMAL15"] = 15
    p = pc.calc_price(1045)
    assert (str(p.net), str(p.vat), str(p.total)) == ("551.65", "137.91", "689.56")


def test_rabatt_20_procent_ger_icke_normaliserade_strangar(pc):
    # Order 1041: 736.00 - 20 % = 588.80 -> "588.8", "147.2", "736.0".
    add_order(pc, 1041, [(1, "736.00")], code="SOMMAR20")
    pc.conn.discounts["SOMMAR20"] = 20
    p = pc.calc_price(1041)
    assert (str(p.net), str(p.vat), str(p.total)) == ("588.8", "147.2", "736.0")


def test_utgangen_rabattkod_ignoreras_inte_giltighet_lases_aldrig(pc):
    # BUGG/lucka (codemap 7.1): GAMMAL15 ar utgangen (2024) men ger anda 15 %.
    # Legacykoden fragar aldrig efter valid_from/valid_to.
    add_order(pc, 1045, [(1, "100.00")], code="GAMMAL15")
    pc.conn.discounts["GAMMAL15"] = 15
    assert str(pc.calc_price(1045).net) == "85"
    assert not any("valid_" in s for s, _ in pc.conn.executed)


def test_okand_rabattkod_ger_tyst_ingen_rabatt(pc):
    add_order(pc, 1050, [(1, "100.00")], code="FINNSEJ")
    p = pc.calc_price(1050)
    assert (str(p.net), str(p.vat), str(p.total)) == ("100", "25", "125")


def test_tom_rabattkod_slar_inte_upp_rabatt(pc):
    add_order(pc, 1051, [(1, "100.00")], code="")
    pc.calc_price(1051)
    assert not any("from discounts" in s for s, _ in pc.conn.executed)


def test_saknad_order_ger_none(pc):
    assert pc.calc_price(999999) is None


def test_saknad_order_loggas_inte(pc):
    pc.calc_price(999999)
    assert not os.path.exists(pc.LOGG)


def test_order_utan_orderrader_ger_noll_utan_fel(pc):
    add_order(pc, 1046, [])
    p = pc.calc_price(1046)
    assert (str(p.net), str(p.vat), str(p.total)) == ("0", "0", "0")


def test_tom_order_med_rabatt_ger_fortfarande_noll(pc):
    add_order(pc, 1047, [], code="VAR10")
    pc.conn.discounts["VAR10"] = 10
    assert str(pc.calc_price(1047).total) == "0"


def test_radsumma_ar_antal_gange_styckpris_over_flera_rader(pc):
    add_order(pc, 1060, [(3, "19.99"), (2, "0.05")])
    p = pc.calc_price(1060)
    # 59.97 + 0.10 = 60.07; moms 15.0175 -> 15.01
    assert (str(p.net), str(p.vat), str(p.total)) == ("60.07", "15.01", "75.08")


def test_moms_raknas_pa_redan_trunkerat_netto(pc):
    # Netto 0.019 * 100 -> 0.01; moms pa 0.01 = 0.0025 -> 0.00; total 0.01.
    add_order(pc, 1061, [(1, "0.019")])
    p = pc.calc_price(1061)
    assert (str(p.net), str(p.vat)) == ("0.01", "0")


def test_total_ar_net_plus_vat_utan_ytterligare_avrundning(pc):
    add_order(pc, 1062, [(1, "10.07")])
    p = pc.calc_price(1062)
    assert p.total == p.net + p.vat
    assert (str(p.net), str(p.vat), str(p.total)) == ("10.07", "2.51", "12.58")


def test_resultat_ar_decimal_inte_float(pc):
    add_order(pc, 1063, [(1, "1.10")])
    p = pc.calc_price(1063)
    assert all(isinstance(v, Decimal) for v in (p.net, p.vat, p.total))


def test_apostrof_i_rabattkod_skickas_som_parameter_inte_i_sql(pc):
    # Refaktorerat (steg 1): tidigare SQL-injektionsbrist (codemap 8 #1) ar atgardad.
    add_order(pc, 1070, [(1, "100.00")], code="x' OR '1'='1")
    p = pc.calc_price(1070)
    sql, params = pc.conn.executed[-1]
    assert sql == "select percent from discounts where code = %s"
    assert params == ("x' OR '1'='1",)
    assert str(p.net) == "100"


def test_sql_ar_parametriserad(pc):
    add_order(pc, 1071, [(1, "1.00")], code="VAR10")
    pc.calc_price(1071)
    assert pc.conn.executed == [
        ("select discount_code from orders where id = %s", (1071,)),
        ("select quantity, unit_price from order_lines where order_id = %s", (1071,)),
        ("select percent from discounts where code = %s", ("VAR10",)),
    ]


def test_cursor_stangs_efter_berakning_och_vid_saknad_order(pc):
    add_order(pc, 1072, [(1, "1.00")])
    pc.calc_price(1072)
    pc.calc_price(9999)
    assert pc.conn.closed_cursors == 2


# --------------------------------------------------------------- loggning

def test_loggrad_innehaller_tid_orderid_och_total_utan_normalisering(pc):
    add_order(pc, 1042, [(1, "950.00")])
    pc.calc_price(1042)
    with open(pc.LOGG) as f:
        rader = f.read().splitlines()
    assert len(rader) == 1
    tid, oid, total = rader[0].split(" ")
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", tid)
    assert (oid, total) == ("1042", "1187.5")


def test_varje_berakning_appendar_en_loggrad(pc):
    add_order(pc, 1042, [(1, "950.00")])
    pc.calc_price(1042)
    pc.calc_price(1042)
    with open(pc.LOGG) as f:
        assert len(f.read().splitlines()) == 2


def test_loggfel_sluks_tyst_och_beraknat_pris_returneras(pc, tmp_path, monkeypatch):
    # Bar except: pass. Loggsokvag i en katalog som inte finns -> OSError, sluks.
    monkeypatch.setattr(pc, "LOGG", str(tmp_path / "saknas" / "x.log"))
    add_order(pc, 1042, [(1, "950.00")])
    p = pc.calc_price(1042)
    assert str(p.total) == "1187.5"


def test_moms_ar_hardkodad_25_procent(pc):
    assert pc.MOMS == 25


# -------------------------------------------------------------------- CLI

def test_cli_skriver_json_med_strangar_och_exit_0(pc, monkeypatch, capsys):
    add_order(pc, 1042, [(1, "950.00")])
    monkeypatch.setattr(sys, "argv", ["price_calc.py", "1042"])
    src = open(MODULE_PATH, encoding="utf-8").read()
    main_block = src.split('if __name__ == "__main__":')[1]
    body = "\n".join(l[4:] if l.startswith("    ") else l for l in main_block.splitlines())
    ns = dict(pc.__dict__, __name__="__main__")
    exec(body, ns)
    out = json.loads(capsys.readouterr().out)
    assert out == {"net": "950", "vat": "237.5", "total": "1187.5"}


def test_cli_saknad_order_ger_json_fel_och_exit_1(pc, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["price_calc.py", "999999"])
    src = open(MODULE_PATH, encoding="utf-8").read()
    main_block = src.split('if __name__ == "__main__":')[1]
    body = "\n".join(l[4:] if l.startswith("    ") else l for l in main_block.splitlines())
    ns = dict(pc.__dict__, __name__="__main__")
    with pytest.raises(SystemExit) as e:
        exec(body, ns)
    assert e.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"error": "finns inte"}


# ------------------------------------------- steg 2: ren logik utan DB

def test_berakna_pris_ar_ren_och_ger_samma_trunkering(pc):
    p = pc.berakna_pris([(1, D("199.90"))], 10)
    assert (str(p.net), str(p.vat), str(p.total)) == ("179.91", "44.97", "224.88")


def test_berakna_pris_utan_rabatt_och_utan_rader(pc):
    p = pc.berakna_pris([], None)
    assert (str(p.net), str(p.vat), str(p.total)) == ("0", "0", "0")
