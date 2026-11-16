"""Desktop launcher for FaceCheck without a console window."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import Label, Tk, messagebox


ROOT = Path(__file__).resolve().parent
HEALTH_URL = "http://127.0.0.1:8765/api/health"
ADMIN_URL = "http://127.0.0.1:8765/?view=admin#dashboard"
LOG_PATH = ROOT / "data" / "facecheck_desktop.log"
STARTUP_TIMEOUT_SECONDS = 120


def facecheck_running() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=0.7) as response:
            payload = json.load(response)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return payload.get("ok") is True and payload.get("service") == "FaceCheck Web UI"


def log_tail(max_characters: int = 1800) -> str:
    try:
        content = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Không đọc được nhật ký khởi động."
    return content[-max_characters:].strip()


def main() -> int:
    if facecheck_running():
        webbrowser.open(ADMIN_URL)
        return 0

    root = Tk()
    root.title("FaceCheck Server")
    root.geometry("430x150")
    root.resizable(False, False)
    root.configure(bg="#F6F8FC")

    title = Label(
        root,
        text="FaceCheck Server",
        font=("Segoe UI", 17, "bold"),
        fg="#172033",
        bg="#F6F8FC",
    )
    title.pack(pady=(25, 8))
    status = Label(
        root,
        text="Đang tìm camera và tải hệ thống AI...",
        font=("Segoe UI", 10),
        fg="#526078",
        bg="#F6F8FC",
    )
    status.pack()

    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("a", encoding="utf-8")
    log_file.write(f"\n--- FaceCheck desktop start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()

    python_path = ROOT / "venv" / "Scripts" / "python.exe"
    command = [str(python_path), str(ROOT / "facecheck.py"), "wifi"]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    environment = os.environ.copy()
    environment["FACECHECK_FORCE_BROWSER_UI"] = "1"
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
    except OSError as error:
        log_file.close()
        messagebox.showerror("FaceCheck Server", f"Không thể khởi động server:\n{error}")
        root.destroy()
        return 1

    started_at = time.monotonic()

    def check_startup() -> None:
        if facecheck_running():
            status.configure(text="Server đã sẵn sàng. Đang mở giao diện...")
            log_file.close()
            root.after(1800, root.destroy)
            return

        exit_code = process.poll()
        if exit_code is not None:
            log_file.close()
            details = log_tail() or f"Tiến trình đã dừng với mã {exit_code}."
            messagebox.showerror(
                "FaceCheck không khởi động được",
                f"Server đã dừng trước khi sẵn sàng.\n\n{details}",
            )
            root.destroy()
            return

        elapsed = int(time.monotonic() - started_at)
        status.configure(text=f"Đang khởi động hệ thống... {elapsed} giây")
        if elapsed >= STARTUP_TIMEOUT_SECONDS:
            log_file.flush()
            messagebox.showwarning(
                "FaceCheck Server",
                "Server vẫn đang chạy nhưng chưa sẵn sàng. "
                "Hãy kiểm tra nguồn và Wi-Fi của ESP32-S3 CAM.\n\n"
                f"Nhật ký: {LOG_PATH}",
            )
            log_file.close()
            root.destroy()
            return
        root.after(700, check_startup)

    root.after(400, check_startup)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
