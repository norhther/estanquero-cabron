"""
Hookymia Flavour Shop — Flask web app.

Catalogue is persisted to data/catalogue.json and loaded from disk on startup.
Fetching from the remote API only happens when explicitly requested via /api/refresh.
"""

import json
import os
import re
import time
import unicodedata
from flask import Flask, jsonify, render_template, request, send_file, abort

import requests as req
from flavours import parse_formatos

app = Flask(__name__)

# ── Persistence ───────────────────────────────────────────────────────────────

DATA_DIR        = os.path.join(os.path.dirname(__file__), "data")
CATALOGUE_PATH  = os.path.join(DATA_DIR, "catalogue.json")
BRAND_IMG_DIR   = os.path.join(DATA_DIR, "brand_imgs")

# Known CDN patterns to try when fetching brand images.
# The actual storage location is private; these are probed in order.
_BRAND_IMG_BASES = [
    "https://firebasestorage.googleapis.com/v0/b/hookymia-app.appspot.com/o/marcas%2F{name}?alt=media",
    "https://firebasestorage.googleapis.com/v0/b/hookymia.appspot.com/o/marcas%2F{name}?alt=media",
]
API_URL       = "https://hookymia.es/api/get/index.php"

_cache: dict = {"flavours": [], "loaded_at": 0}


def _fetch(tipo: str) -> list:
    r = req.post(API_URL, data={"tipo": tipo}, timeout=20)
    r.raise_for_status()
    raw = r.json().get("respuesta", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    return raw or []


def _build_flavours(marcas_raw: list, sabores_raw: list) -> list:
    brands     = {m["id"]: m["nombre"] for m in marcas_raw}
    brand_imgs = {m["id"]: m.get("img", "") for m in marcas_raw}
    flavours = []
    for s in sabores_raw:
        if s.get("retirado", "0") == "1":
            continue
        mid = s.get("marca_id", "")
        flavours.append({
            "id":          s["id"],
            "nombre":      s["nombre"],
            "marca":       brands.get(mid, ""),
            "brand_img":   brand_imgs.get(mid, ""),
            "descripcion": s.get("descripcion", ""),
            "formatos":    parse_formatos(s.get("formatos", "")),
            "img":         s.get("img", ""),
        })
    return flavours


def _save_to_disk(flavours: list, loaded_at: float) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CATALOGUE_PATH, "w", encoding="utf-8") as f:
        json.dump({"loaded_at": loaded_at, "flavours": flavours}, f, ensure_ascii=False)


def _load_from_disk() -> bool:
    """Load catalogue from disk into cache. Returns True if successful."""
    if not os.path.exists(CATALOGUE_PATH):
        return False
    try:
        with open(CATALOGUE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _cache["flavours"] = data["flavours"]
        _cache["loaded_at"] = data["loaded_at"]
        return True
    except (json.JSONDecodeError, KeyError, OSError):
        return False


def get_catalogue() -> list:
    """Return cached flavours, loading from disk on first call."""
    if not _cache["flavours"]:
        _load_from_disk()
    return _cache["flavours"]


def refresh_from_api() -> dict:
    """Fetch fresh data from the API, update cache and disk."""
    marcas_raw  = _fetch("getListaMarcas")
    sabores_raw = _fetch("getListaSabores")
    flavours    = _build_flavours(marcas_raw, sabores_raw)
    loaded_at   = time.time()

    _cache["flavours"]  = flavours
    _cache["loaded_at"] = loaded_at
    _save_to_disk(flavours, loaded_at)
    return {"count": len(flavours), "loaded_at": loaded_at}


# ── Fuzzy search ──────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def fuzzy_search(query: str, flavours: list, limit: int = 30) -> list:
    from rapidfuzz import fuzz
    q = _normalize(query)
    scored = []
    for f in flavours:
        text = _normalize(f"{f['nombre']} {f['marca']} {f['descripcion']}")
        score = fuzz.token_set_ratio(q, text)
        if q in text:
            score = min(100, score + 20)
        scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for score, f in scored[:limit] if score >= 40]


def best_match(query: str, flavours: list):
    results = fuzzy_search(query, flavours, limit=1)
    return results[0] if results else None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    return jsonify(fuzzy_search(q, get_catalogue(), limit=30))


@app.route("/api/import", methods=["POST"])
def api_import():
    data  = request.get_json(force=True)
    lines = data.get("lines", [])
    flavours = get_catalogue()
    results  = []
    for line in lines:
        for part in [p.strip() for p in line.strip().split(",") if p.strip()]:
            results.append({"query": part, "match": best_match(part, flavours)})
    return jsonify(results)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        info = refresh_from_api()
        return jsonify({"ok": True, **info})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@app.route("/api/brand-img/<path:filename>")
def api_brand_img(filename: str):
    """
    Serve a brand logo image.
    1. Check local cache in data/brand_imgs/
    2. Try known CDN patterns
    3. 404 if not found anywhere
    """
    # Sanitise: only allow safe filenames (letters, digits, spaces, dots, hyphens)
    if not re.match(r'^[\w\s.\-]+$', filename):
        abort(400)

    os.makedirs(BRAND_IMG_DIR, exist_ok=True)
    local_path = os.path.join(BRAND_IMG_DIR, filename)

    if os.path.exists(local_path):
        return send_file(local_path)

    # Try remote sources
    for pattern in _BRAND_IMG_BASES:
        url = pattern.format(name=req.utils.quote(filename, safe=""))
        try:
            r = req.get(url, timeout=8)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                with open(local_path, "wb") as f:
                    f.write(r.content)
                return send_file(local_path)
        except req.RequestException:
            continue

    abort(404)


@app.route("/api/stats")
def api_stats():
    get_catalogue()
    return jsonify({
        "count":     len(_cache["flavours"]),
        "loaded_at": _cache["loaded_at"],
        "from_disk": os.path.exists(CATALOGUE_PATH),
    })


if __name__ == "__main__":
    if _load_from_disk():
        print(f"Loaded {len(_cache['flavours'])} flavours from disk.")
    else:
        print("No local catalogue found — fetching from API…")
        refresh_from_api()
        print(f"  {len(_cache['flavours'])} flavours saved.")
    app.run(debug=True, port=5000)
