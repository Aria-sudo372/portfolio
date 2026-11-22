#!/usr/bin/env python3
"""GitHub 设备授权 + Pages 自动部署（自持协议轮询，不依赖 gh 交互）
授权范围仅 repo / workflow / read:user；token 只在内存中使用，不写入任何文件。"""
import json, os, subprocess, sys, time, urllib.request, urllib.parse

CID = "178c6fc778ccc68e1d6a"          # 本机 gh 内置的 CLI client_id
ROOT = "/home/user/Doubao/chats/38435942269034754"
SITE = os.path.join(ROOT, "site")
LOG = os.path.join(SITE, "deploy2.log")
REPO = "portfolio"


def say(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def post(url, data, token=None, accept="application/json"):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Accept", accept)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if token:
        req.add_header("Authorization", "token " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    if "&" in raw and "=" in raw and not raw.lstrip().startswith(("{", "[")):
        return dict(urllib.parse.parse_qsl(raw))
    return json.loads(raw) if raw.strip() else {}


def api(method, path, token, payload=None):
    url = "https://api.github.com" + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", "token " + token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode("utf-8", "replace")
        return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"msg": raw[:200]}


def main():
    open(LOG, "w").close()
    say("STEP1 申请设备码")
    d = post("https://github.com/login/device/code",
             {"client_id": CID, "scope": "repo workflow read:user"})
    if "user_code" not in d:
        say("FAIL 设备码申请失败: %s" % d); return 1
    code = d["user_code"]
    say("USERCODE %s" % code)
    say("VERIFY %s" % d.get("verification_uri", "https://github.com/login/device"))
    deadline = time.time() + min(int(d.get("expires_in", 900)), 870)
    interval = max(int(d.get("interval", 5)), 3)
    token = None
    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = post("https://github.com/login/oauth/access_token",
                     {"client_id": CID, "device_code": d["device_code"],
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
                     accept="application/json")
        except Exception as e:
            say("WARN 轮询异常 %s" % str(e)[:80]); continue
        if r.get("access_token"):
            token = r["access_token"]; break
        err = r.get("error", "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5; continue
        say("FAIL 授权被拒: %s" % r); return 1
    if not token:
        say("FAIL 超时未完成授权"); return 1
    say("AUTH 授权成功（token 仅在内存）")

    _, me = api("GET", "/user", token)
    login = me.get("login", "")
    if not login:
        say("FAIL 取不到用户名: %s" % me); return 1
    say("USER %s" % login)

    st, repo = api("GET", "/repos/%s/%s" % (login, REPO), token)
    if st == 200:
        say("REPO 已存在，复用")
    else:
        st, repo = api("POST", "/user/repos", token,
                       {"name": REPO, "public": True, "has_issues": False,
                        "has_wiki": False, "auto_init": False,
                        "description": "杨之涵 · 作品陈列网站"})
        if st not in (200, 201):
            say("FAIL 建仓 %s %s" % (st, repo)); return 1
        say("REPO 已创建")

    # 用 askpass 推送到 main，避免 token 出现在命令行
    helper = os.path.join(SITE, "askpass.sh")
    env = dict(os.environ, GIT_TOKEN=token, GIT_ASKPASS=helper)
    with open(helper, "w") as f:
        f.write("#!/bin/sh\ncase \"$1\" in\n*Username*) echo x-access-token;;\n*) echo \"$GIT_TOKEN\";;\nesac\n")
    os.chmod(helper, 0o700)
    remote = "https://github.com/%s/%s.git" % (login, REPO)

    def git(*a):
        p = subprocess.run(["git", "-C", SITE] + list(a), capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    rc, out = git("remote", "remove", "origin")
    rc, out = git("remote", "add", "origin", remote)
    rc, out = git("push", "-f", "origin", "HEAD:refs/heads/main")
    os.unlink(helper)
    if rc:
        say("FAIL 推送失败: %s" % out.replace(token, "***")[-300:]); return 1
    say("PUSH 完成")

    st, pg = api("POST", "/repos/%s/%s/pages" % (login, REPO), token,
                 {"build_type": "legacy", "source": {"branch": "main", "path": "/"}})
    if st in (201, 202):
        say("PAGES 已开启")
    elif st == 409:
        st, pg = api("PUT", "/repos/%s/%s/pages" % (login, REPO), token,
                     {"build_type": "legacy", "source": {"branch": "main", "path": "/"}})
        say("PAGES 已存在，更新 %s" % st)
    else:
        say("WARN Pages %s %s" % (st, str(pg)[:200]))

    url = "https://%s.github.io/%s/" % (login, REPO)
    say("URL %s" % url)
    built = False
    for i in range(40):
        st, pg = api("GET", "/repos/%s/%s/pages" % (login, REPO), token)
        status = pg.get("status") or pg.get("message", "")
        say("PAGES status=%s" % status)
        if status == "built":
            built = True; break
        time.sleep(10)
    say("BUILT %s" % built)
    return 0


if __name__ == "__main__":
    sys.exit(main())
