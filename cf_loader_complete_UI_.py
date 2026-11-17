import os
import time
from datetime import datetime, timezone
from typing import List, Optional

import requests
import streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Codeforces Extractor", layout="wide")


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------
@st.cache_resource
def get_llm():
    return ChatOpenAI(
        model="openai/gpt-4o-mini",
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )


class ProblemConstraints(BaseModel):
    core_logic: str = Field(description="The underlying mathematical or algorithmic task without the story.")
    time_limit_hint: str = Field(description="Expected time complexity based on input constraints (e.g., O(N log N) if N=10^5).")
    edge_cases: List[str] = Field(description="Potential edge cases to watch out for, like N=0 or array containing negative numbers.")
    suggested_tags: List[str] = Field(description="Algorithm tags like 'prefix sum', 'sliding window', or 'greedy'.")


parser = PydanticOutputParser(pydantic_object=ProblemConstraints)

prompt = ChatPromptTemplate.from_messages([
    ("system", "Extract codeforces question information from the paragraph\n{format_instructions}"),
    ("human", "{paragraph}"),
])

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CF-Loader/1.0)"}


# ---------------------------------------------------------------------------
# Codeforces API — ground-truth rating + official tags
# (one call fetches the whole problemset; cache it instead of hitting the
# API per-problem)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_cf_problemset_index():
    resp = requests.get("https://codeforces.com/api/problemset.problems", timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "OK":
        raise RuntimeError(f"Codeforces API error: {payload.get('comment')}")
    problems = payload["result"]["problems"]
    # keyed by (contestId, index) for O(1) lookup while looping combos
    return {(p["contestId"], p["index"]): p for p in problems}


# ---------------------------------------------------------------------------
# MongoDB setup
# ---------------------------------------------------------------------------
@st.cache_resource
def get_collection():
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGO_DB", "codeforces")
    coll_name = os.environ.get("MONGO_COLLECTION", "problems")
    client = MongoClient(mongo_uri)
    return client[db_name][coll_name]


# ---------------------------------------------------------------------------
# Scraper + extractor (same logic as the script)
# ---------------------------------------------------------------------------
def fetch_problem_statement(contest_id: int, index: str) -> dict:
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    statement_div = soup.find("div", class_="problem-statement")
    if statement_div is None:
        raise ValueError(f"No problem-statement block found at {url} (bad contest/index?)")

    title_tag = statement_div.find("div", class_="title")
    title = title_tag.get_text(strip=True) if title_tag else f"{contest_id}{index}"

    header = statement_div.find("div", class_="header")
    if header:
        header.extract()

    raw_text = statement_div.get_text("\n", strip=True)

    return {
        "contest_id": contest_id,
        "index": index,
        "title": title,
        "url": url,
        "raw_text": raw_text,
    }


def extract_constraints(paragraph: str) -> ProblemConstraints:
    llm = get_llm()
    final_prompt = prompt.invoke({
        "paragraph": paragraph,
        "format_instructions": parser.get_format_instructions(),
    })
    response = llm.invoke(final_prompt)
    return parser.parse(response.content)


def process_range(start: int, end: int, letters: List[str], delay: float,
                   skip_existing: bool, skip_unrated: bool,
                   log_area, progress_bar, results_area):
    collection = get_collection()
    cf_index = get_cf_problemset_index()
    results = []
    combos = [(cid, l) for cid in range(start, end + 1) for l in letters]
    total = len(combos)
    logs = []

    for i, (contest_id, letter) in enumerate(combos, start=1):
        doc_id = f"{contest_id}{letter}"
        progress_bar.progress(i / total, text=f"{doc_id} ({i}/{total})")

        if skip_existing and collection.find_one({"_id": doc_id}):
            logs.append(f"⏭️ [skip] {doc_id} already in DB")
            log_area.code("\n".join(logs[-25:]))
            continue

        # Ground-truth metadata from the CF API. Some problems (gym-only,
        # unofficial, very new) have no public rating.
        cf_meta = cf_index.get((contest_id, letter))
        rating = cf_meta.get("rating") if cf_meta else None
        official_tags = cf_meta.get("tags", []) if cf_meta else []
        points = cf_meta.get("points") if cf_meta else None
        cf_name = cf_meta.get("name") if cf_meta else None
        problem_type = cf_meta.get("type") if cf_meta else None

        if skip_unrated and rating is None:
            logs.append(f"⏭️ [skip] {doc_id} has no public rating")
            log_area.code("\n".join(logs[-25:]))
            continue

        try:
            problem = fetch_problem_statement(contest_id, letter)
        except Exception as e:
            logs.append(f"❌ [miss] {doc_id}: {e}")
            log_area.code("\n".join(logs[-25:]))
            continue

        try:
            constraints = extract_constraints(problem["raw_text"])
        except Exception as e:
            logs.append(f"❌ [llm-error] {doc_id}: {e}")
            log_area.code("\n".join(logs[-25:]))
            continue

        record = {
            "_id": doc_id,
            "contest_id": contest_id,
            "index": letter,
            "title": cf_name or problem["title"],
            "url": problem["url"],
            "rating": rating,
            "official_tags": official_tags,
            "points": points,
            "problem_type": problem_type,
            "raw_text": problem["raw_text"],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            **constraints.model_dump(),
        }
        collection.update_one({"_id": doc_id}, {"$set": record}, upsert=True)
        results.append(record)

        rating_label = rating if rating is not None else "unrated"
        logs.append(f"✅ [ok] saved {doc_id} - {record['title']} (rating: {rating_label})")
        log_area.code("\n".join(logs[-25:]))
        results_area.dataframe(
            [
                {
                    "id": r["_id"],
                    "title": r["title"],
                    "rating": r["rating"],
                    "official_tags": ", ".join(r["official_tags"]),
                    "llm_tags": ", ".join(r["suggested_tags"]),
                }
                for r in results
            ],
            use_container_width=True,
        )

        time.sleep(delay)

    progress_bar.progress(1.0, text="Done")
    return results


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🧩 Codeforces Problem Extractor")
st.caption("Scrapes Codeforces problems, extracts structured constraints via LLM, and saves to MongoDB.")

with st.sidebar:
    st.header("Settings")
    start_id = st.number_input("Start contest ID", min_value=1, value=1, step=1)
    end_id = st.number_input("End contest ID", min_value=1, value=1, step=1)
    letters_raw = st.text_input("Letters (comma-separated)", value="A,B,C,D")
    delay = st.slider("Delay between requests (seconds)", 0.0, 10.0, 2.0, 0.5)
    skip_existing = st.checkbox("Skip problems already in DB", value=True)
    skip_unrated = st.checkbox("Skip problems with no public rating", value=True,
                                help="Some gym/unofficial problems have no CF rating — "
                                     "uncheck to save them anyway with rating=null.")
    run_btn = st.button("🚀 Run", type="primary", use_container_width=True)

letters = [l.strip().upper() for l in letters_raw.split(",") if l.strip()]

col1, col2 = st.columns(2)
with col1:
    st.metric("Contest range", f"{start_id} – {end_id}")
with col2:
    st.metric("Combinations", (end_id - start_id + 1) * len(letters) if end_id >= start_id else 0)

if run_btn:
    if end_id < start_id:
        st.error("End contest ID must be >= start contest ID.")
    elif not letters:
        st.error("Enter at least one letter (e.g. A,B,C).")
    else:
        st.subheader("Progress")
        progress_bar = st.progress(0.0)
        log_area = st.empty()
        st.subheader("Saved problems")
        results_area = st.empty()

        with st.spinner("Running..."):
            results = process_range(
                start=int(start_id),
                end=int(end_id),
                letters=letters,
                delay=delay,
                skip_existing=skip_existing,
                skip_unrated=skip_unrated,
                log_area=log_area,
                progress_bar=progress_bar,
                results_area=results_area,
            )
        st.success(f"Finished. {len(results)} new problem(s) saved.")
else:
    st.info("Set your range and letters in the sidebar, then hit Run.")