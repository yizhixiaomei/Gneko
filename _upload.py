import json, os, sys, time, urllib.request, urllib.error

REPO = "yizhixiaomei/Gneko"
RID = "460618339"
API = "https://api.github.com/repos/" + REPO
UP = "https://uploads.github.com/repos/%s/releases/%s/assets?name=" % (REPO, RID)
WD = r"D:\gneko"

tok = None
for line in open(os.path.expanduser(r"~\.git-credentials"), encoding="utf-8"):
    if "github.com" in line:
        tok = line.strip().split("://")[1].split("@")[0].split(":")[1]


def call(url, data=None, method=None, ctype="application/json", raw=False, tries=4):
    body = data
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, method=method or ("POST" if body is not None else "GET"))
            req.add_header("Authorization", "Bearer " + tok)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "gneko-release-bot")
            if body is not None:
                req.add_header("Content-Type", ctype)
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            print("  HTTP %s %s" % (e.code, detail))
            if e.code in (401, 403, 404, 422):
                raise SystemExit("fatal: HTTP %s" % e.code)
        except Exception as e:
            print("  try %d/%d failed: %s" % (i + 1, tries, e))
        time.sleep(8 * (i + 1))
    raise SystemExit("upload failed after %d tries: %s" % (tries, url))


DEFS = [
    # 先传新名字的 Linux 包：顺带验证上传域名是否可达，不通就还什么都没删
    (None, r"_release\Gneko-v2.0.1-linux.tar.gz", "Gneko-v2.0.1-linux.tar.gz", "application/gzip"),
    ("800553783", r"_release\Gneko-v2.0.1-source.zip", "Gneko-v2.0.1-source.zip", "application/zip"),
    ("800549191", r"dist\Gneko.exe", "Gneko-v2.0.1-windows-x64.exe", "application/octet-stream"),
    ("802881400", r"_release\SHA256SUMS.txt", "SHA256SUMS.txt", "text/plain"),
]

# 先确认上传域名可达，避免删了旧附件又传不上去
print("probe uploads.github.com ...")
call(API + "/releases/" + RID)

for aid, path, name, ctype in DEFS:
    if aid:
        call(API + "/releases/assets/" + aid, method="DELETE")
        print("deleted asset", aid, name)
    data = open(os.path.join(WD, path), "rb").read()
    a = call(UP + urllib.request.quote(name), data=data, method="POST", ctype=ctype)
    print("uploaded", a["name"], a["size"], a["digest"])

rel = call(API + "/releases/" + RID)
print("assets now:")
for a in rel["assets"]:
    print("  ", a["name"], a["size"], a.get("digest"))
