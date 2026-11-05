#!/usr/bin/env python3
"""Reproduit l'indicateur « Alerte Altcoin » (SMA 9 / SMA 20 en bougies 3D) pour plusieurs cryptos
et écrit data/signals.json.
Règle : ENTRÉE si clôture > SMA 9 > SMA 20 ; SORTIE si clôture < SMA 20 (sur bougies 3D).
Données : bougies journalières Kraken (API publique, ~2 ans), ou Coinbase si la crypto n'est pas cotée sur Kraken,
regroupées par 3 jours."""
import json, os, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

# ───── À MODIFIER SI BESOIN : la liste des cryptos suivies (cotées en USD sur Kraken ou Coinbase) ─────
COINS = ["BTC", "ETH", "LINK", "SOL", "AAVE", "SUI", "ONDO", "UNI", "RENDER", "INJ", "AVAX", "TAO", "MORPHO",
         "ENA", "PUMP", "HYPE", "ZEC", "NEAR", "ADA", "XRP", "CRV", "DOGE", "SYRUP", "GEO", "BNB", "FET", "ASTER"]
# ────────────────────────────────────────────────────────────────────────────────────────
KRAKEN_NAMES = {"BTC": "XBT", "DOGE": "XDG"}   # noms particuliers chez Kraken
FAST, SLOW = 9, 20
# Bougies 3D : une bougie commence un jour dont le numéro depuis le 01/01/1970 est un multiple de 3 + DECALAGE.
# DECALAGE = 0 correspond à une clôture à 00:00 UTC le 06/11/2026 (cohérent avec le compte à rebours TradingView).
DECALAGE = 0
DAY = 86400


def get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "crypto-dashboard", "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(20)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(10)
    raise RuntimeError("échec réseau")


def fetch_kraken(sym):
    pair = KRAKEN_NAMES.get(sym, sym) + "USD"
    j = get("https://api.kraken.com/0/public/OHLC?" + urllib.parse.urlencode({"pair": pair, "interval": 1440}))
    if j.get("error"):
        raise RuntimeError(", ".join(j["error"]))
    key = next(k for k in j["result"] if k != "last")
    return pair, [(int(r[0]), float(r[4])) for r in j["result"][key]]   # (début du jour UTC, clôture)


def fetch_coinbase(sym):
    """Secours : API publique Coinbase Exchange, 300 jours par appel, 3 appels."""
    pair, end, rows = f"{sym}-USD", int(time.time()), {}
    fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(3):
        start = end - 299 * DAY
        q = urllib.parse.urlencode({"granularity": 86400, "start": fmt(start), "end": fmt(end)})
        j = get(f"https://api.exchange.coinbase.com/products/{pair}/candles?{q}")
        if not j:
            break
        for r in j:
            rows[int(r[0])] = float(r[4])      # [heure, bas, haut, ouverture, clôture, volume]
        end = start - DAY
        time.sleep(0.4)
    if not rows:
        raise RuntimeError("aucune donnée")
    return pair, sorted(rows.items())


def fetch_daily(sym):
    """Kraken d'abord, Coinbase ensuite. Retourne (paire, source, bougies journalières)."""
    errors = []
    for name, fn in (("Kraken", fetch_kraken), ("Coinbase", fetch_coinbase)):
        try:
            pair, daily = fn(sym)
            if daily:
                return pair, name, daily
        except Exception as e:
            errors.append(f"{name} : {str(e)[:40]}")
    raise RuntimeError("non coté sur Kraken ni Coinbase (" + " ; ".join(errors) + ")")


