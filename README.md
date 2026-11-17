# Codeforces Problem Parser & Dashboard

Scrapes Codeforces problem statements, uses an LLM to extract their core
algorithmic structure (stripped of story/flavor text), stores everything in
MongoDB, and visualizes the resulting dataset in an interactive dashboard.

## Components

### 1. Parser — LLM-based constraint extraction (`core.py`, `uicore.py`)
Takes a raw Codeforces problem statement and uses an LLM (via LangChain +
OpenRouter, `gpt-4o-mini`) with a Pydantic output parser to pull out:
- `core_logic` — the underlying algorithmic task, with the story removed
- `time_limit_hint` — expected time complexity given the input constraints
- `edge_cases` — things to watch for (N=0, negative numbers, etc.)
- `suggested_tags` — algorithm tags (sliding window, greedy, prefix sum, ...)

`uicore.py` wraps the same logic in a Streamlit UI for pasting in a problem
and seeing the extracted structure interactively.

### 2. Loader (`cf_loader_complete.py` / `cf_loader_complete_UI_.py`)
Scrapes a problem page directly from `codeforces.com/problemset/problem/...`
with `requests` + `BeautifulSoup`, strips the title/limits header, runs it
through the extractor above, and writes the result into a MongoDB
`problems` collection.

### 3. Dashboard (`cf_dashboard/`)
A Flask app that reads the populated MongoDB collection and renders:
- problems bucketed into Codeforces-style rating bands (800–1199 ... 2400+)
- per-tag statistics
- tag co-occurrence analysis
- difficulty encoded using Codeforces' own rating color scale

All aggregation happens server-side in `app.py`; the frontend
(`templates/index.html` + `static/dashboard.js`) only renders what the API
returns.

## Running it

```bash
pip install flask flask-cors python-dotenv pymongo requests beautifulsoup4 \
            langchain-openai langchain-core pydantic streamlit

# .env needs:
# OPENROUTER_API_KEY=...
# MONGO_URI=mongodb://localhost:27017   (optional, this is the default)

# parse + load problems into Mongo
python cf_loader_complete.py

# or use the Streamlit UI to extract one problem at a time
streamlit run uicore.py

# run the dashboard
cd cf_dashboard
python app.py
# open http://127.0.0.1:5000
```

## Tech stack

Python, Flask, MongoDB, LangChain, OpenRouter (`gpt-4o-mini`), Streamlit,
BeautifulSoup
