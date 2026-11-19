"""本机待看文章窗口：只有明确点击才打开原文或修改已读。"""
import logging
import os
from article_parser import is_safe_article_url
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
_window_process = None
_window_lock = threading.Lock()


def open_inbox_window(db_path):
    global _window_process
    with _window_lock:
        if _window_process is not None and _window_process.poll() is None:
            return True
        try:
            # 窗口不用服务凭据；使用固定解释器和脚本路径，不经过命令行解释器。
            allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "LANG", "DISPLAY", "TCL_LIBRARY", "TK_LIBRARY", "PATH"}
            env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
            _window_process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                                str(Path(db_path).absolute())], env=env,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except OSError:
            log.warning("启动本地待看窗口失败")
            return False


def _show_window(db_path, store_factory):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("综测提醒 · 待看文章")
    root.geometry("820x440")
    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
    status = tk.StringVar(master=root)
    ttk.Label(frame, textvariable=status).pack(anchor="w")
    tree = ttk.Treeview(frame, columns=("time", "source", "title"), show="headings", selectmode="browse")
    for key, label, width in (("time", "接收时间", 150), ("source", "来源", 130), ("title", "标题", 450)):
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=key == "title")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    actions = ttk.Frame(frame)
    actions.pack(side="bottom", fill="x", pady=6)
    scroll.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
    store = None
    indexed = {}

    def refresh():
        nonlocal store, indexed
        try:
            if store is None:
                store = store_factory(db_path)
            rows = store.unread()
        except Exception:
            status.set("读取待看清单失败，可稍后刷新。")
            return
        tree.delete(*tree.get_children())
        indexed = {r["id"]: r for r in rows}
        for r in rows:
            received = r["received_at"]
            if isinstance(received, (float, int)):
                received = datetime.fromtimestamp(received).strftime("%Y-%m-%d %H:%M:%S")
            tree.insert("", "end", iid=r["id"], values=(received, r["account"], r["title"]))
        status.set(f"{len(rows)} 篇待看。打开原文不会自动标记已看。")

    def selected():
        sel = tree.selection()
        return indexed.get(sel[0]) if sel else None

    def open_article():
        row = selected()
        if row is None:
            return
        if not is_safe_article_url(row.get("url")):
            status.set("无法打开：原文地址无效。")
            return
        try:
            if not webbrowser.open(row["url"]):
                status.set("打开原文失败，请检查默认浏览器。")
        except Exception:
            status.set("打开原文失败，请检查默认浏览器。")

    def mark():
        row = selected()
        if row is not None:
            try:
                store.mark_read(row["id"])
            except Exception:
                status.set("标记失败，文章仍在待看清单。")
                return
            refresh()

    for label, fn in (("刷新", refresh), ("打开原文", open_article), ("标记已看", mark)):
        ttk.Button(actions, text=label, command=fn).pack(side="left", padx=4)
    try:
        refresh()
        root.mainloop()
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                log.warning("关闭待看清单失败")


if __name__ == "__main__" and len(sys.argv) == 2:
    from inbox_store import InboxStore
    _show_window(sys.argv[1], InboxStore)
