"""
YouTube Strategy Hub - FastAPI 웹 서버
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from api import channel, competitor, planner, trend, keyword, copywriter, history_api, system_api

app = FastAPI(title="YouTube Strategy Hub")

app.include_router(channel.router,     prefix="/api/channel")
app.include_router(competitor.router,  prefix="/api/competitor")
app.include_router(planner.router,     prefix="/api/planner")
app.include_router(trend.router,       prefix="/api/trend")
app.include_router(keyword.router,     prefix="/api/keyword")
app.include_router(copywriter.router,  prefix="/api/copywriter")
app.include_router(history_api.router, prefix="/api/history")
app.include_router(system_api.router,  prefix="/api/system")

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
