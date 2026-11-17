import os
import json
import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import List, Optional
from langchain_core.output_parsers import PydanticOutputParser

load_dotenv()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Codeforces Problem Extractor",
    page_icon="🧩",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Original logic — unchanged
# ---------------------------------------------------------------------------

llm = ChatOpenAI(
    model="openai/gpt-4o-mini",
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)


class ProblemConstraints(BaseModel):
    core_logic: str = Field(description="The underlying mathematical or algorithmic task without the story.")
    time_limit_hint: str = Field(description="Expected time complexity based on input constraints (e.g., O(N log N) if N=10^5).")
    edge_cases: list[str] = Field(description="Potential edge cases to watch out for, like N=0 or array containing negative numbers.")
    suggested_tags: list[str] = Field(description="Algorithm tags like 'prefix sum', 'sliding window', or 'greedy'.")


parser = PydanticOutputParser(pydantic_object=ProblemConstraints)


prompt = ChatPromptTemplate.from_messages([
    ('system', """
Extract codeforces question information from the paragraph
     {format_instructions}
"""),
    ("human", "{paragraph}")
])


def run_extraction(para: str):
    final_prompt = prompt.invoke(
        {
            "paragraph": para,
            "format_instructions": parser.get_format_instructions(),
        }
    )
    response = llm.invoke(final_prompt)
    question_data = parser.parse(response.content)
    return response, question_data


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
        .main > div { padding-top: 2rem; }
        .cf-tag {
            display: inline-block;
            background-color: #262730;
            color: #fafafa;
            border-radius: 999px;
            padding: 4px 12px;
            margin: 3px 4px 3px 0;
            font-size: 0.85rem;
            border: 1px solid #444;
        }
        .cf-card {
            background-color: rgba(127,127,127,0.06);
            border: 1px solid rgba(127,127,127,0.25);
            border-radius: 12px;
            padding: 1.1rem 1.3rem;
            margin-bottom: 1rem;
        }
        .cf-label {
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            opacity: 0.6;
            margin-bottom: 0.3rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🧩 Codeforces Problem Extractor")
st.caption("Paste a competitive-programming problem statement and get its core logic, complexity hint, edge cases, and tags — extracted by an LLM.")

if "history" not in st.session_state:
    st.session_state.history = []

with st.form("cf_form", clear_on_submit=False):
    para = st.text_area(
        "Give your question paragraph:",
        height=220,
        placeholder="Paste the full Codeforces problem statement here...",
    )
    submitted = st.form_submit_button("🔍 Extract", use_container_width=True)

if submitted:
    if not para or not para.strip():
        st.warning("Please paste a problem paragraph first.")
    else:
        with st.spinner("Analyzing problem statement..."):
            try:
                response, question_data = run_extraction(para)
                st.session_state.history.insert(0, {
                    "paragraph": para,
                    "data": question_data,
                    "raw": response.model_dump(),
                })
                st.success("Extraction complete.")
            except Exception as e:
                st.error(f"Something went wrong: {e}")

if st.session_state.history:
    latest = st.session_state.history[0]
    data = latest["data"]

    st.subheader("Extracted Details")

    st.markdown(
        f"""<div class="cf-card">
        <div class="cf-label">Core Logic</div>
        <div>{data.core_logic}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f"""<div class="cf-card">
            <div class="cf-label">Time Complexity Hint</div>
            <div>{data.time_limit_hint}</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with col2:
        tags_html = "".join(f'<span class="cf-tag">{t}</span>' for t in data.suggested_tags)
        st.markdown(
            f"""<div class="cf-card">
            <div class="cf-label">Suggested Tags</div>
            <div>{tags_html if tags_html else "—"}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    edge_html = "".join(f"<li>{e}</li>" for e in data.edge_cases) or "<li>None listed</li>"
    st.markdown(
        f"""<div class="cf-card">
        <div class="cf-label">Edge Cases</div>
        <ul>{edge_html}</ul>
        </div>""",
        unsafe_allow_html=True,
    )

    with st.expander("Raw JSON response"):
        st.code(json.dumps(latest["raw"], indent=2), language="json")

    if len(st.session_state.history) > 1:
        with st.expander(f"Previous extractions ({len(st.session_state.history) - 1})"):
            for i, item in enumerate(st.session_state.history[1:], start=1):
                st.markdown(f"**#{i}** — {item['paragraph'][:80]}{'...' if len(item['paragraph']) > 80 else ''}")
                st.json(item["raw"])
                st.divider()
else:
    st.info("No extraction yet — paste a problem statement above and click Extract.")