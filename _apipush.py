import base64, json, subprocess, sys, urllib.request, os

WD = r"D:\gneko"
REPO = "yizhixiaomei/Gneko"
API = "https://api.github.com/repos/" + REPO

tok = None
for line in open(os.path.expanduser(r"~\.git-credentials"), encoding="utf-8"):
    if "github.com" in line:
        tok = line.strip().split("://")[1].split("@")[0].split(":")[1]


def git(*a):
    r = subprocess.run(["git"] + list(a), cwd=WD, capture_output=True, text=True)
    if r.returncode:
        sys.exit("git " + " ".join(a) + " failed: " + r.stderr)
    return r.stdout


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


base, head, branch = sys.argv[1], sys.argv[2], sys.argv[3]
base_sha, head_sha = git("rev-parse", base).strip(), git("rev-parse", head).strip()
files = [f for f in git("diff", "--name-only", "--no-renames", base, head).splitlines() if f.strip()]
print("changed:", files)

meta = git("log", "-1", "--pretty=%an|%ae|%aI|%cn|%ce|%cI", head).strip()
an, ae, ad, cn, ce, cd = meta.split("|")
msg = git("log", "-1", "--pretty=%B", head).rstrip("\n")

entries = []
for f in files:
    parts = git("ls-tree", head, "--", f).split()
    mode = parts[0]
    raw = open(os.path.join(WD, f), "rb").read()
    blob = api("/git/blobs", {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
    entries.append({"path": f.replace("\\", "/"), "mode": mode, "type": "blob", "sha": blob["sha"]})
    print("blob", f, mode, len(raw))

tree = api("/git/trees", {"base_tree": git("rev-parse", base + "^{tree}").strip(), "tree": entries})
commit = api("/git/commits", {"message": msg, "tree": tree["sha"], "parents": [base_sha],
                             "author": {"name": an, "email": ae, "date": ad},
                             "committer": {"name": cn, "email": ce, "date": cd}})
print("remote commit:", commit["sha"], "(local", head_sha + ")")
ref = api("/git/refs/heads/" + branch, {"sha": commit["sha"], "force": True}, method="PATCH")
print("ref heads/" + branch, "->", ref["object"]["sha"])
