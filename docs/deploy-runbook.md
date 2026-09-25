# 觅码 · 服务器一次性初始化与回滚 Runbook

前置：云服务器（Linux，已装 Nginx）、域名已 A 记录到服务器 IP、80/443/22 在安全组放行、本分支（含 `deploy/` 模板）已推送到 GitHub（§9 为验证步骤；clone 后若无 `deploy/` 目录说明部署提交尚未推送）。
按顺序执行；`<你的域名>`、`<服务器IP>` 替换为实际值。

## 1. 系统用户与依赖（root）

```bash
adduser --disabled-password --gecos "" deploy
apt update && apt install -y python3-venv git rsync certbot
mkdir -p /opt/meecode /var/www/meecode
chown deploy:deploy /opt/meecode /var/www/meecode
```

## 2. 拉代码与后端环境（deploy）

```bash
sudo -iu deploy
git clone https://github.com/alaala-daka/Meecode-Find_your_code.git /opt/meecode
cd /opt/meecode/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. 写 .env（deploy，密钥不进 git）

```bash
cp .env.example .env && chmod 600 .env
vi .env   # 填入 LLM_API_KEY、TAVILY_API_KEY、GITHUB_TOKEN 等（从本地 backend/.env 迁移）
```

## 4. 部署专用 SSH 密钥（deploy）

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N "" -C "github-actions-deploy"
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
cat ~/.ssh/deploy_key   # 私钥全文（含 BEGIN/END 行）→ GitHub Secret SSH_PRIVATE_KEY
```

## 5. systemd + 免密重启授权（root）

```bash
cat > /etc/sudoers.d/deploy-meecode <<'SUD'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart meecode-backend, /usr/bin/systemctl status meecode-backend
SUD
chmod 440 /etc/sudoers.d/deploy-meecode
cp /opt/meecode/deploy/meecode-backend.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now meecode-backend
curl -fsS http://127.0.0.1:8100/api/health   # 期望 {"ok": true, ...}
```

## 6. Nginx 最小配置（签证书前）

`/etc/nginx/sites-available/meecode`：

```nginx
server {
    listen 80;
    server_name <你的域名>;
    root /var/www/meecode;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }
}
```

```bash
ln -sf /etc/nginx/sites-available/meecode /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

## 7. 签发证书并切换最终配置

```bash
certbot certonly --webroot -w /var/www/meecode -d <你的域名>
# 用仓库模板替换，替换 <你的域名> 后：
cp /opt/meecode/deploy/nginx-meecode.conf /etc/nginx/sites-available/meecode
vi /etc/nginx/sites-available/meecode   # <你的域名> → 实际域名
nginx -t && systemctl reload nginx
certbot renew --dry-run   # 续期演练；certbot 装好即有自动续期 timer
```

## 8. GitHub Secrets（仓库 Settings → Secrets and variables → Actions）

| Secret | 值 |
|---|---|
| `SSH_HOST` | `deploy@<服务器IP>` |
| `SSH_PRIVATE_KEY` | 第 4 步 `deploy_key` 私钥全文 |
| `DEPLOY_DOMAIN` | `<你的域名>` |

## 9. 首次部署验证

```bash
# 本机推送后，GitHub → Actions 观察 deploy 工作流全绿
git push origin feat/frontend-ui
# 服务器侧确认：
systemctl status meecode-backend
journalctl -u meecode-backend -n 50 --no-pager
```

浏览器验证：打开 `https://<你的域名>` 首页 200 → 仓库详情 → 仓库解读 tab 自动建图 → 双击节点阅读器出真实长文 → 伴读追问流式回答 → 深链接刷新不 404。

## 10. 回滚

```bash
# 后端：回到指定 commit 并重启（服务器上）
cd /opt/meecode && git fetch origin && git checkout <旧commit-sha>
backend/.venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart meecode-backend
# 重新上线前恢复分支（否则下次部署 git pull --ff-only 失败）
git checkout feat/frontend-ui && git reset --hard origin/feat/frontend-ui
# 前端：本地 checkout 旧 commit 构建，rsync 覆盖
$env:VITE_USE_MOCK='false'; npm run build   # 本机 frontend/
rsync -az --delete -e "ssh -i <部署私钥>" frontend/dist/ deploy@<服务器IP>:/var/www/meecode/
```

