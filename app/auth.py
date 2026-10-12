# -*- coding: utf-8 -*-
"""
访问口令（简单鉴权）中间件。

为什么需要：这个应用被发布到了公网，任何拿到链接的人都能打开并消耗
.env 里的 DeepSeek 额度。加一层口令后，只有知道口令的人才能用。

设计（刻意保持简单，够用即可）：
  - 口令从环境变量 ACCESS_PASSWORD 读，没配就自动禁用（方便本地开发）。
  - 校验通过后签发一枚随机 session id，存进服务端内存会话表；Cookie 里只放这枚 id。
    Cookie 不设 max_age（会话级），关掉浏览器即失效。
  - 会话有闲置超时（SESSION_TTL），超时自动过期，需重新输口令。
  - 只比对摘要、Cookie 里不存明文口令；用 hmac.compare_digest 防时序攻击。
  - 放行白名单：口令页本身、静态样式、健康检查（供部署平台的探活使用）。

为什么不用「口令摘要直接当 Cookie」的旧做法：
  那样 Cookie 一旦签发就长期有效，且无法主动失效（改口令才能踢人）。
  改成服务端会话表后，既能做闲置超时，也能一键让所有会话失效。
"""

from __future__ import annotations

import os
import time
import hmac
import html
import hashlib
import secrets
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from fastapi.responses import JSONResponse

COOKIE_NAME = "xiaokun_sid"
SESSION_TTL = 60 * 60 * 8  # 会话闲置超时：8 小时不操作就需重新输口令

# 内存会话表：{session_id: 最后活跃时间戳}
# 单进程演示应用够用；多进程部署时换成 Redis 即可，其余逻辑不变。
_SESSIONS: dict[str, float] = {}


def _password() -> str:
    return (os.getenv("ACCESS_PASSWORD") or "").strip()


def enabled() -> bool:
    """配了口令才启用鉴权；没配就完全放行（本地开发用）。"""
    return bool(_password())


def _token() -> str:
    """口令的摘要——只用于比对，不写入 Cookie。"""
    return hashlib.sha256(("xiaolv::" + _password()).encode("utf-8")).hexdigest()


def verify(raw: str) -> bool:
    if not enabled():
        return False
    given = hashlib.sha256(("xiaolv::" + (raw or "")).encode("utf-8")).hexdigest()
    return hmac.compare_digest(given, _token())


def _prune() -> None:
    """清掉闲置超时的会话，避免内存表无限增长。"""
    now = time.time()
    dead = [sid for sid, last in _SESSIONS.items() if now - last > SESSION_TTL]
    for sid in dead:
        _SESSIONS.pop(sid, None)


def new_session() -> str:
    """校验通过后签发一枚新会话 id。"""
    _prune()
    sid = secrets.token_urlsafe(32)
    _SESSIONS[sid] = time.time()
    return sid


def drop_session(sid: str | None) -> None:
    if sid:
        _SESSIONS.pop(sid, None)


def authorized(request) -> bool:
    if not enabled():
        return True
    sid = request.cookies.get(COOKIE_NAME)
    if not sid:
        return False
    last = _SESSIONS.get(sid)
    if last is None:
        return False
    if time.time() - last > SESSION_TTL:
        _SESSIONS.pop(sid, None)
        return False
    _SESSIONS[sid] = time.time()  # 滑动续期：有操作就顺延
    return True


# 不需要口令就能访问的路径前缀
_PUBLIC_PREFIXES = (
    "/_gate",        # 口令页与校验接口
    "/_logout",      # 退出登录（本身要能在未授权时被调用）
    "/static/",      # 样式与脚本（否则口令页自己都渲染不出来）
    "/api/health",   # 部署平台探活
    "/favicon.ico",
)


def _is_public(path: str) -> bool:
    return path in ("/_gate", "/_logout") or path.startswith(_PUBLIC_PREFIXES)


# 登录后允许跳回的站内路径。不在这里的一律回首页，
# 避免带 `**` 之类的脏地址被记住后把人送进 404。
_KNOWN_PATHS = {"/", "/index.html"}


