import os
import time
from typing import List

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# LLM setup (same bot you already had)
# ---------------------------------------------------------------------------
llm = ChatOpenAI(
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

# ---------------------------------------------------------------------------
# MongoDB setup
# ---------------------------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "codeforces")
COLLECTION_NAME = os.environ.get("MONGO_COLLECTION", "problems")

mongo_client = MongoClient(MONGO_URI)
collection = mongo_client[DB_NAME][COLLECTION_NAME]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CF-Loader/1.0)"}


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
def fetch_problem_statement(contest_id: int, index: str) -> dict:
    """Scrape a single Codeforces problem page and return its title + raw text."""
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    statement_div = soup.find("div", class_="problem-statement")
    if statement_div is None:
        raise ValueError(f"No problem-statement block found at {url} (bad contest/index?)")

    title_tag = statement_div.find("div", class_="title")
    title = title_tag.get_text(strip=True) if title_tag else f"{contest_id}{index}"

    # Drop the header block (title/time-limit/memory-limit lines) so what's
    # left is the narrative + input/output spec + examples, closer to what
    # your extractor expects as "a paragraph".
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


# ---------------------------------------------------------------------------
# Extraction (your existing bot, wrapped in a function)
# ---------------------------------------------------------------------------
def extract_constraints(paragraph: str) -> ProblemConstraints:
    final_prompt = prompt.invoke({
        "paragraph": paragraph,
        "format_instructions": parser.get_format_instructions(),
    })
    response = llm.invoke(final_prompt)
    return parser.parse(response.content)


# ---------------------------------------------------------------------------
# Batch driver: contest-id range x letters
# ---------------------------------------------------------------------------
def process_range(start: int, end: int, letters: List[str], delay: float = 2.0):
    """
    Loop over contest IDs [start, end] x the given letters (e.g. ["A","B","C","D"]),
    scrape each problem, run it through the extractor, and upsert into MongoDB.
    Already-saved problems are skipped so you can re-run safely.
    """
    for contest_id in range(start, end + 1):
        for letter in letters:
            doc_id = f"{contest_id}{letter}"

            if collection.find_one({"_id": doc_id}):
                print(f"[skip] {doc_id} already in DB")
                continue

            try:
                problem = fetch_problem_statement(contest_id, letter)
            except Exception as e:
                print(f"[miss] {doc_id}: {e}")
                continue

            try:
                constraints = extract_constraints(problem["raw_text"])
            except Exception as e:
                print(f"[llm-error] {doc_id}: {e}")
                continue

            record = {
                "_id": doc_id,
                "contest_id": contest_id,
                "index": letter,
                "title": problem["title"],
                "url": problem["url"],
                "raw_text": problem["raw_text"],
                **constraints.model_dump(),
            }
            collection.insert_one(record)
            print(f"[ok] saved {doc_id} - {problem['title']}")

            time.sleep(delay)  # be polite to Codeforces' servers


if __name__ == "__main__":
    start_id = int(input("Start contest id: "))
    end_id = int(input("End contest id: "))
    letters_raw = input("Letters (comma-separated, e.g. A,B,C,D): ")
    letters = [l.strip().upper() for l in letters_raw.split(",") if l.strip()]

    process_range(start_id, end_id, letters)