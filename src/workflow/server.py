import asyncio
import uvicorn
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi import Request
from src.workflow.workflow import DeepGraphWorkflow
from src.utils.web_logger import web_log_manager


app = FastAPI(title="DeepGraph Web Logger", version="1.0.0")

static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"

static_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# Workflow instance
workflow = DeepGraphWorkflow()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/sessions")
async def get_sessions():
    """Get all sessions"""
    return {"sessions": web_log_manager.get_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get specific session details"""
    session = web_log_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/cancel")
async def cancel_analysis():
    """Cancel current running analysis"""
    if hasattr(app.state, "current_task") and app.state.current_task:
        app.state.current_task.cancel()
        return {"message": "Analysis has been cancelled"}
    else:
        return {"message": "No running analysis"}


@app.post("/api/run")
async def run_analysis(data: Dict[str, Any]):
    """Run analysis"""
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        # Async run workflow (session management in run_with_web_logging)
        task = asyncio.create_task(run_workflow_async(query))
        # Store task reference for possible cancellation
        app.state.current_task = task

        return {"message": "Analysis has been started"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


async def run_workflow_async(query: str):
    """Async run workflow, support graceful error handling"""
    try:
        # Use workflow run method with Web logging
        result = await workflow.run_with_web_logging(query)
        print(f"Workflow execution completed: {query}")

    except asyncio.CancelledError:
        print(f"Workflow has been cancelled: {query}")

    except KeyboardInterrupt:
        print(f"Workflow has been interrupted by user: {query}")

    except Exception as e:
        # Error already handled in run_with_web_logging
        print(f"Workflow execution failed: {query} - {e}")

    finally:
        # Clean up task reference
        if hasattr(app.state, "current_task"):
            app.state.current_task = None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint, for real-time log pushing"""
    await websocket.accept()
    web_log_manager.add_websocket(websocket)

    try:
        # Send current session list
        sessions = web_log_manager.get_sessions()
        await websocket.send_json({"type": "sessions_list", "sessions": sessions})

        # Keep connection active
        while True:
            # Wait for client message (heartbeat, etc.)
            try:
                data = await websocket.receive_text()
                # Can handle client sent commands
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        web_log_manager.remove_websocket(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "sessions_count": len(web_log_manager.sessions),
    }


def start_server(host: str = "0.0.0.0", port: int = 9000, reload: bool = False):
    """Start server"""
    print(f"🚀 Start DeepGraph Web Logger server...")
    print(f"📊 Dashboard address: http://{host}:{port}")
    print(f"🔗 WebSocket address: ws://{host}:{port}/ws")

    uvicorn.run(
        "src.workflow.server:app", host=host, port=port, reload=reload, log_level="info"
    )


if __name__ == "__main__":
    start_server(reload=True)
