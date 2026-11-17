"""
Quick sanity check for the Mongo connection used by streamlit_app.py.
Inserts one fixed, fake problem record, reads it back, then cleans up.

Run: python test.py
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "codeforces")
COLLECTION_NAME = os.environ.get("MONGO_COLLECTION", "problems")

# Fixed sample record — same shape as what streamlit_app.py writes.
SAMPLE_DOC = {
    "_id": "TEST999Z",
    "contest_id": 999,
    "index": "Z",
    "title": "Sample Test Problem",
    "url": "https://codeforces.com/problemset/problem/999/Z",
    "rating": 1500,
    "official_tags": ["dp", "greedy"],
    "points": None,
    "problem_type": "PROGRAMMING",
    "raw_text": "This is a fake problem statement used only for testing the DB.",
    "scraped_at": datetime.now(timezone.utc).isoformat(),
    "core_logic": "Not a real problem — inserted by test.py.",
    "time_limit_hint": "O(1)",
    "edge_cases": ["n/a"],
    "suggested_tags": ["testing"],
}


def main():
    print(f"Connecting to: {MONGO_URI}")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

    try:
        client.admin.command("ping")
    except ConnectionFailure as e:
        print(f"❌ Could not reach MongoDB: {e}")
        return

    print("✅ Connected.")
    collection = client[DB_NAME][COLLECTION_NAME]

    # --- Write ---
    print(f"\nUpserting sample doc '{SAMPLE_DOC['_id']}' into "
          f"{DB_NAME}.{COLLECTION_NAME} ...")
    result = collection.update_one(
        {"_id": SAMPLE_DOC["_id"]}, {"$set": SAMPLE_DOC}, upsert=True
    )
    print(f"✅ matched={result.matched_count} "
          f"modified={result.modified_count} "
          f"upserted_id={result.upserted_id}")

    # --- Read ---
    print(f"\nRetrieving '{SAMPLE_DOC['_id']}' back ...")
    fetched = collection.find_one({"_id": SAMPLE_DOC["_id"]})
    if fetched is None:
        print("❌ Document not found after insert — something's wrong.")
        return

    print("✅ Retrieved:")
    for key, value in fetched.items():
        print(f"   {key}: {value}")

    # --- Verify a couple of fields round-tripped correctly ---
    assert fetched["rating"] == SAMPLE_DOC["rating"], "rating mismatch!"
    assert fetched["official_tags"] == SAMPLE_DOC["official_tags"], "tags mismatch!"
    print("\n✅ Round-trip check passed (rating + official_tags match).")

    # --- Cleanup ---
    collection.delete_one({"_id": SAMPLE_DOC["_id"]})
    print(f"\n🧹 Cleaned up test doc '{SAMPLE_DOC['_id']}'.")

    total = collection.count_documents({})
    print(f"\nCollection '{COLLECTION_NAME}' now has {total} document(s) left.")


if __name__ == "__main__":
    main()