def to_3d(daily, now_ts):
    """Regroupe les bougies journalières en bougies 3D. Retourne (liste de (début, clôture), en_cours)."""
    groups = {}
    for ts, close in daily:
        groups.setdefault((ts // DAY - DECALAGE) // 3, []).append((ts, close))
    keys = sorted(groups)
    candles = []
    for n, k in enumerate(keys):
        g = groups[k]
        if n == 0 and len(g) < 3 and len(keys) > 1:
            continue                       # première bougie incomplète : ignorée
        candles.append((k * 3 * DAY + DECALAGE * DAY, g[-1][1]))
    live = bool(candles) and now_ts < candles[-1][0] + 3 * DAY
    return candles, live


def sma(v, n, i):
    return sum(v[i - n + 1:i + 1]) / n


def simulate(closes):
    inm, entry, entry_i, trades, sig = False, None, None, [], []
    for i in range(SLOW - 1, len(closes)):
        c, f, s = closes[i], sma(closes, FAST, i), sma(closes, SLOW, i)
        if not inm and c > f > s:
            inm, entry, entry_i = True, c, i
            sig.append(("BUY", i))
        elif inm and c < s:
            inm = False
            trades.append((c / entry - 1) * 100)
            sig.append(("SELL", i))
    return {"in": inm, "entry": entry, "entry_i": entry_i, "trades": trades, "signals": sig}


def state_of(sim, n_bars):
    if n_bars < SLOW + 10 or not sim["signals"]:
        return "UNKNOWN"
    return "IN" if sim["in"] else "OUT"


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def analyse(sym, pair, daily, now_ts, source=""):
    candles, live = to_3d(daily, now_ts)
    closes = [c for _, c in candles]
    if len(closes) < SLOW:
        return {"sym": sym, "pair": pair, "error": "historique insuffisant"}
    sim = simulate(closes)
    conf = simulate(closes[:-1]) if live else sim
    state = state_of(sim, len(closes))
    confirmed = state_of(conf, len(closes) - (1 if live else 0))
    last = sim["signals"][-1] if sim["signals"] else None
    eq = 1.0
    for t in sim["trades"]:
        eq *= 1 + t / 100
    wins = sum(1 for t in sim["trades"] if t > 0)
    price, i = closes[-1], len(closes) - 1
    out = {"sym": sym, "pair": pair, "source": source, "state": state, "confirmed": confirmed, "pending": state != confirmed,
           "price": price, "sma9": sma(closes, FAST, i), "sma20": sma(closes, SLOW, i),
           "distSma20": (price / sma(closes, SLOW, i) - 1) * 100,
           "lastSignal": {"type": last[0], "bar": iso(candles[last[1]][0])} if last else None,
           "entryPrice": sim["entry"] if sim["in"] else None,
           "entryBar": iso(candles[sim["entry_i"]][0]) if sim["in"] else None,
           "perfSinceEntry": (price / sim["entry"] - 1) * 100 if sim["in"] else None,
           "trades": len(sim["trades"]), "winRate": wins / len(sim["trades"]) * 100 if sim["trades"] else None,
           "stratPerf": (eq - 1) * 100, "buyHold": (price / closes[0] - 1) * 100, "bars": len(closes),
           "from": iso(candles[0][0])}
    return out


def main():
    now = int(datetime.now(timezone.utc).timestamp())
    coins = []
    for sym in COINS:
        try:
            pair, source, daily = fetch_daily(sym)
            coins.append(analyse(sym, pair, daily, now, source))
            c = coins[-1]
            print(f"{sym:7} {source:9} {c.get('state', c.get('error'))}")
        except Exception as e:
            print(f"{sym:5} indisponible : {e}")
            coins.append({"sym": sym, "error": str(e)[:120]})
        time.sleep(1.5)
    cur = (now // DAY - DECALAGE) // 3
    end = (cur + 1) * 3 * DAY + DECALAGE * DAY
    result = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "rule": "Entrée : clôture > SMA 9 > SMA 20 ; sortie : clôture < SMA 20 (bougies 3D)",
              "source": "Kraken, ou Coinbase si absent de Kraken (bougies journalières regroupées par 3 jours)",
              "candleEnd": datetime.fromtimestamp(end, timezone.utc).isoformat(timespec="seconds"),
              "coins": coins}
    os.makedirs("data", exist_ok=True)
    with open("data/signals.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print("OK : data/signals.json écrit")


if __name__ == "__main__":
    main()
