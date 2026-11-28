import json, os, sys, urllib.request

REPO = "yizhixiaomei/Gneko"
API = "https://api.github.com/repos/" + REPO
tok = None
for line in open(os.path.expanduser(r"~\.git-credentials"), encoding="utf-8"):
    if "github.com" in line:
        tok = line.strip().split("://")[1].split("@")[0].split(":")[1]


def api(path, data=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(API + path, data=body,
                                 method=method or ("POST" if body else "GET"))
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "gneko-release-bot")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


sha = sys.argv[1]
ref = api("/git/refs/tags/v2.0.1", {"sha": sha, "force": True}, method="PATCH")
print("tag v2.0.1 ->", ref["object"]["sha"])
rel = api("/releases/460618339")
print("release tag:", rel["tag_name"], "| target:", rel["target_commitish"], "| assets:", len(rel["assets"]))
for a in rel["assets"]:
    print("  ", a["id"], a["name"], a["size"], a.get("digest"))
open(r"D:\gneko\_release\body_current.md", "w", encoding="utf-8").write(rel["body"])
print("body saved, chars:", len(rel["body"]))
