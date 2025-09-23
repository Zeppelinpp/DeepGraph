import subprocess

def run_code(code: str):
    """
    Python Code Interpreter, use print() to output the result

    Args:
        code: The code to run

    Returns:
        The result of the code
    """
    try:
        result = subprocess.run(["python", "-c", code], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    print(run_code("a = 1 + 1\nprint(a)"))