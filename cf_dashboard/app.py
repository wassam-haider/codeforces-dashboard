"""
Codeforces Problem Dashboard — Flask backend.

All data work (reading Mongo, bucketing ratings, computing tag stats,
co-occurrence) happens here in Python. The frontend (templates/index.html +
static/js/dashboard.js) only renders what these endpoints return.

Run:
    pip install flask python-dotenv pymongo --break-system-packages
    python app.py
Then open http://127.0.0.1:5000
"""

import os
from collections import defaultdict
from itertools import combinations

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from pymongo import MongoClient

load_dotenv(override=True)

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "codeforces")
COLLECTION_NAME = os.environ.get("MONGO_COLLECTION", "problems")

# Rating bands used across every chart — wide enough to keep bars readable,
# aligned roughly to how Codeforces problems are commonly grouped.
BANDS = [
    (800, 1199, "800–1199"),
    (1200, 1499, "1200–1499"),
    (1500, 1799, "1500–1799"),
    (1800, 2099, "1800–2099"),
    (2100, 2399, "2100–2399"),
    (2400, 10000, "2400+"),
]

# Official Codeforces rating colors — used to encode difficulty consistently
# across every chart on the page instead of an arbitrary palette.
def rating_color(rating):
    if rating is None:
        return "#6e7681"
    if rating < 1200:
        return "#808080"
    if rating < 1400:
        return "#1fa34a"
    if rating < 1600:
        return "#17a2a2"
    if rating < 1900:
        return "#2b5fd9"
    if rating < 2100:
        return "#a83fd9"
    if rating < 2400:
        return "#e08a1e"
    return "#e03e3e"


def band_for(rating):
    for lo, hi, label in BANDS:
        if lo <= rating <= hi:
            return label
    return None


app = Flask(__name__)


def get_collection():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client[DB_NAME][COLLECTION_NAME]


def load_rated_problems():
    """Pull every problem that has a rating + official_tags into memory.
    Dataset sizes here (hundreds–low thousands of docs) are small enough
    that plain Python aggregation is simpler and easier to debug than a
    Mongo aggregation pipeline."""
    collection = get_collection()
    cursor = collection.find(
        {"rating": {"$ne": None}},
        {"_id": 1, "rating": 1, "official_tags": 1, "suggested_tags": 1, "title": 1},
    )
    return list(cursor)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summary")
def api_summary():
    problems = load_rated_problems()
    if not problems:
        return jsonify({"total": 0, "min_rating": None, "max_rating": None, "tag_count": 0})

    ratings = [p["rating"] for p in problems]
    tags = set()
    for p in problems:
        tags.update(p.get("official_tags", []))

    return jsonify({
        "total": len(problems),
        "min_rating": min(ratings),
        "max_rating": max(ratings),
        "avg_rating": round(sum(ratings) / len(ratings)),
        "tag_count": len(tags),
    })


