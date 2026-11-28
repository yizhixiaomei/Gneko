import json, os, time, urllib.request, urllib.error

REPO = "yizhixiaomei/Gneko"
RID = "460618339"
API = "https://api.github.com/repos/" + REPO
UP = "https://uploads.github.com/repos/%s/releases/%s/assets?name=" % (REPO, RID)
WD = r"D:\gneko"
tok = [l.strip().split("://")[1].split("@")[0].split(":")[1]
       for l in open(os.path.expanduser("~/.git-credentials"), encoding="utf-8") if "github.com" in l][0]


def call(url, data=None, method=None, ctype="application/json", tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data,
                                         method=method or ("POST" if data is not None else "GET"))
            req.add_header("Authorization", "Bearer " + tok)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "gneko-release-bot")
            if data is not None:
                req.add_header("Content-Type", ctype)
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw.strip() else {"status": r.status}
        except urllib.error.HTTPError as e:
            if e.code in (204, 404):
                return {"status": e.code}
            print("  HTTP %s %s" % (e.code, e.read().decode()[:200]))
            if e.code in (401, 403, 422):
                raise SystemExit("fatal %s" % e.code)
        except Exception as e:
            print("  try %d/%d: %s" % (i + 1, tries, e))
        time.sleep(8 * (i + 1))
    raise SystemExit("failed: " + url)


DEFS = [
    ("800553783", None, "Gneko-v2.0.1-source.zip", None),   # 已删，仅占位
    ("800549191", r"dist\Gneko.exe", "Gneko-v2.0.1-windows-x64.exe", "application/octet-stream"),
    ("802881400", r"_release\SHA256SUMS.txt", "SHA256SUMS.txt", "text/plain"),
]
# 源包上一轮已删，这里补传
todo = [
    (None, r"_release\Gneko-v2.0.1-source.zip", "Gneko-v2.0.1-source.zip", "application/zip"),
    ("800549191", r"dist\Gneko.exe", "Gneko-v2.0.1-windows-x64.exe", "application/octet-stream"),
    ("802881400", r"_release\SHA256SUMS.txt", "SHA256SUMS.txt", "text/plain"),
]

for aid, path, name, ctype in todo:
    if aid:
        r = call(API + "/releases/assets/" + aid, method="DELETE")
        print("delete", aid, r.get("status"))
    a = call(UP + urllib.request.quote(name), data=open(os.path.join(WD, path), "rb").read(),
             method="POST", ctype=ctype)
    print("uploaded", a.get("name"), a.get("size"), a.get("digest"))

d = call(API + "/releases/" + RID)
print("final assets:")
for a in d["assets"]:
    print("  ", a["name"], a["size"], a.get("digest"))
