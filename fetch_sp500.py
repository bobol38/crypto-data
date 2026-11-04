#!/usr/bin/env python3
"""Récupère le cours du S&P 500 (différé) et écrit data/sp500.json.
Source principale : Yahoo Finance (non officielle, sans clé). Secours : Stooq (clôture)."""
import csv, io, json, os, time, urllib.request, urllib.error
from datetime import datetime, timezone

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1m&range=1d"
STOOQ = "https://stooq.com/q/d/l/?s=%5Espx&i=d"
UA = "Mozilla/5.0 (compatible; crypto-dashboard)"


def http(url):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            last = e
            time.sleep(5)
    raise RuntimeError(last)


def parse_yahoo(text):
    r = json.loads(text)["chart"]["result"][0]
    m = r["meta"]
    price = float(m["regularMarketPrice"])
    prev = float(m.get("chartPreviousClose") or m.get("previousClose"))
    t = int(m["regularMarketTime"])
    reg = m.get("currentTradingPeriod", {}).get("regular", {})
    now = int(datetime.now(timezone.utc).timestamp())
    is_open = bool(reg) and reg.get("start", 0) <= now <= reg.get("end", 0) and now - t < 1800
    return {"price": price, "prevClose": prev, "changePct": (price / prev - 1) * 100,
            "open": is_open, "asOf": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds"),
            "source": "Yahoo Finance (différé)"}


def parse_stooq(text):
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("Close")]
    last, prev = rows[-1], rows[-2]
    price, pc = float(last["Close"]), float(prev["Close"])
    return {"price": price, "prevClose": pc, "changePct": (price / pc - 1) * 100,
            "open": False, "asOf": last["Date"] + "T21:00:00+00:00", "source": "Stooq (clôture)"}


def main():
    data = None
    for name, url, parser in (("Yahoo", YAHOO, parse_yahoo), ("Stooq", STOOQ, parse_stooq)):
        try:
            data = parser(http(url))
            print(f"OK via {name} : {data['price']:.2f} ({data['changePct']:+.2f} %)")
            break
        except Exception as e:
            print(f"  {name} indisponible : {e}")
    if not data:
        raise SystemExit("Aucune source disponible, rien n'est écrit.")
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs("data", exist_ok=True)
    with open("data/sp500.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
