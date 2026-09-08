#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日签到脚本
- 零第三方依赖，仅用 Python 标准库
- 支持 GitHub Actions（读 Secrets 注入的环境变量）与本地运行（读本机登录态文件）
- 「已签到」一律判为成功，避免 Actions 误报失败
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_DOMAIN = "www.workbuddy.cn"
STATUS_PATH = "/v2/billing/meter/checkin-status"
CHECKIN_PATH = "/v2/billing/meter/daily-checkin"
REQUEST_TIMEOUT = 20
MAX_RETRY = 3

_WIN_AUTH_FILE = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "CodeBuddyExtension"
    / "Data"
    / "Public"
    / "auth"
    / "workbuddy-desktop.info"
)
_MAC_AUTH_FILE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "CodeBuddyExtension"
    / "Data"
    / "Public"
    / "auth"
    / "workbuddy-desktop.info"
)
_CONFIG_FILE = Path(__file__).resolve().parent / "config.json"


def log(msg: str) -> None:
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("utf-8", "replace").decode("utf-8", "replace"), flush=True)


# ---------------------------------------------------------------- 凭据加载

def _creds_from_env() -> dict | None:
    token = os.environ.get("WORKBUDDY_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    return {
        "access_token": token,
        "account_name": os.environ.get("WORKBUDDY_ACCOUNT_NAME", "云端账号").strip(),
        "uid": os.environ.get("WORKBUDDY_UID", "").strip() or None,
        "domain": os.environ.get("WORKBUDDY_DOMAIN", DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN,
        "enterprise_id": os.environ.get("WORKBUDDY_ENTERPRISE_ID", "").strip() or None,
    }


def _creds_from_config() -> dict | None:
    if not _CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log("[!] 读取 config.json 失败: %s" % e)
        return None
    token = (data.get("access_token") or "").strip()
    if not token:
        return None
    return {
        "access_token": token,
        "account_name": data.get("account_name") or "本地配置账号",
        "uid": (data.get("uid") or "").strip() or None,
        "domain": (data.get("domain") or DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN,
        "enterprise_id": (data.get("enterprise_id") or "").strip() or None,
    }


def _creds_from_local_auth() -> dict | None:
    for auth_file, label in ((_WIN_AUTH_FILE, "Windows"), (_MAC_AUTH_FILE, "macOS")):
        if not auth_file.exists():
            continue
        try:
            data = json.loads(auth_file.read_text(encoding="utf-8-sig"))
        except Exception as e:
            log("[!] 读取 %s auth 文件失败: %s" % (label, e))
            continue
        token = (data.get("auth", {}).get("accessToken") or "").strip()
        if not token:
            log("[x] %s auth 中未找到 accessToken" % label)
            continue
        account = data.get("account") or {}
        return {
            "access_token": token,
            "account_name": account.get("nickname") or "%s账号" % label,
            "uid": (account.get("uid") or "").strip() or None,
            "domain": (data.get("auth", {}).get("domain") or DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN,
            "enterprise_id": (
                (account.get("enterpriseId") or account.get("enterprise_id") or "").strip() or None
            ),
        }
    return None


def load_credentials() -> dict | None:
    # CI 环境：只用 Secrets 注入的环境变量，绝不依赖本地文件
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        creds = _creds_from_env()
        if creds:
            log("凭据来源：GitHub Secrets（账号: %s）" % creds["account_name"])
            return creds
        log("[x] CI 环境未提供 WORKBUDDY_ACCESS_TOKEN，请检查 Secrets 配置")
        return None

    creds = _creds_from_config() or _creds_from_env() or _creds_from_local_auth()
    if creds:
        log("凭据来源：本机（账号: %s，域名: %s）" % (creds["account_name"], creds["domain"]))
    else:
        log("[x] 未找到任何凭据，请配置 config.json 或环境变量")
    return creds


# ---------------------------------------------------------------- HTTP

def _build_headers(creds: dict) -> dict:
    headers = {
        "Authorization": "Bearer %s" % creds["access_token"],
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "WorkBuddy-Checkin/1.1",
    }
    if creds.get("uid"):
        headers["X-User-Id"] = creds["uid"]
    if creds.get("domain"):
        headers["X-Domain"] = creds["domain"]
    eid = creds.get("enterprise_id")
    if eid:
        headers["X-Enterprise-Id"] = eid
        headers["X-Tenant-Id"] = eid
    return headers


def _request_json(url: str, creds: dict) -> dict | None:
    headers = _build_headers(creds)
    for attempt in range(1, MAX_RETRY + 1):
        req = urllib.request.Request(url, data=b"{}", method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            log("   HTTP %s: %s %s" % (e.code, e.reason, body[:200]))
            if e.code in (401, 403):
                log("   [x] 凭据无效或已过期，请更新 WORKBUDDY_ACCESS_TOKEN")
                return None
            try:
                return json.loads(body) if body else None
            except Exception:
                return None
        except Exception as e:
            log("   [!] 第 %d/%d 次请求失败: %s: %s" % (attempt, MAX_RETRY, type(e).__name__, e))
            if attempt < MAX_RETRY:
                time.sleep(3 * attempt)
    return None


def _msg_of(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("message") or payload.get("msg") or "")


def already_checked_in(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("code") == 10001:
        return True
    msg = _msg_of(payload)
    if "已签到" in msg or "已经签到" in msg or "明天再来" in msg:
        return True
    data = payload.get("data")
    if isinstance(data, dict) and (data.get("today_checked_in") or data.get("checked_in")):
        return True
    return bool(payload.get("today_checked_in") or payload.get("checked_in"))


def unwrap_data(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    if code is not None and code not in (0, 200, 10001):
        log("   [!] 业务错误 code=%s: %s" % (code, _msg_of(payload) or "unknown"))
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


# ---------------------------------------------------------------- 主流程

def checkin() -> bool:
    log("=" * 56)
    log("WorkBuddy 每日签到 —— %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log("=" * 56)

    log("步骤 1/3: 加载凭据...")
    creds = load_credentials()
    if not creds:
        return False
    base = "https://%s" % creds["domain"]

    log("步骤 2/3: 查询签到状态...")
    status_raw = _request_json(base + STATUS_PATH, creds)
    if already_checked_in(status_raw):
        log("[ok] 今日已签到，无需重复领取。")
        return True
    status = unwrap_data(status_raw)
    if status is None:
        log("[!] 状态查询失败，仍继续尝试领取...")
    else:
        log(
            "   today_checked_in=%s, streak_days=%s, daily_credit=%s"
            % (status.get("today_checked_in"), status.get("streak_days"), status.get("daily_credit"))
        )

    log("步骤 3/3: 领取签到积分...")
    result_raw = _request_json(base + CHECKIN_PATH, creds)
    if already_checked_in(result_raw):
        log("[ok] 今日已签到。")
        return True

    result = unwrap_data(result_raw)
    if result is None:
        log("[x] 签到失败，请检查 token 是否过期。")
        return False

    if result.get("success") is False:
        log("[!] 领取未成功: %s" % (result.get("message") or result))
        return False

    log(
        "[ok] 签到成功! credit=%s, streak_days=%s %s"
        % (
            result.get("credit", result.get("today_credit", result.get("daily_credit"))),
            result.get("streak_days"),
            result.get("message") or "",
        )
    )
    return True


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(0 if checkin() else 1)
