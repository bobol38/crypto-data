#!/usr/bin/env python3
"""Estime l'indice OTHERS (capitalisation des cryptos classées 11e à 100e)
sur 365 jours à partir de CoinGecko, et écrit data/others.json.
Aucune clé n'est obligatoire. Si CoinGecko limite trop les appels,
ajouter une clé gratuite 'Demo' dans le secret GitHub COINGECKO_API_KEY."""
import json, os, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

API = "https://api.coingecko.com/api/v3"
KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
N_COINS = 150      # nombre de cryptos analysées
SKIP = 10          # on retire les 10 premières
LAST = 100         # on additionne jusqu'au rang 100
PAUSE = 3.0        # secondes entre deux appels (limite gratuite : 30/min)


def get(path, params):
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    headers = {"accept": "application/json", "User-Agent": "crypto-dashboard"}
    if KEY:
        headers["x-cg-demo-api-key"] = KEY
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                print(f"  erreur {e.code}, nouvelle tentative dans 65 s ({attempt + 1}/6)")
                time.sleep(65)
                continue
            raise
        except urllib.error.URLError as e:
            print(f"  erreur réseau {e}, nouvelle tentative dans 15 s")
            time.sleep(15)
    raise RuntimeError(f"Échec après plusieurs tentatives : {path}")


def daily(points):
    """[[timestamp_ms, valeur], ...] -> {'AAAA-MM-JJ': valeur} (dernier point du jour)."""
    out = {}
    for ts, v in points:
        if v is None:
            continue
        d = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d")
        out[d] = v
    return out


def compute_others(caps_by_coin, skip=SKIP, last=LAST, min_coins=60):
    """Pour chaque jour : classe les cryptos, retire les `skip` premières,
    additionne jusqu'au rang `last`."""
    dates = sorted({d for s in caps_by_coin.values() for d in s})
    out = {}
    for d in dates:
        caps = sorted((s[d] for s in caps_by_coin.values() if s.get(d)), reverse=True)
        if len(caps) < min_coins:
            continue
        out[d] = sum(caps[skip:last])
    return out


def main():
    markets = get("/coins/markets", {"vs_currency": "usd", "order": "market_cap_desc",
                                     "per_page": N_COINS, "page": 1})
    ids = [m["id"] for m in markets]
    print(f"{len(ids)} cryptos à analyser")
    caps, btc = {}, {}
    for i, cid in enumerate(ids, 1):
        data = get(f"/coins/{cid}/market_chart",
                   {"vs_currency": "usd", "days": 365, "interval": "daily"})
        caps[cid] = daily(data.get("market_caps", []))
        if cid == "bitcoin":
            btc = daily(data.get("prices", []))
        print(f"  {i}/{len(ids)} {cid}")
        time.sleep(PAUSE)
    others = compute_others(caps)
    dates = [d for d in sorted(others) if d in btc]
    if not dates:
        raise SystemExit("Aucune donnée exploitable, rien n'est écrit.")
    result = {
        "source": "CoinGecko (estimation)",
        "method": f"Somme des capitalisations des cryptos classées {SKIP + 1}e à {LAST}e, parmi les {N_COINS} premières d'aujourd'hui.",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dates": dates,
        "others_mcap": [round(others[d]) for d in dates],
        "btc_price": [round(btc[d], 2) for d in dates],
    }
    os.makedirs("data", exist_ok=True)
    with open("data/others.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"OK : {len(dates)} jours écrits dans data/others.json")


if __name__ == "__main__":
    main()
