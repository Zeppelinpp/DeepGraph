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


# 创建FastAPI应用
app = FastAPI(title="DeepGraph Web Logger", version="1.0.0")

# 设置静态文件和模板
static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"

# 创建目录（如果不存在）
static_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# 工作流实例
workflow = DeepGraphWorkflow()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """主仪表板页面"""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/sessions")
async def get_sessions():
    """获取所有会话"""
    return {"sessions": web_log_manager.get_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取特定会话详情"""
    session = web_log_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话未找到")
    return session


@app.post("/api/cancel")
async def cancel_analysis():
    """取消当前运行的分析"""
    if hasattr(app.state, "current_task") and app.state.current_task:
        app.state.current_task.cancel()
        return {"message": "分析已取消"}
    else:
        return {"message": "没有正在运行的分析"}


@app.post("/api/run")
async def run_analysis(data: Dict[str, Any]):
    """运行分析"""
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="查询不能为空")

    try:
        # 异步运行工作流（会话管理在run_with_web_logging中处理）
        task = asyncio.create_task(run_workflow_async(query))
        # 存储任务引用以便可能的取消操作
        app.state.current_task = task

        return {"message": "分析已开始"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"运行失败: {str(e)}")


async def run_workflow_async(query: str):
    """异步运行工作流，支持优雅的错误处理"""
    try:
        # 使用带Web日志记录的工作流运行方法
        result = await workflow.run_with_web_logging(query)
        print(f"工作流执行完成: {query}")

    except asyncio.CancelledError:
        print(f"工作流被取消: {query}")

    except KeyboardInterrupt:
        print(f"工作流被用户中断: {query}")

    except Exception as e:
        # 错误已经在run_with_web_logging中处理
        print(f"工作流执行失败: {query} - {e}")

    finally:
        # 清理任务引用
        if hasattr(app.state, "current_task"):
            app.state.current_task = None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点，用于实时日志推送"""
    await websocket.accept()
    web_log_manager.add_websocket(websocket)

    try:
        # 发送当前会话列表
        sessions = web_log_manager.get_sessions()
        await websocket.send_json({"type": "sessions_list", "sessions": sessions})

        # 保持连接活跃
        while True:
            # 等待客户端消息（心跳等）
            try:
                data = await websocket.receive_text()
                # 可以处理客户端发送的命令
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
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "sessions_count": len(web_log_manager.sessions),
    }


def start_server(host: str = "0.0.0.0", port: int = 9000, reload: bool = False):
    """启动服务器"""
    print(f"🚀 启动DeepGraph Web Logger服务器...")
    print(f"📊 仪表板地址: http://{host}:{port}")
    print(f"🔗 WebSocket地址: ws://{host}:{port}/ws")

    uvicorn.run(
        "src.workflow.server:app", host=host, port=port, reload=reload, log_level="info"
    )


if __name__ == "__main__":
    start_server(reload=True)