## 11. 排障速查

- 后端起不来：`journalctl -u meecode-backend -n 100`；先查 `/opt/meecode/backend/.env` 是否存在且密钥有效。
- 解读接口 502：`systemctl is-active meecode-backend`；`ss -tlnp | grep 8100` 确认监听。
- 证书续期失败：`certbot renew --dry-run` 输出；确认 80 端口未被改动、DNS 仍指向本机。
- 部署后页面仍是旧版：浏览器强刷（dist 文件名带 hash，正常不会缓存错版本）。

## 12. 信息流后端(随 8100 单应用提供)

1. 服务器 `.env` 追加键：`SESSION_SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")`、`GITHUB_CLIENT_ID/SECRET`（GitHub → Settings → Developer settings → OAuth Apps → New：callback `https://<domain>/api/auth/callback`）、`GITHUB_TOKEN`（爬取用，无需任何 scope，read public 即可）、`FRONTEND_ORIGIN=https://<domain>`、`GITHUB_MOCK=false`、`LLM_MOCK=false`。
2. `systemctl restart meecode-backend` 后 `systemctl status` 确认 active；`curl -s https://<domain>/api/health` 返回 `{"ok":true,...}`。
3. Nginx 按模板更新 `/api` location 并 `nginx -t && systemctl reload nginx`。
4. cron（`crontab -e`，deploy 用户）：

```cron
0 3 * * * cd /opt/meecode/backend && .venv/bin/python -m app.feed.jobs.crawl >> /var/log/meecode-crawl.log 2>&1
0 4 * * * cd /opt/meecode/backend && .venv/bin/python -m app.feed.jobs.report >> /var/log/meecode-report.log 2>&1
*/5 * * * * cd /opt/meecode/backend && .venv/bin/python -m app.feed.jobs.moderate >> /var/log/meecode-moderate.log 2>&1
```

5. 冒烟：`curl -s "https://<domain>/api/feed" | head -c 200`（有 DB 内容后返回 cards）；`curl -s "https://<domain>/api/categories"` 返回 8 分类。

## 13. 安全基线上线（2026-09-21，手动步骤）

CI 只同步 `frontend/dist/` 与后端代码，**不碰 nginx 配置**。安全头需在服务器手动生效一次：

1. 拉取含安全基线的代码后替换配置：

```bash
cd /opt/meecode && git pull --ff-only
cp /opt/meecode/deploy/nginx-meecode.conf /etc/nginx/sites-available/meecode
vi /etc/nginx/sites-available/meecode   # <你的域名> → 实际域名（若尚未替换）
nginx -t && systemctl reload nginx
```

2. 验证响应头（应逐条命中）：

```bash
curl -sI https://<你的域名>/ | grep -iE 'content-security-policy|x-frame-options|strict-transport-security|x-content-type-options|referrer-policy|permissions-policy'
```

3. 验证限流（连续 25 次打解读会话端点，第 21 次起应 429 带 Retry-After）：

```bash
for i in $(seq 1 25); do curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<你的域名>/api/sessions; done | sort | uniq -c
```

4. 限流参数调整（`backend/.env` 增删后 `systemctl restart meecode-backend`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | 总开关 |
| `RATE_LIMIT_WINDOW` | `60` | 窗口秒数 |
| `RATE_LIMIT_LLM` / `_SESSION` / `_SUBMIT` / `_INTERACT` / `_BROWSE` / `_AUTH` / `_DELIST` / `_DEFAULT` | `20/30/5/60/240/10/5/120` | 各桶每窗口次数 |
| `RATE_LIMIT_MAX_KEYS` | `10000` | 限流器键数上限（超出淘汰最早键） |

> 前置条件：限流键取 nginx `$proxy_add_x_forwarded_for` 追加的 XFF 末段，仅在「后端仅监听 127.0.0.1、流量必经 nginx」时可信；若绕过 nginx 直连 8100，IP 限形同虚设。

5. 回滚：删除 nginx 中 6 个 `add_header` 行 + `nginx -t && systemctl reload nginx`；限流置 `RATE_LIMIT_ENABLED=false` 并重启后端。
