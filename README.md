# WorkBuddy 每日签到（GitHub Actions 版）

电脑关机也能自动领取 WorkBuddy 每日 100 积分。零第三方依赖，纯 Python 标准库。

## 原理

```
读取 accessToken → POST 查询签到状态 → POST 领取积分 → 已签到则跳过
```

- 查状态：`POST https://<domain>/v2/billing/meter/checkin-status`
- 领积分：`POST https://<domain>/v2/billing/meter/daily-checkin`
- 认证：`Authorization: Bearer <accessToken>`

## 部署步骤

### 1. 建仓库

GitHub 新建仓库，**必须选 Private**（accessToken 等同登录态）。

### 2. 上传 4 个文件

| 文件 | 路径 |
| --- | --- |
| `checkin.py` | 根目录 |
| `.github/workflows/checkin.yml` | 需连目录一起建 |
| `.gitignore` | 根目录 |
| `README.md` | 根目录（可选） |

### 3. 配置 Secrets

Settings → Secrets and variables → Actions → New repository secret

| Secret 名 | 必填 | 值 |
| --- | --- | --- |
| `WORKBUDDY_ACCESS_TOKEN` | 是 | 本机 `auth.accessToken` |
| `WORKBUDDY_UID` | 是 | 本机 `account.uid` |
| `WORKBUDDY_DOMAIN` | 是 | `www.workbuddy.cn` |
| `WORKBUDDY_ACCOUNT_NAME` | 否 | 昵称，仅日志展示 |

本机登录态文件位置：
- Windows：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`
- macOS：`~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`

也可在本机运行 `python gen_secrets.py` 自动生成待填清单。

### 4. 启用并验证

Actions 页 → 启用 workflow → **Run workflow** 手动跑一次。

看到 `[ok] 签到成功` 或 `[ok] 今日已签到` 即为成功。

## 执行时间

| 北京时间 | UTC cron | 说明 |
| --- | --- | --- |
| 09:05 | `5 1 * * *` | 主执行 |
| 16:05 | `5 8 * * *` | 补签机会 |

两次都避开整点/整半点以减少排队延迟。每天只能领 1 次，重复执行会被识别为「已签到」并判成功，不会重复领取、不会误报失败。

## 维护

**accessToken 有效期 60 天。** WorkBuddy 每次启动会自动续期本地 token，但 GitHub Secret 那份不会同步更新。到期后 Actions 会静默 401 失败 → 断签。

更新方法：重新打开本机登录态文件，复制新的 `accessToken`，更新 Secret `WORKBUDDY_ACCESS_TOKEN`，不用改代码。

## 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| `HTTP 401/403` | token 过期或无效，更新 Secret |
| 一直没触发 | 仓库 60 天无活动 GitHub 会自动禁用 schedule，到 Actions 页手动启用 |
| 触发时间不准 | 定时触发有数分钟到数十分钟延迟，属正常 |
| 状态接口说未签到但领取时说已签到 | 已知现象，状态接口字段滞后；脚本以领取接口返回为准，判为成功 |

## 安全

- accessToken 等同登录态，只存 GitHub Secrets
- 仓库必须 Private，绝不公开
- 不要把 `config.json`、`secrets-待填.txt` 提交进仓库（已在 .gitignore 中）
