#!/usr/bin/env python3
"""Récupère le MVRV de BTC (Coin Metrics, API communautaire gratuite, sans clé),
construit un récapitulatif automatique par règles (sans IA) et écrit data/mvrv.json.
Si data/others.json existe (créé par fetch_others.py), le récap commente aussi BTC et OTHERS."""
import json, os, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

API = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
START = "2017-01-01"


def get(url):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json", "User-Agent": "crypto-dashboard"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                print(f"  erreur {e.code}, nouvelle tentative dans 15 s ({attempt + 1}/5)")
                time.sleep(15)
                continue
            raise
        except urllib.error.URLError as e:
            print(f"  erreur réseau {e}, nouvelle tentative dans 15 s")
            time.sleep(15)
    raise RuntimeError("Échec de l'appel Coin Metrics")


def fetch_mvrv():
    params = {"assets": "btc", "metrics": "CapMVRVCur", "frequency": "1d",
              "start_time": START, "page_size": 10000}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    rows = []
    while url:
        j = get(url)
        rows += j.get("data", [])
        url = j.get("next_page_url")
    out = [(r["time"][:10], float(r["CapMVRVCur"])) for r in rows
           if r.get("CapMVRVCur") not in (None, "")]
    out.sort()
    return [d for d, _ in out], [v for _, v in out]


def fr(x, d=1, sign=False):
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s.replace(".", ",")


def zone(v):
    if v < 1: return "sous 1 : sous le coût moyen d'achat"
    if v < 2.5: return "zone intermédiaire"
    if v < 3.5: return "zone élevée"
    return "zone très élevée"


def change(vals, n):
    return (vals[-1] / vals[-1 - n] - 1) * 100 if len(vals) > n else None


def load_market():
    try:
        with open("data/others.json", encoding="utf-8") as f:
            j = json.load(f)
        return j["btc_price"], j["others_mcap"]
    except Exception:
        return None, None


def build_recap(dates, vals, btc=None, oth=None):
    v = vals[-1]
    d7, d30 = change(vals, 7), change(vals, 30)
    pctile = sum(1 for x in vals if x <= v) / len(vals) * 100
    stats = {"last": round(v, 3), "zone": zone(v), "d7": round(d7 or 0, 2),
             "d30": round(d30 or 0, 2), "percentile": round(pctile, 1)}
    L = [f"Le MVRV de BTC est à {fr(v, 2)} ({zone(v)}). "
         f"Il est supérieur ou égal à {fr(pctile, 0)} % des valeurs observées depuis {START[:4]}."]
    if d30 is not None:
        t = "tendance haussière" if d30 > 5 else "tendance baissière" if d30 < -5 else "plutôt stable"
        L.append(f"Sur 7 jours : {fr(d7, 1, True)} % ; sur 30 jours : {fr(d30, 1, True)} % ({t}).")
    if v < 1:
        L.append(f"Il lui faudrait environ {fr((1 / v - 1) * 100, 0)} % de hausse pour repasser au-dessus de 1.")
    else:
        L.append(f"Une baisse d'environ {fr((1 - 1 / v) * 100, 0)} % le ramènerait à 1 ; "
                 f"il lui faudrait environ {fr((3.5 / v - 1) * 100, 0)} % de hausse pour atteindre 3,5, "
                 "niveau qui a coïncidé avec des sommets passés." if v < 3.5 else
                 "Il est dans une zone qui a coïncidé avec des sommets passés.")
    if btc and len(btc) > 30:
        b7, b30 = change(btc, 7), change(btc, 30)
        L.append(f"Prix de BTC : {fr(b7, 1, True)} % sur 7 jours, {fr(b30, 1, True)} % sur 30 jours.")
        if d30 is not None:
            same = (d30 >= 0) == (b30 >= 0)
            L.append("Le MVRV et le prix évoluent dans le même sens sur 30 jours : pas de divergence notable."
                     if same else
                     "Le MVRV et le prix évoluent en sens opposé sur 30 jours : divergence à surveiller.")
    if oth and btc and len(oth) > 30:
        o30, b30 = change(oth, 30), change(btc, 30)
        L.append(f"OTHERS (estimé) : {fr(o30, 1, True)} % sur 30 jours, soit "
                 f"{fr(abs(o30 - b30), 1)} points de {'mieux' if o30 >= b30 else 'moins bien'} que BTC.")
    L.append("Résumé généré automatiquement par règles, sans IA. Repères historiques, pas un conseil en investissement.")
    return {"titre": f"Récapitulatif du {dates[-1][8:]}/{dates[-1][5:7]}/{dates[-1][:4]}", "lignes": L}, stats


def main():
    dates, vals = fetch_mvrv()
    if len(dates) < 100:
        raise SystemExit("Données insuffisantes, rien n'est écrit.")
    btc, oth = load_market()
    recap, stats = build_recap(dates, vals, btc, oth)
    result = {"source": "Coin Metrics (API communautaire)",
              "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "dates": dates, "mvrv": [round(v, 3) for v in vals],
              "stats": stats, "recap": recap}
    os.makedirs("data", exist_ok=True)
    with open("data/mvrv.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"OK : {len(dates)} jours, dernier MVRV {vals[-1]:.2f}")
    print("\n".join(recap["lignes"]))


if __name__ == "__main__":
    main()
