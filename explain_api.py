import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Load environment variables from a .env file
load_dotenv()

app = FastAPI(
    title="Code Explainer API",
    description="API to explain code snippets based on user skill level.",
    version="1.0.0"
)

class ExplainRequest(BaseModel):
    code_snippet: str
    skill_level: Literal["Beginner", "Intermediate", "Advanced"]

class ExplainResponse(BaseModel):
    explanation: str

@app.post("/explain", response_model=ExplainResponse)
async def explain_code(request: ExplainRequest):
    # Require a free Hugging Face API key
    api_key = os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="HUGGINGFACEHUB_API_TOKEN environment variable is not set. Get a free token at https://huggingface.co/settings/tokens"
        )
        
    prompt_template = """
You are an expert programming mentor. You will be provided with a code snippet and the target user's skill level: {skill_level}.
Using a Chain of Thought approach, explain the logic of the code step-by-step.

Target your explanation for a {skill_level} software engineer:
- If Beginner: Focus on fundamental concepts, basic syntax, and what the code does line-by-line. Avoid complex jargon unless you explain it simply.
- If Intermediate: Focus on the overall structure, how the parts interact, and why standard structures are used.
- If Advanced: Focus heavily on design patterns (like Dependency Injection, Async/Await, etc.), performance implications, algorithmic efficiency, and advanced language features.

Chain of Thought process:
1. **Analyze the Code**: Briefly identify the language, purpose, and key components.
2. **Identify Patterns**: Determine what programming paradigms or design patterns are present (e.g., async/await, loops, DI, classes).
3. **Formulate Approach**: Think step-by-step about how to explain these patterns tailored strictly to a {skill_level} audience. What jargon is appropriate? What concepts need expanding?
4. **Final Explanation**: Provide the finalized explanation tailored to the user, ensuring the "why" behind patterns is clear appropriate for the {skill_level} level.

Code Snippet:
```
{code_snippet}
```
"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    
    # Using an excellent, free, open-source model through HuggingFace with the conversational task flag
    llm = HuggingFaceEndpoint(
        repo_id="Qwen/Qwen2.5-72B-Instruct",
        huggingfacehub_api_token=api_key,
        task="conversational",
        temperature=0.2,
        max_new_tokens=1024,
        return_full_text=False
    )
    chat_model = ChatHuggingFace(llm=llm)
    
    chain = prompt | chat_model | StrOutputParser()
    
    try:
        response = await chain.ainvoke({
            "skill_level": request.skill_level,
            "code_snippet": request.code_snippet
        })
        return ExplainResponse(explanation=response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating explanation: {str(e)}")

# To run: uvicorn explain_api:app --reload
