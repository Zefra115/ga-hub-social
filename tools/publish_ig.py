#!/usr/bin/env python3
"""Pubblica il carosello settimanale su Instagram (GA.Hub) con l'API ufficiale
Instagram Graph API (accesso tramite Facebook, graph.facebook.com; account Instagram
professionale collegato a una Pagina Facebook). Con --via instagram usa invece
graph.instagram.com (accesso tramite Instagram).

Il token NON sta in questo file né in variabili: è salvato come segreto di rete
dell'ambiente e il proxy lo aggiunge da solo all'header Authorization delle
richieste verso l'host dell'API. Qui si manda un valore fittizio.

Comandi:
  check   --urls U1 ... U5 --caption FILE   controlli prima della pubblicazione (nessun effetto)
  whoami                                      verifica che il token funzioni (username dell'account)
  publish --urls U1 ... U5 --caption FILE [--story-urls S1 S2]
                                              pubblica il carosello e poi le storie (IRREVERSIBILE)
  stories --story-urls S1 S2                  pubblica solo le storie (IRREVERSIBILE)
"""
import argparse, json, sys, time, urllib.parse, urllib.request, urllib.error

API = "https://graph.facebook.com/v23.0"
HDR = {"Authorization": "Bearer PROXY_INJECTS_TOKEN", "User-Agent": "gahub-meta-report/1.0"}
EXPECTED_USER = "ga_hub_it"


def call(method, path, params=None):
    url = f"{API}/{path}"
    data = None
    if params and method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    elif params:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:600]
        raise SystemExit(f"ERRORE API {e.code} su {method} {path}: {body}")


def whoami():
    if "graph.instagram.com" in API:
        me = call("GET", "me", {"fields": "user_id,username,account_type"})
        if me.get("username", "").lower() != EXPECTED_USER:
            raise SystemExit(f"ERRORE: il token è dell'account @{me.get('username')}, atteso @{EXPECTED_USER}")
        return me
    pages = call("GET", "me/accounts", {"fields": "name,instagram_business_account{id,username}"}).get("data", [])
    for pg in pages:
        ig = pg.get("instagram_business_account") or {}
        if ig.get("username", "").lower() == EXPECTED_USER:
            return {"user_id": ig["id"], "username": ig["username"], "page": pg.get("name")}
    seen = [(pg.get("name"), (pg.get("instagram_business_account") or {}).get("username")) for pg in pages]
    raise SystemExit(f"ERRORE: nessuna Pagina collegata a @{EXPECTED_USER}. Pagine viste dal token: {seen}")


def check(urls, caption, story_urls=()):
    probs = []
    if urls and not 2 <= len(urls) <= 10:
        probs.append(f"un carosello vuole 2–10 immagini, qui {len(urls)}")
    for u in list(urls) + list(story_urls):
        try:
            req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "gahub-meta-report/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                ct = r.headers.get("Content-Type", "")
                size = int(r.headers.get("Content-Length") or 0)
                if "jpeg" not in ct:
                    probs.append(f"{u}: tipo {ct!r}, serve image/jpeg")
                if size > 8 * 1024 * 1024:
                    probs.append(f"{u}: {size} byte, max 8 MB")
        except Exception as e:  # noqa: BLE001
            probs.append(f"{u}: non raggiungibile ({e})")
    if not urls:
        return probs
    if len(caption) > 2200:
        probs.append(f"didascalia di {len(caption)} caratteri, max 2200")
    if caption.count("#") > 30:
        probs.append("più di 30 hashtag")
    if not caption.strip():
        probs.append("didascalia vuota")
    return probs


def wait_ready(cid, tries=30):
    for _ in range(tries):
        st = call("GET", cid, {"fields": "status_code,status"})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise SystemExit(f"ERRORE: contenitore {cid} in stato {code}: {st.get('status')}")
        time.sleep(5)
    raise SystemExit(f"ERRORE: contenitore {cid} non pronto dopo {tries*5}s")


def publish(urls, caption):
    me = whoami()
    uid = me["user_id"]
    children = []
    for u in urls:
        c = call("POST", f"{uid}/media", {"image_url": u, "is_carousel_item": "true"})
        children.append(c["id"])
    for c in children:
        wait_ready(c)
    car = call("POST", f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    wait_ready(car["id"])
    pub = call("POST", f"{uid}/media_publish", {"creation_id": car["id"]})
    info = call("GET", pub["id"], {"fields": "permalink,timestamp"})
    return {"media_id": pub["id"], **info}


def publish_stories(urls):
    me = whoami()
    uid = me["user_id"]
    out = []
    for u in urls:
        c = call("POST", f"{uid}/media", {"image_url": u, "media_type": "STORIES"})
        wait_ready(c["id"])
        pub = call("POST", f"{uid}/media_publish", {"creation_id": c["id"]})
        out.append(pub["id"])
    return {"stories": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "whoami", "publish", "stories"])
    ap.add_argument("--story-urls", nargs="*", default=[])
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--caption")
    ap.add_argument("--via", choices=["facebook", "instagram"], default="facebook")
    a = ap.parse_args()
    global API
    if a.via == "instagram":
        API = "https://graph.instagram.com/v23.0"
    if a.cmd == "whoami":
        print(json.dumps(whoami(), ensure_ascii=False))
        return
    if a.cmd == "stories":
        a.urls = []
    cap = open(a.caption, encoding="utf-8").read().strip() if a.caption else ""
    probs = check(a.urls, cap, a.story_urls)
    if probs:
        print("PROBLEMI:\n- " + "\n- ".join(probs))
        sys.exit(2)
    if a.cmd == "check":
        print(f"OK: {len(a.urls)} slide, {len(a.story_urls)} storie, didascalia {len(cap)} caratteri")
        return
    if a.cmd == "stories":
        print(json.dumps(publish_stories(a.story_urls), ensure_ascii=False))
        return
    res = publish(a.urls, cap)
    print(json.dumps(res, ensure_ascii=False), flush=True)
    if a.story_urls:
        print(json.dumps(publish_stories(a.story_urls), ensure_ascii=False))


if __name__ == "__main__":
    main()
