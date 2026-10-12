# -*- coding: utf-8 -*-
"""本地启动入口：python run.py

★ 必须先加载 .env ★
之前这里没读 .env，本地跑全靠 shell 里已有的环境变量兜底——
结果 ACCESS_PASSWORD 明明写进了 .env 却不生效，鉴权静默失效。
load_dotenv 放在 import app 之前，保证模块级读到的 os.getenv 都是最新值。
"""

import os
from pathlib import Path

import dotenv

# 显式指定项目根的 .env，避免受当前工作目录影响
dotenv.load_dotenv(Path(__file__).parent / ".env", override=False)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    # 优先用平台注入的 PORT（发布上线时由沙箱提供），本地回落到 8000
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
