import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel,Field
from typing import List,Optional
from langchain_core.output_parsers import PydanticOutputParser

load_dotenv()

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
    ('system',"""
Extract codeforces question information from the paragraph
     {format_instructions}
"""),
("human","{paragraph}")
]
)

para = input("Give your question paragraph : ")

final_prompt = prompt.invoke(
    {"paragraph" : para,
     'format_instructions': parser.get_format_instructions()
     }
)

response = llm.invoke(final_prompt)
question_data = parser.parse(response.content)


import json
print(json.dumps(response.model_dump(), indent=2))