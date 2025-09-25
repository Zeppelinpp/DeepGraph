#!/usr/bin/env python3
"""
启动DeepGraph Web日志监控服务器
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def main():
    try:
        from src.workflow.server import start_server

        print("🚀 启动DeepGraph Web日志监控系统...")
        print("📊 功能特性:")
        print("   • 实时日志监控")
        print("   • 美观的Web界面")
        print("   • 任务执行追踪")
        print("   • 工具调用详情")
        print("   • 框架提取溯源")
        print("   • WebSocket实时推送")
        print()

        # 启动服务器
        start_server(host="localhost", port=9000, reload=True)

    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保安装了所需依赖:")
        print("pip install fastapi uvicorn websockets jinja2")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