@app.route("/api/rating-histogram")
def api_rating_histogram():
    problems = load_rated_problems()
    counts = defaultdict(int)
    for p in problems:
        # bucket into steps of 100 for a finer-grained histogram than the bands
        bucket = (p["rating"] // 100) * 100
        counts[bucket] += 1

    buckets = sorted(counts.keys())
    return jsonify({
        "labels": [str(b) for b in buckets],
        "counts": [counts[b] for b in buckets],
        "colors": [rating_color(b) for b in buckets],
    })


@app.route("/api/tag-lifespan")
def api_tag_lifespan():
    """For each tag: the rating range it spans, and how many problems
    carry it. This answers 'when does tag X start/stop appearing'."""
    problems = load_rated_problems()
    stats = defaultdict(lambda: {"min": None, "max": None, "ratings": []})

    for p in problems:
        for tag in p.get("official_tags", []):
            s = stats[tag]
            s["ratings"].append(p["rating"])
            s["min"] = p["rating"] if s["min"] is None else min(s["min"], p["rating"])
            s["max"] = p["rating"] if s["max"] is None else max(s["max"], p["rating"])

    rows = []
    for tag, s in stats.items():
        avg = round(sum(s["ratings"]) / len(s["ratings"]))
        rows.append({
            "tag": tag,
            "min": s["min"],
            "max": s["max"],
            "avg": avg,
            "count": len(s["ratings"]),
            "color": rating_color(avg),
        })

    # top 15 by frequency, keeps the chart legible
    rows.sort(key=lambda r: r["count"], reverse=True)
    rows = rows[:15]
    # then order the chart itself by where the tag starts appearing
    rows.sort(key=lambda r: r["min"])
    return jsonify(rows)


@app.route("/api/tag-by-band")
def api_tag_by_band():
    """Stacked/grouped view: which tags dominate at each rating band."""
    problems = load_rated_problems()
    tag_totals = defaultdict(int)
    for p in problems:
        for tag in p.get("official_tags", []):
            tag_totals[tag] += 1
    top_tags = [t for t, _ in sorted(tag_totals.items(), key=lambda kv: kv[1], reverse=True)[:8]]

    band_labels = [b[2] for b in BANDS]
    matrix = {tag: {label: 0 for label in band_labels} for tag in top_tags}

    for p in problems:
        label = band_for(p["rating"])
        if label is None:
            continue
        for tag in p.get("official_tags", []):
            if tag in matrix:
                matrix[tag][label] += 1

    return jsonify({
        "bands": band_labels,
        "series": [{"tag": tag, "values": [matrix[tag][b] for b in band_labels]} for tag in top_tags],
    })


@app.route("/api/tag-cooccurrence")
def api_tag_cooccurrence():
    """Which tags commonly appear together on the same problem."""
    problems = load_rated_problems()
    tag_totals = defaultdict(int)
    for p in problems:
        for tag in p.get("official_tags", []):
            tag_totals[tag] += 1
    top_tags = [t for t, _ in sorted(tag_totals.items(), key=lambda kv: kv[1], reverse=True)[:10]]
    top_set = set(top_tags)

    pair_counts = defaultdict(int)
    for p in problems:
        present = [t for t in p.get("official_tags", []) if t in top_set]
        for a, b in combinations(sorted(set(present)), 2):
            pair_counts[(a, b)] += 1

    matrix = []
    max_count = max(pair_counts.values(), default=1)
    for a in top_tags:
        row = []
        for b in top_tags:
            if a == b:
                row.append(tag_totals[a])
            else:
                key = (a, b) if (a, b) in pair_counts else (b, a)
                row.append(pair_counts.get(key, 0))
        matrix.append(row)

    return jsonify({"tags": top_tags, "matrix": matrix, "max": max(max_count, max(tag_totals.values(), default=1))})


@app.route("/api/tag-agreement")
def api_tag_agreement():
    """Bonus chart: how often the LLM's guessed tags overlap with the
    official Codeforces tags, broken down by rating band."""
    problems = load_rated_problems()
    band_scores = defaultdict(list)

    for p in problems:
        official = set(p.get("official_tags", []))
        suggested = set(p.get("suggested_tags", []))
        if not official:
            continue
        overlap = len(official & suggested) / len(official)
        label = band_for(p["rating"])
        if label:
            band_scores[label].append(overlap)

    band_labels = [b[2] for b in BANDS]
    return jsonify({
        "bands": band_labels,
        "agreement_pct": [
            round(100 * sum(band_scores[b]) / len(band_scores[b])) if band_scores[b] else None
            for b in band_labels
        ],
    })

@app.route("/api/practice-problems")
def api_practice_problems():
    from flask import request

    min_rating = int(request.args.get("min_rating", 800))
    max_rating = int(request.args.get("max_rating", 3500))
    tags = [t.strip() for t in request.args.get("tags", "").split(",") if t.strip()]
    mode = request.args.get("mode", "any")
    limit = min(int(request.args.get("limit", 10)), 100)

    problems = load_rated_problems()

    filtered = []

    for p in problems:
        rating = p.get("rating")
        official_tags = set(p.get("official_tags", []))

        if rating is None or not (min_rating <= rating <= max_rating):
            continue

        if tags:
            selected = set(tags)

            if mode == "all" and not selected.issubset(official_tags):
                continue

            if mode == "any" and not selected.intersection(official_tags):
                continue

        filtered.append({
            "title": p.get("title", "Untitled"),
            "rating": rating,
            "tags": p.get("official_tags", []),
            "id": str(p.get("_id", ""))
        })

    # Randomize results so you get different practice problems
    import random
    random.shuffle(filtered)

    return jsonify({
        "count": len(filtered),
        "problems": filtered[:limit]
    })

@app.route("/api/tags")
def api_tags():
    problems = load_rated_problems()

    tags = set()

    for p in problems:
        tags.update(p.get("official_tags", []))

    return jsonify(sorted(tags))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
