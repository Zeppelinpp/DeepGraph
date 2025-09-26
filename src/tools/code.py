import subprocess
from typing import Optional
from llama_index.core.workflow import Context


def run_code(code: str, context: Optional[Context] = None):
    """
    Python Code Interpreter
    Use print() to output each demanded result
    Use polars to analyze data
    Don't try to write files or delete files, only use the code to analyze data and print the result

    Args:
        code: The code to run
        context: The context of the workflow

    Returns:
        The result of the code
    """
    try:
        # 获取项目根目录并拼接正确的虚拟环境python路径
        import os
        import sys

        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        # 根据操作系统选择正确的python可执行文件路径
        if sys.platform == "win32":
            python_executable = os.path.join(
                project_root, ".venv", "Scripts", "python.exe"
            )
        else:
            python_executable = os.path.join(project_root, ".venv", "bin", "python")

        # 如果虚拟环境中的python不存在，回退到系统python
        if not os.path.exists(python_executable):
            python_executable = sys.executable
        result = subprocess.run(
            [python_executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr if e.stderr else "No error details available"
        return f"Code execution error: {stderr_output}"
    except UnicodeDecodeError as e:
        return f"Encoding error: {e}. Try using different encoding or check your code for non-ASCII characters."
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    print(run_code("import polars as pl\na = 1 + 1\nprint(a)"))
