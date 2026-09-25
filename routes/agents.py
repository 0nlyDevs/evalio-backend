"""Chat with the jury + direct access to individual agents."""

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from agents import chat_agent, market_agent
from db import fetch_one
from routes.schemas import ChatIn
from services import llm
from services.repo_ingest import IngestError, ingest_repository

router = APIRouter()


def _history(body: ChatIn) -> list[dict]:
    return [t.model_dump() for t in body.chathistory]


@router.post("/chat-agent", tags=["Chat Agent"], summary="Ask the jury about a project")
def chat(body: ChatIn):
    project = hackathon = None
    if body.project_id:
        project = fetch_one("SELECT * FROM projects WHERE project_id = %s", (body.project_id,))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.get("hackathon_id"):
            hackathon = fetch_one("SELECT * FROM hackathons WHERE id = %s", (project["hackathon_id"],))
    try:
        answer, cited = chat_agent.answer(project, hackathon, body.question, _history(body))
    except llm.LLMError as exc:
        raise HTTPException(status_code=503, detail=f"The AI jury is unavailable: {exc}") from exc
    history = [*_history(body), {"input": body.question, "output": answer}]
    return {"answer": answer, "sources": cited, "chathistory": history}


@router.post("/chat-agent/simple", tags=["Chat Agent"], summary="General judging assistant (no project)")
def simple_chat(body: ChatIn):
    try:
        answer, _ = chat_agent.answer(None, None, body.question, _history(body))
    except llm.LLMError as exc:
        raise HTTPException(status_code=503, detail=f"The AI assistant is unavailable: {exc}") from exc
    return {"answer": answer, "chathistory": [*_history(body), {"input": body.question, "output": answer}]}


class RepoIn(BaseModel):
    repo_url: str = Field(min_length=5, max_length=300)


@router.post("/code-agent/analyze", tags=["Code Agent"], summary="Ingest a repository and return its snapshot")
async def code_agent_analyze(body: RepoIn):
    try:
        snapshot = await run_in_threadpool(ingest_repository, body.repo_url, None, False)
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    snapshot.pop("readme", None)
    snapshot.pop("manifests", None)
    snapshot.get("history", {}).pop("commit_dates", None)
    return {"message": "Repository analysed", "snapshot": snapshot}


class IdeaIn(BaseModel):
    idea: str = Field(min_length=10, max_length=4000)
    theme: str = ""


@router.post("/market-agent/analyze", tags=["Market Agent"], summary="Run the Market Judge on an idea")
async def market_agent_analyze(body: IdeaIn):
    if not llm.is_configured():
        raise HTTPException(status_code=503, detail="LLM_API_KEY is not configured")
    result = await run_in_threadpool(market_agent.analyze_idea, body.idea, body.theme)
    return {"message": "Market analysis complete", "analysis": result}
