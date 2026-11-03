"""Run both the API (port 8000) and AI Service (port 8001) in a single terminal.

Usage:
    python run_dev.py
"""

import os
import subprocess
import sys
import time


def main() -> None:
    print("=" * 65)
    print("Starting BrAInBox Backend Services...")
    print("  * AI Service : http://localhost:8001")
    print("  * API Service: http://localhost:8000")
    print("  * Swagger UI : http://localhost:8000/docs")
    print("=" * 65)
    print("Press CTRL+C at any time to stop both services.\n")

    python_executable = sys.executable

    # Start AI service on 8001
    ai_process = subprocess.Popen(
        [python_executable, "-m", "uvicorn", "ai_service.main:app", "--reload", "--port", "8001"],
        cwd=os.getcwd(),
    )

    # Small delay to let AI service bind
    time.sleep(1.5)

    # Start API service on 8000
    api_process = subprocess.Popen(
        [python_executable, "-m", "uvicorn", "api.main:app", "--reload", "--port", "8000"],
        cwd=os.getcwd(),
    )

    try:
        # Keep runner alive while either process is running
        while True:
            if ai_process.poll() is not None or api_process.poll() is not None:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping services...")
    finally:
        for p in (api_process, ai_process):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("Both services stopped.")


if __name__ == "__main__":
    main()
