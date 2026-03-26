"""
Hookymia Flavour Shop — Flask web app.

Caches the full catalogue in memory on first request (or on demand via /refresh).
Exposes endpoints for fuzzy search, list import, and catalogue browsing.
"""

import json
import time
import unicodedata
from flask import Flask, jsonify, render_template, request

import requests as req
from flavours import parse_formatos

app = Flask(__name__)

# ── In-memory cache ──────────────────────────────────────────────────────────

_cache: dict = {"flavours": [], "brands": {}, "loaded_at": 0}

API_URL = "https://hookymia.es/api/get/index.php"
CACHE_TTL = 3600  # seconds


def _fetch(tipo: str) -> list:
    r = req.post(API_URL, data={"tipo": tipo}, timeout=15)
    r.raise_for_status()
    raw = r.json().get("respuesta", [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    return raw or []


def load_catalogue(force: bool = False) -> list:
    now = time.time()
    if not force and _cache["flavours"] and (now - _cache["loaded_at"]) < CACHE_TTL:
        return _cache["flavours"]

    marcas_raw = _fetch("getListaMarcas")
    brands = {m["id"]: m["nombre"] for m in marcas_raw}

    sabores_raw = _fetch("getListaSabores")
    flavours = []
    for s in sabores_raw:
        if s.get("retirado", "0") == "1":
            continue
        flavours.append({
            "id":          s["id"],
            "nombre":      s["nombre"],
            "marca":       brands.get(s.get("marca_id", ""), ""),
            "descripcion": s.get("descripcion", ""),
            "formatos":    parse_formatos(s.get("formatos", "")),
            "img":         s.get("img", ""),
        })

    _cache["flavours"] = flavours
    _cache["brands"] = brands
    _cache["loaded_at"] = now
    return flavours


# ── Fuzzy matching helpers ────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase + strip accents."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def fuzzy_search(query: str, flavours: list, limit: int = 20) -> list:
    """
    Score each flavour against the query.
    Uses rapidfuzz for token-set ratio (handles word order, partial matches, typos).
    Falls back to simple substring matching.
    """
    from rapidfuzz import fuzz

    q = _normalize(query)
    scored = []
    for f in flavours:
        text = _normalize(f"{f['nombre']} {f['marca']} {f['descripcion']}")
        score = fuzz.token_set_ratio(q, text)
        # Boost exact substring hits
        if q in text:
            score = min(100, score + 20)
        scored.append((score, f))

    scored.sort(key=lambda x: -x[0])
    return [f for score, f in scored[:limit] if score >= 40]


def best_match(query: str, flavours: list):
    """Return the single best match for a query line."""
    results = fuzzy_search(query, flavours, limit=1)
    return results[0] if results else None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    flavours = load_catalogue()
    results = fuzzy_search(q, flavours, limit=30)
    return jsonify(results)


@app.route("/api/import", methods=["POST"])
def api_import():
    """
    Accept a raw paste (one item per line) and return the best match per line.
    Body: {"lines": ["line1", "line2", ...]}
    """
    data = request.get_json(force=True)
    lines = data.get("lines", [])
    flavours = load_catalogue()

    results = []
    for line in lines:
        line = line.strip()
        # Handle comma-separated items on one line (e.g. "Dozaj lux, dark purple, rgasm")
        parts = [p.strip() for p in line.split(",") if p.strip()]
        for part in parts:
            match = best_match(part, flavours)
            results.append({
                "query":  part,
                "match":  match,
            })
    return jsonify(results)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    load_catalogue(force=True)
    return jsonify({"ok": True, "count": len(_cache["flavours"])})


@app.route("/api/stats")
def api_stats():
    flavours = load_catalogue()
    return jsonify({
        "count": len(flavours),
        "loaded_at": _cache["loaded_at"],
    })


if __name__ == "__main__":
    print("Pre-loading catalogue...")
    load_catalogue()
    print(f"  {len(_cache['flavours'])} flavours loaded.")
    app.run(debug=True, port=5000)