GATE_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>需要访问口令 · 小坤</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Noto Sans SC", -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    min-height: 100vh; display: grid; place-items: center;
    background: #f6f7f9; color: #1a1d24; padding: 20px;
  }
  .box {
    width: 100%; max-width: 372px; background: #fff;
    border: 1px solid #e6e8ec; border-radius: 16px;
    padding: 32px 28px 26px; text-align: center;
    box-shadow: 0 4px 16px rgba(16,24,40,.07);
  }
  .mark {
    width: 54px; height: 54px; margin: 0 auto 16px;
    display: grid; place-items: center; font-size: 26px;
    background: #e6f7f5; border-radius: 15px;
  }
  h1 { font-size: 18px; font-weight: 700; margin-bottom: 7px; }
  p.sub { font-size: 13px; color: #5b6270; line-height: 1.65; margin-bottom: 22px; }
  input {
    width: 100%; font-family: inherit; font-size: 14.5px;
    padding: 12px 14px; border: 1px solid #e6e8ec; border-radius: 10px;
    outline: none; transition: border-color .15s, box-shadow .15s;
    text-align: center; letter-spacing: 2px;
  }
  input:focus { border-color: #0d9488; box-shadow: 0 0 0 3px rgba(13,148,136,.16); }
  button {
    width: 100%; margin-top: 12px; font-family: inherit; font-size: 14px; font-weight: 500;
    padding: 12px; border: none; border-radius: 10px; cursor: pointer;
    background: #0d9488; color: #fff; transition: background .15s;
  }
  button:hover { background: #0b7f75; }
  button:disabled { background: #d3d8de; cursor: not-allowed; }
  .err {
    margin-top: 13px; font-size: 12.5px; color: #c0392b;
    background: #fdeceb; border-radius: 8px; padding: 9px 11px; display: none;
  }
  .err.show { display: block; }
  .foot { margin-top: 20px; font-size: 11px; color: #98a0ae; line-height: 1.6; }
</style>
</head>
<body>
  <div class="box">
    <div class="mark">🔒</div>
    <h1>{%TITLE%}</h1>
    <p class="sub">这个应用已开启访问口令，请输入口令后继续。<br>会话有效期为一次浏览，关闭浏览器后需重新输入。</p>
    <form id="f" autocomplete="off">
      <input id="pw" type="password" placeholder="输入访问口令" autofocus />
      <button id="btn" type="submit">进入</button>
    </form>
    <div class="err" id="err">{%ERROR%}</div>
    <div class="foot">口令由应用所有者提供</div>
  </div>
<script>
  const f = document.getElementById('f'), pw = document.getElementById('pw');
  const btn = document.getElementById('btn'), err = document.getElementById('err');
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!pw.value) return;
    btn.disabled = true; btn.textContent = '校验中…'; err.classList.remove('show');
    try {
      const r = await fetch('/_gate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw.value })
      });
      if (r.ok) { location.href = '{%NEXT%}'; return; }
      err.textContent = '口令不正确，请重试。';
      err.classList.add('show');
    } catch {
      err.textContent = '网络错误，请重试。';
      err.classList.add('show');
    }
    btn.disabled = false; btn.textContent = '进入';
    pw.select();
  });
</script>
</body>
</html>
"""


def _safe_next(next_url: str) -> str:
    """把登录后的跳转目标收敛到已知路径，避免脏地址把人带进 404。

    场景：有人从聊天/文档里复制链接时带上了 markdown 的 `**`，
    变成 /**. 若原样回跳，输完口令只会看到 {"detail":"Not Found"}。
    """
    if not next_url:
        return "/"
    # 只允许站内相对路径，挡掉 //evil.com 这类协议相对跳转
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    path = next_url.split("?", 1)[0].split("#", 1)[0]
    if path not in _KNOWN_PATHS:
        return "/"
    return next_url


def gate_html(error: str = "", next_url: str = "/") -> str:
    return (
        GATE_PAGE
        .replace("{%TITLE%}", "需要访问口令")
        .replace("{%ERROR%}", html.escape(error))
        .replace("{%NEXT%}", html.escape(_safe_next(next_url), quote=True))
    )


class PasswordGate(BaseHTTPMiddleware):
    """统一拦截：未通过口令校验的请求一律跳转到口令页。"""

    async def dispatch(self, request, call_next):
        if not enabled() or _is_public(request.url.path) or authorized(request):
            return await call_next(request)

        # 接口请求返回 401，让前端能识别；页面请求跳转到口令页
        if request.url.path.startswith("/api/"):
            return Response(
                content='{"detail":"未通过访问口令校验"}',
                status_code=401,
                media_type="application/json",
            )

        next_url = request.url.path
        if request.url.query:
            next_url += "?" + request.url.query
        return RedirectResponse("/_gate?next=" + quote(next_url, safe=""), status_code=302)


def register_gate(app) -> None:
    """挂载中间件与口令页路由。"""
    app.add_middleware(PasswordGate)

    @app.get("/_gate")
    async def gate_page(request: Request, next: str = "/"):
        # 未启用鉴权，或已经通过校验的，直接送去目标页，不用再看口令页
        if not enabled() or authorized(request):
            return RedirectResponse(_safe_next(next), status_code=302)
        return HTMLResponse(gate_html(next_url=next or "/"))

    @app.post("/_gate")
    async def gate_submit(payload: dict):
        if not enabled():
            return JSONResponse({"ok": True})
        if verify(str(payload.get("password", ""))):
            sid = new_session()
            resp = JSONResponse({"ok": True})
            # 不设 max_age：会话级 Cookie，关掉浏览器就失效
            resp.set_cookie(
                COOKIE_NAME, sid,
                httponly=True, samesite="lax", path="/",
            )
            return resp
        return JSONResponse({"ok": False, "detail": "口令不正确"}, status_code=401)

    @app.post("/_logout")
    async def logout(request: Request):
        """主动退出：作废当前会话并清 Cookie。"""
        drop_session(request.cookies.get(COOKIE_NAME))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp
