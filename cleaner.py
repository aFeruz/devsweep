#!/usr/bin/env python3
"""DevSweep — laptopdagi keraksiz fayllarni topib, tanlab o'chiradigan lokal app.

Ishga tushirish:  python3 cleaner.py   (brauzerda http://127.0.0.1:8765 ochiladi)
Desktop ilova:    python3 gui.py
Hech narsa avtomatik o'chirilmaydi — faqat siz tanlagan va tasdiqlagan narsalar.
"""
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n import LANGS, T, _, get_lang, set_lang, table  # noqa: E402

HOME = Path.home()
PORT = int(os.environ.get("PORT", 8765))
TOKEN = secrets.token_hex(16)
MIN_SIZE = 5 * 1024 * 1024  # 5 MB dan kichiklarni ko'rsatmaymiz
RECENT_DAYS = int(os.environ.get("RECENT_DAYS", 14))  # shundan yangi ishlatilganlar himoyalanadi
BIG_FILE = int(os.environ.get("BIG_FILE_MB", 100)) * 1024 * 1024
DUP_MIN = 1024 * 1024  # dublikat qidirish uchun minimal fayl hajmi

SAFE, REVIEW, CAREFUL = "safe", "review", "careful"

# id -> action (scan paytida to'ldiriladi; klientdan faqat id keladi, yo'l emas)
ACTIONS = {}
SCAN_LOCK = threading.Lock()


# ---------------------------------------------------------------- helpers

def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def du(path):
    rc, out, _err = run(["du", "-sk", "--one-file-system", str(path)], timeout=600)
    try:
        return int(out.split()[0]) * 1024
    except (IndexError, ValueError):
        return 0


def parse_docker_size(s):
    m = re.match(r"([\d.]+)\s*([kKMGT]?B)", s or "")
    if not m:
        return 0
    mult = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2)]
    return int(float(m.group(1)) * mult)


def age_days(path):
    try:
        return int((time.time() - path.stat().st_mtime) / 86400)
    except OSError:
        return None


def running(*names):
    for n in names:
        if run(["pgrep", "-x", n])[0] == 0:
            return True
    return False


class Item(dict):
    pass


def item(gkey, title, desc, size, safety, action, path=None, age=None, warn=None,
         used=None, track_recent=False, paths=None, app=None):
    """age — oxirgi o'zgarish (kun); used — oxirgi ishlatilgan (kun).
    track_recent=True bo'lsa, RECENT_DAYS ichida ishlatilgan narsa "yaqinda" deb belgilanadi."""
    iid = f"i{len(ACTIONS)}"
    ACTIONS[iid] = action
    last = used if used is not None else age
    recent = bool(track_recent and last is not None and last < RECENT_DAYS)
    if recent:
        safety = CAREFUL
    if app:  # dastur ochiq — ogohlantirish
        warn = _("warn.running", app=app)
    return Item(id=iid, gkey=gkey, group=_(f"group.{gkey}", mb=BIG_FILE >> 20), title=title, desc=desc,
                size=size, safety=safety, path=str(path) if path else None, paths=paths, age=age, used=used,
                warn=warn, app=app, recent=recent)


def parse_time(s):
    """Docker/RFC3339 vaqtini epoch'ga aylantiradi. '0001-01-01...' (hech qachon) -> None."""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.\d+)?\s*(Z|UTC|[+-]\d\d:?\d\d)?", s or "")
    if not m or m.group(1) == "0001":
        return None
    tz = m.group(7) or "Z"
    off = timedelta(0) if tz in ("Z", "UTC") else \
        (1 if tz[0] == "+" else -1) * timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:]))
    dt = datetime(*map(int, m.groups()[:6]), tzinfo=timezone(off))
    return dt.timestamp()


def days_since(*times):
    ts = [t for t in times if t]
    return int((time.time() - max(ts)) / 86400) if ts else None


def rm_files(paths):
    """Bir nechta faylni o'chiradi (faqat $HOME ichida)."""
    def _do():
        home = HOME.resolve()
        n = 0
        for f in paths:
            p = Path(f)
            if home not in p.resolve().parents:
                raise RuntimeError(_("res.outside", path=p))
            if p.is_file() or p.is_symlink():
                p.unlink()
                n += 1
        return _("res.files", n=n)
    return {"kind": "py", "fn": _do}


def rm_path(path, contents_only=False):
    """Faqat $HOME ichidagi yo'llarni o'chiradi."""
    def _do():
        p = Path(path)
        real = p.resolve()
        if HOME.resolve() not in real.parents:
            raise RuntimeError(_("res.outside", path=p))
        if not p.exists():
            return _("res.gone")
        targets = list(p.iterdir()) if contents_only else [p]
        for t in targets:
            if t.is_symlink() or t.is_file():
                t.unlink()
            else:
                shutil.rmtree(t)
        return _("res.deleted")
    return {"kind": "py", "fn": _do}


def cmd(*args):
    return {"kind": "cmd", "cmd": list(args)}


def root_cmd(*args):
    return {"kind": "root", "cmd": list(args)}


# ---------------------------------------------------------------- scanners

def docker_inspect(kind, ids, fmt):
    """Ko'p obyektni bitta chaqiruvda inspect qiladi: {id: [maydonlar]}."""
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 200):
        rc, o, _err = run(["docker", kind, "inspect", "--format", fmt, *ids[i:i + 200]], timeout=120)
        for line in o.splitlines():
            parts = line.split("|")
            out[parts[0]] = parts[1:]
    return out


def scan_docker():
    items = []
    if not shutil.which("docker"):
        return items
    rc, out, _err = run(["docker", "system", "df", "-v", "--format", "{{json .}}"], timeout=120)
    if rc != 0:
        return items
    d = json.loads(out)
    G = "docker"
    hours = f"{RECENT_DAYS * 24}h"

    # --- konteynerlar: oxirgi ishga tushgan/to'xtagan vaqtiga qarab
    conts = [c for c in d.get("Containers") or [] if c.get("State") != "running"]
    info = docker_inspect("container", [c["ID"] for c in conts],
                          "{{.Id}}|{{.Created}}|{{.State.StartedAt}}|{{.State.FinishedAt}}")
    for c in conts:
        full = next((v for k, v in info.items() if k.startswith(c["ID"])), [])
        used = days_since(*map(parse_time, full))
        items.append(item(G, _("docker.container.title", name=c.get("Names", "?")),
                          _("docker.container.desc", image=c.get("Image", ""), status=c.get("Status", "")),
                          parse_docker_size(c.get("Size", "").split(" ")[0]), REVIEW,
                          cmd("docker", "rm", c["ID"]), used=used, track_recent=True))

    # --- image'lar: yaratilgan / oxirgi tag (pull, build) vaqtiga qarab
    images = d.get("Images") or []
    unused = [i for i in images if i.get("Containers") == "0"]
    info = docker_inspect("image", {i["ID"] for i in unused}, "{{.Id}}|{{.Created}}|{{.Metadata.LastTagTime}}")
    for i in unused:
        i["_used"] = days_since(*map(parse_time, info.get(i["ID"], [])))

    dangling = [i for i in unused if i.get("Repository") == "<none>"]
    old_d = [i for i in dangling if (i["_used"] or 0) >= RECENT_DAYS]
    if old_d:
        items.append(item(G, _("docker.dangling.title", n=len(old_d), days=RECENT_DAYS),
                          _("docker.dangling.desc", days=RECENT_DAYS, kept=len(dangling) - len(old_d)),
                          sum(parse_docker_size(i.get("UniqueSize")) for i in old_d), SAFE,
                          cmd("docker", "image", "prune", "-f", "--filter", f"until={hours}")))

    for i in unused:
        if i.get("Repository") == "<none>":
            continue
        ref = f"{i['Repository']}:{i['Tag']}"
        items.append(item(G, _("docker.image.title", ref=ref), _("docker.image.desc", size=i.get("Size")),
                          parse_docker_size(i.get("UniqueSize")), REVIEW, cmd("docker", "rmi", ref),
                          used=i["_used"], track_recent=True))

    # --- build cache: LastUsedAt bo'yicha, faqat eskilari
    cache = [c for c in d.get("BuildCache") or [] if c.get("InUse") != "true"]
    for c in cache:
        c["_used"] = days_since(parse_time(c.get("LastUsedAt")), parse_time(c.get("CreatedAt")))
    old_c = [c for c in cache if (c["_used"] or 0) >= RECENT_DAYS]
    if old_c:
        items.append(item(G, _("docker.cache.title", n=len(old_c), days=RECENT_DAYS),
                          _("docker.cache.desc", days=RECENT_DAYS, kept=len(cache) - len(old_c)),
                          sum(parse_docker_size(c.get("Size")) for c in old_c), SAFE,
                          cmd("docker", "builder", "prune", "-a", "-f", "--filter", f"until={hours}")))

    # --- volume'lar: ulanmagan, yaratilgan vaqtiga qarab
    vols = [v for v in d.get("Volumes") or [] if v.get("Links") == "0"]
    info = docker_inspect("volume", [v["Name"] for v in vols], "{{.Name}}|{{.CreatedAt}}")
    for v in vols:
        v["_used"] = days_since(*map(parse_time, info.get(v["Name"], [])))
    tiny = [v for v in vols if parse_docker_size(v.get("Size")) < 1e6 and (v["_used"] or 0) >= RECENT_DAYS]
    if tiny:
        items.append(item(G, _("docker.tinyvol.title", n=len(tiny)), _("docker.tinyvol.desc", days=RECENT_DAYS),
                          sum(parse_docker_size(v.get("Size")) for v in tiny), SAFE,
                          cmd("docker", "volume", "rm", *[v["Name"] for v in tiny])))
    for v in vols:
        if v in tiny or (parse_docker_size(v.get("Size")) < 1e6 and (v["_used"] or 0) < RECENT_DAYS):
            continue
        anon = "com.docker.volume.anonymous" in (v.get("Labels") or "")
        items.append(item(G, _("docker.vol.title", name=v["Name"][:40]),
                          _("docker.vol.anon") if anon else _("docker.vol.named"),
                          parse_docker_size(v.get("Size")), REVIEW if anon else CAREFUL,
                          cmd("docker", "volume", "rm", v["Name"]), used=v["_used"], track_recent=True))
    return items


APP_PROCS = {"google-chrome": ("chrome",), "Cursor": ("cursor", "Cursor"), "Code": ("code",),
             "Code - Insiders": ("code-insiders",), "TelegramDesktop": ("Telegram", "telegram-desktop")}


def app_running(name):
    """Dastur ochiq bo'lsa, uning nomini qaytaradi (ogohlantirish uchun)."""
    procs = APP_PROCS.get(name)
    return name if procs and running(*procs) else None


def scan_user_paths():
    """(gkey, title, desc, path, safety, contents_only, app)"""
    cands = []
    cache = HOME / ".cache"
    if cache.is_dir():
        for p in cache.iterdir():
            if p.is_dir() and not p.is_symlink():
                desc = _(f"cache.{p.name}") if f"cache.{p.name}" in T else _("cache.generic")
                cands.append(("cache", p.name, desc, p, SAFE, False, app_running(p.name)))

    dev = [
        (".npm/_cacache", "dev.npm"), (".gradle/caches", "dev.gradle"), (".gradle/daemon", "dev.gradled"),
        (".gradle/wrapper/dists", "dev.gradlew"), (".m2/repository", "dev.m2"), (".cargo/registry", "dev.cargo"),
        ("go/pkg/mod", "dev.go"), (".nvm/.cache", "dev.nvm"), (".local/share/pnpm/store", "dev.pnpm"),
        (".bun/install/cache", "dev.bun"),
    ]
    for rel, key in dev:
        p = HOME / rel
        if p.is_dir():
            cands.append(("devcache", _(key), _(f"{key}.desc"), p, SAFE, False, None))

    cfg = HOME / ".config"
    if cfg.is_dir():
        for app in cfg.iterdir():
            if not app.is_dir():
                continue
            for sub in ("Cache", "Code Cache", "GPUCache", "CachedData", "CachedExtensionVSIXs",
                        "Service Worker/CacheStorage", "logs", "Crashpad"):
                p = app / sub
                if p.is_dir():
                    cands.append(("appcache", f"{app.name} → {sub}", _("app.electron.desc"),
                                  p, SAFE, False, app_running(app.name)))

    chrome = cfg / "google-chrome"
    if chrome.is_dir():
        p = chrome / "OptGuideOnDeviceModel"
        if p.is_dir():
            cands.append(("appcache", _("app.chrome_model"), _("app.chrome_model.desc"), p, REVIEW, False,
                          app_running("google-chrome")))
        for prof in chrome.iterdir():
            for sub in ("Service Worker/CacheStorage", "Code Cache", "GPUCache"):
                p = prof / sub
                if prof.is_dir() and p.is_dir():
                    cands.append(("appcache", f"Chrome [{prof.name}] → {sub}", _("app.chrome_site.desc"),
                                  p, SAFE, False, app_running("google-chrome")))

    p = cfg / "Cursor" / "snapshots"
    if p.is_dir():
        cands.append(("appcache", _("app.cursor_snap"), _("app.cursor_snap.desc"), p, REVIEW, False,
                      app_running("Cursor")))

    p = HOME / ".local/share/TelegramDesktop/tdata/user_data"
    if p.is_dir():
        cands.append(("appcache", _("app.telegram"), _("app.telegram.desc"), p, REVIEW, False,
                      app_running("TelegramDesktop")))

    snapdir = HOME / "snap"
    if snapdir.is_dir():
        for p in snapdir.glob("*/*/.cache"):
            if p.is_dir() and not p.is_symlink():
                cands.append(("cache", _("app.snap_cache", name=p.parts[-3]), _("app.snap_cache.desc"),
                              p, SAFE, False, None))

    trash = HOME / ".local/share/Trash"
    if trash.is_dir():
        cands.append(("junk", _("trash"), _("trash.desc"), trash, SAFE, True, None))

    items = []
    with ThreadPoolExecutor(8) as ex:
        sizes = list(ex.map(lambda c: du(c[3]), cands))
    for (g, title, desc, p, safety, contents, app), size in zip(cands, sizes):
        if size >= MIN_SIZE:
            items.append(item(g, title, desc, size, safety, rm_path(p, contents), path=p, age=age_days(p), app=app))
    return items


# nom -> (marker, tarjima kaliti). marker: papka ichida yoki (..) yonida bo'lishi kerak bo'lgan fayl
ARTIFACTS = {
    "node_modules": (None, "art.node_modules"),
    ".next": (None, "art..next"),
    ".nuxt": (None, "art..nuxt"),
    ".turbo": (None, "art..turbo"),
    ".angular": (None, "art..angular"),
    ".parcel-cache": (None, "art..parcel-cache"),
    ".venv": ("pyvenv.cfg", "art.venv"),
    "venv": ("pyvenv.cfg", "art.venv"),
    "target": ("..Cargo.toml|..pom.xml", "art.target"),
    "build": ("..build.gradle|..build.gradle.kts", "art.build"),
}
# Uy papkasining yuqori darajasida aylanilmaydigan papkalar (keshlar boshqa skanerda)
SKIP_DIRS = {"snap", "go", "Android"}  # Android SDK fayllari emulator uchun kerak

JUNK = [
    ("junk.partial", SAFE, None,
     re.compile(r".*\.(crdownload|part|partial|download)$", re.I)),
    ("junk.logs", REVIEW, None,
     re.compile(r"(.*\.log(\.\d+)?|npm-debug\.log.*|yarn-error\.log|hs_err_pid\d+\.log|replay_pid\d+\.log)$", re.I)),
    ("junk.temp", REVIEW, None,
     re.compile(r"(.*\.(tmp|temp|swp|swo|bak|old|orig)|.*~|\.DS_Store|Thumbs\.db|desktop\.ini)$", re.I)),
    ("junk.core", SAFE, None,
     re.compile(r"core(\.\d+)?$")),
]
INSTALLER = re.compile(r".*\.(deb|rpm|appimage|apk|aab|iso|exe|msi|dmg|snap|flatpakref)$", re.I)


def is_artifact(p):
    rule = ARTIFACTS.get(p.name)
    if rule is None:
        return False
    marker = rule[0]
    if marker is None:
        return True
    for m in marker.split("|"):
        if m.startswith(".."):
            if (p.parent / m[2:]).exists():
                return True
        elif (p / m).exists():
            return True
    return False


def project_age(project):
    """Loyiha oxirgi marta qachon o'zgargan: papka va uning bevosita ichidagilarning eng yangisi."""
    try:
        times = [project.stat().st_mtime]
        for c in project.iterdir():
            if c.name not in ARTIFACTS:
                times.append(c.lstat().st_mtime)
        return days_since(*times)
    except OSError:
        return None


def walk_home():
    """Uy papkasini bir marta aylanib: build papkalar, 1MB+ fayllar va keraksiz fayllarni yig'adi."""
    artifacts, files, junk = [], [], defaultdict(list)
    for root, dirs, names in os.walk(HOME):
        rp = Path(root)
        keep = []
        for d in dirs:
            p = rp / d
            if p.is_symlink() or (rp == HOME and d in SKIP_DIRS):
                continue
            if is_artifact(p):
                artifacts.append(p)
            elif not d.startswith(".") or d in ARTIFACTS:
                keep.append(d)
        dirs[:] = keep
        for n in names:
            p = rp / n
            try:
                st = p.lstat()
            except OSError:
                continue
            if not os.path.isfile(p) or os.path.islink(p):
                continue
            for jt in JUNK:
                if jt[3].fullmatch(n):
                    junk[jt].append((p, st))
                    break
            else:
                if st.st_size >= DUP_MIN:
                    files.append((p, st))
    return artifacts, files, junk


def file_hash(p, partial):
    # O_NOATIME: o'qish faylning "oxirgi ochilgan" vaqtini o'zgartirmasin (aks holda hammasi "yaqinda" bo'lib qoladi)
    h = hashlib.blake2b(digest_size=20)
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOATIME", 0))
    except PermissionError:  # O_NOATIME faqat fayl egasiga ruxsat
        fd = os.open(p, os.O_RDONLY)
    with os.fdopen(fd, "rb") as f:
        if partial:
            h.update(f.read(65536))
            f.seek(max(0, os.fstat(f.fileno()).st_size - 65536))
            h.update(f.read(65536))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def find_duplicates(files):
    """Hajm -> boshi/oxiri hashi -> to'liq hash. Hardlink'lar (bir xil inode) hisoblanmaydi."""
    by_size = defaultdict(dict)
    for p, st in files:
        by_size[st.st_size].setdefault((st.st_dev, st.st_ino), (p, st))
    groups = []
    for size, uniq in by_size.items():
        if len(uniq) < 2:
            continue
        buckets = defaultdict(list)
        for p, st in uniq.values():
            try:
                buckets[file_hash(p, True)].append((p, st))
            except OSError:
                pass
        for cand in buckets.values():
            if len(cand) < 2:
                continue
            full = defaultdict(list)
            for p, st in cand:
                try:
                    full[file_hash(p, False)].append((p, st))
                except OSError:
                    pass
            groups += [g for g in full.values() if len(g) > 1]
    return groups


_REPO_CACHE = {}


def repo_of(p):
    """Fayl git loyihasi ichida bo'lsa, loyiha papkasini qaytaradi."""
    for d in p.parents:
        if d == HOME or d == d.parent:
            return None
        if d not in _REPO_CACHE:
            _REPO_CACHE[d] = (d / ".git").exists()
        if _REPO_CACHE[d]:
            return d


def file_warn(p):
    repo = repo_of(p)
    return _("warn.git", repo=repo.name) if repo else None


def scan_home():
    artifacts, files, junk = walk_home()
    items = []

    # --- build/paket papkalari
    with ThreadPoolExecutor(8) as ex:
        sizes = list(ex.map(du, artifacts))
    for p, size in zip(artifacts, sizes):
        if size < MIN_SIZE:
            continue
        age = project_age(p.parent)
        items.append(item("projects", f"{p.parent.name}/{p.name}",
                          f"{_(ARTIFACTS[p.name][1])} · {_('art.age_note')}",
                          size, SAFE if (age or 0) > 60 else REVIEW,
                          rm_path(p), path=p, age=age, track_recent=True))

    # --- dublikatlar: har guruhda bitta nusxa saqlanadi (Downloads'da bo'lmagan, eng eski)
    taken = set()
    for g in find_duplicates(files):
        g.sort(key=lambda x: ("/Downloads/" in str(x[0]), x[1].st_mtime, len(str(x[0]))))
        keep = g[0][0]
        for p, st in g[1:]:
            taken.add(p)
            warn = file_warn(p)
            items.append(item("dupes", p.name, _("dupe.desc", keep=keep),
                              st.st_size, CAREFUL if warn else REVIEW, rm_files([p]), path=p, warn=warn,
                              age=days_since(st.st_mtime), used=days_since(st.st_mtime, st.st_atime),
                              track_recent=True))

    # --- installerlar va katta fayllar
    for p, st in files:
        if p in taken:
            continue
        used = days_since(st.st_mtime, st.st_atime)
        if INSTALLER.fullmatch(p.name) and st.st_size >= MIN_SIZE:
            items.append(item("installers", p.name, _("installer.desc"), st.st_size, REVIEW, rm_files([p]),
                              path=p, warn=file_warn(p), age=days_since(st.st_mtime), used=used, track_recent=True))
        elif st.st_size >= BIG_FILE:
            items.append(item("big", p.name, _("big.desc"), st.st_size, CAREFUL, rm_files([p]),
                              path=p, warn=file_warn(p), age=days_since(st.st_mtime), used=used, track_recent=True))

    # --- keraksiz fayllar (turlari bo'yicha jamlangan)
    for (key, safety, _unused, _rx), lst in junk.items():
        old = [(p, st) for p, st in lst if (days_since(st.st_mtime) or 0) >= 1]
        size = sum(st.st_size for _p, st in old)
        if size >= 100 * 1024:
            old.sort(key=lambda x: -x[1].st_size)
            paths = [str(p) for p, _st in old]
            items.append(item("junk", _(key, n=len(old)), _(f"{key}.desc"), size, safety,
                              rm_files(paths), paths=paths[:200]))
    return items


def scan_system():
    G = "system"
    items = []
    rc, out, _err = run(["snap", "list", "--all"])
    if rc == 0:
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and "disabled" in parts[-1]:
                name, rev = parts[0], parts[2]
                f = Path(f"/var/lib/snapd/snaps/{name}_{rev}.snap")
                size = f.stat().st_size if f.exists() else 0
                items.append(item(G, _("sys.snap", name=name, rev=rev), _("sys.snap.desc"),
                                  size, SAFE, root_cmd("snap", "remove", name, f"--revision={rev}")))
    size = du("/var/cache/apt/archives")
    if size >= MIN_SIZE:
        items.append(item(G, _("sys.apt"), _("sys.apt.desc"),
                          size, SAFE, root_cmd("apt-get", "clean")))
    rc, out, _err = run(["journalctl", "--disk-usage"])
    m = re.search(r"([\d.]+)([KMGT])", out)
    if m:
        size = int(float(m.group(1)) * {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}[m.group(2)])
        if size > 150 << 20:
            items.append(item(G, _("sys.journal"), _("sys.journal.desc"),
                              size - (100 << 20), SAFE, root_cmd("journalctl", "--vacuum-size=100M")))
    return items


def full_scan():
    with SCAN_LOCK:
        ACTIONS.clear()
        t = time.time()
        with ThreadPoolExecutor(4) as ex:
            futs = [ex.submit(f) for f in (scan_docker, scan_user_paths, scan_home, scan_system)]
            items, errors = [], []
            for f in futs:
                try:
                    items += f.result()
                except Exception as e:  # bitta skaner yiqilsa, qolganlari ishlayversin
                    errors.append(repr(e))
        rc, out, _err = run(["df", "-B1", "--output=size,avail", str(HOME)])
        total, avail = (int(x) for x in out.splitlines()[1].split()) if rc == 0 else (0, 0)
        return {"items": items, "errors": errors, "took": round(time.time() - t, 1), "recent_days": RECENT_DAYS,
                "disk": {"total": total, "avail": avail}}


def clean(ids):
    results = []
    root_batch = []
    for iid in ids:
        a = ACTIONS.get(iid)
        if a is None:
            results.append({"id": iid, "ok": False, "msg": _("res.unknown")})
        elif a["kind"] == "py":
            try:
                results.append({"id": iid, "ok": True, "msg": a["fn"]()})
            except Exception as e:
                results.append({"id": iid, "ok": False, "msg": str(e)})
        elif a["kind"] == "cmd":
            rc, out, err = run(a["cmd"], timeout=900)
            results.append({"id": iid, "ok": rc == 0, "msg": (err or out).strip()[-300:] or _("res.done")})
        else:
            root_batch.append((iid, a["cmd"]))
    if root_batch:
        # Bitta parol so'rovi bilan barcha root buyruqlarini bajaramiz
        script = "\n".join(f"{shlex.join(c)} && echo 'OK {i}' || echo 'FAIL {i}'" for i, c in root_batch)
        rc, out, err = run(["pkexec", "sh", "-c", script], timeout=1800)
        for i, _cmd in root_batch:
            ok = f"OK {i}" in out
            results.append({"id": i, "ok": ok, "msg": _("res.done") if ok else (err.strip()[-300:] or _("res.cancelled"))})
    return results


# ---------------------------------------------------------------- web

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        lang = parse_qs(url.query).get("lang", [None])[0]
        if lang in LANGS:
            set_lang(lang)
        if url.path == "/":
            self.send(200, render_page(), "text/html; charset=utf-8")
        elif url.path == "/api/scan":
            self.send(200, json.dumps(full_scan()))
        else:
            self.send(404, "{}")

    def do_POST(self):
        if self.path != "/api/clean" or self.headers.get("X-Token") != TOKEN:
            return self.send(403, '{"error":"forbidden"}')
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        self.send(200, json.dumps({"results": clean(body.get("ids", []))}))


def render_page():
    """{{kalit}} → tarjima (HTML-escape bilan); JS uchun lug'at __I18N__ ga joylanadi."""
    import html
    lang = get_lang()
    page = re.sub(r"\{\{([\w.]+)\}\}", lambda m: html.escape(_(m.group(1))), PAGE)
    opts = "".join(f'<option value="{k}"{" selected" if k == lang else ""}>{v}</option>' for k, v in LANGS.items())
    strings = {**table("ui."), **table("web.")}
    return (page.replace("__TOKEN__", TOKEN).replace("__LANG__", lang).replace("__LANGOPTS__", opts)
            .replace("__I18N__", json.dumps(strings, ensure_ascii=False).replace("</", "<\\/")))


PAGE = r"""<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevSweep</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1c2230;--mut:#6b7385;--line:#e4e7ec;--acc:#2f6fed;--safe:#1f9d55;--rev:#c98a00;--car:#d64545;--sel:#eef3ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--mut:#8b93a5;--line:#262c38;--acc:#5b8cff;--safe:#3ec27a;--rev:#e3a92b;--car:#f06565;--sel:#1b2436}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 16px 8px;max-width:1000px;margin:auto}
h1{margin:0 0 4px;font-size:22px;display:flex;align-items:center;gap:12px}h1 select{margin-left:auto}.mut{color:var(--mut)}
.bar{height:10px;background:var(--line);border-radius:6px;overflow:hidden;margin:10px 0 4px}.bar>i{display:block;height:100%;background:var(--acc)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
button,select{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:7px 12px;border-radius:8px;cursor:pointer}
select{font-size:14px;padding:5px 8px}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}button.dan{background:var(--car);border-color:var(--car);color:#fff}
button:disabled{opacity:.5;cursor:default}
main{max-width:1000px;margin:auto;padding:0 16px 120px}
.grp{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden}
.gh{display:flex;align-items:center;gap:10px;padding:12px 14px;cursor:pointer;user-select:none}
.gh h2{font-size:16px;margin:0;flex:1}.gh .sz{font-weight:600}
.gh .arr{transition:transform .2s;color:var(--mut)}.grp:not(.collapsed) .arr{transform:rotate(180deg)}
.row{display:grid;grid-template-columns:22px 1fr auto;gap:10px;padding:10px 14px;border-top:1px solid var(--line);align-items:start}
.row.on{background:var(--sel)}.row{cursor:pointer}
.t{font-weight:500;word-break:break-word}.d{font-size:13.5px;color:var(--mut)}.p{font:12.5px ui-monospace,monospace;color:var(--mut);word-break:break-all}
.w{font-size:13px;color:var(--car)}
.sz{white-space:nowrap;text-align:right}
.b{font-size:11.5px;padding:1px 7px;border-radius:10px;border:1px solid;margin-left:6px;white-space:nowrap}
.b.safe{color:var(--safe)}.b.review{color:var(--rev)}.b.careful{color:var(--car)}
input[type=checkbox]{width:16px;height:16px;margin-top:2px;accent-color:var(--acc)}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:12px 16px}
footer .in{max-width:1000px;margin:auto;display:flex;align-items:center;gap:12px;flex-wrap:wrap}footer .in>div{flex:1}
.hide,.norecent .row.recent{display:none}.b.recent{color:var(--acc)}
details{font-size:13px;color:var(--mut)}details div{font:12.5px ui-monospace,monospace;word-break:break-all}.collapsed .row{display:none}
dialog{border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--fg);max-width:640px;width:calc(100% - 32px)}
dialog ul{max-height:45vh;overflow:auto;padding-left:18px}.ok{color:var(--safe)}.err{color:var(--car)}
.spin{padding:60px 0;text-align:center}
.ic{width:1.1em;height:1.1em;vertical-align:-.18em;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
h1 .ic{width:1.3em;height:1.3em;color:var(--acc)}button .ic{margin-right:6px}.note{display:flex;gap:8px;align-items:flex-start;margin:6px 0}
</style></head><body>
<header>
 <h1><svg class="ic"><use href="#i-drive"/></svg>DevSweep <select aria-label="{{ui.menu.lang}}" onchange="location.href='/?lang='+this.value">__LANGOPTS__</select></h1>
 <div class="mut" id="disk">{{web.disk_loading}}</div>
 <div class="bar"><i id="used" style="width:0"></i></div>
 <div class="tools">
  <button onclick="scan()"><svg class="ic"><use href="#i-refresh"/></svg>{{web.rescan}}</button>
  <button onclick="pick('safe')"><svg class="ic"><use href="#i-check"/></svg>{{web.pick_safe}}</button>
  <button onclick="pick(null)">{{ui.menu.pick_none}}</button>
  <label style="align-self:center"><input type="checkbox" id="showrec" onchange="toggleRecent(this.checked)">
   {{ui.recent.show}} (<span id="reccnt">0</span>)</label>
  <span class="mut" style="align-self:center">
   <span class="b safe">{{ui.label.safe}}</span> {{web.legend_safe}} ·
   <span class="b review">{{ui.label.review}}</span> ·
   <span class="b careful">{{ui.label.careful}}</span> {{web.legend_careful}}</span>
 </div>
</header>
<main id="main" class="norecent"><div class="spin">{{ui.loading}} {{ui.loading.desc}}</div></main>
<footer><div class="in"><div><b id="selsz">0 B</b> <span class="mut" id="selcnt">{{ui.sel.none}}</span></div>
<button class="dan" id="go" disabled onclick="confirmClean()"><svg class="ic"><use href="#i-trash"/></svg>{{ui.delete_selected}}</button></div></footer>
<dialog id="dlg"></dialog>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
 <symbol id="i-drive" viewBox="0 0 24 24"><rect x="2" y="13" width="20" height="8" rx="2"/><path d="M5.5 13 8 4h8l2.5 9"/><path d="M6 17h.01M10 17h.01"/></symbol>
 <symbol id="i-refresh" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/></symbol>
 <symbol id="i-check" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></symbol>
 <symbol id="i-trash" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></symbol>
 <symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 3 2 21h20z"/><path d="M12 10v5M12 18h.01"/></symbol>
 <symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></symbol>
 <symbol id="i-lock" viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></symbol>
 <symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/></symbol>
</svg>
<script>
const TOKEN="__TOKEN__",L=__I18N__;let ITEMS=[],RECENT_DAYS=14;const sel=new Set();
const t=(k,v={})=>((v.n===1&&L[k+'.one'])||L[k]||k).replace(/\{(\w+)\}/g,(_,x)=>v[x]??'');
const ic=n=>`<svg class="ic"><use href="#i-${n}"/></svg>`,note=(n,cls,txt)=>`<p class="note ${cls}">${ic(n)}<span>${esc(txt)}</span></p>`;
const fmt=b=>{const u=['B','KB','MB','GB','TB'];let i=0;while(b>=1024&&i<4){b/=1024;i++}return (i?b.toFixed(1):b)+' '+u[i]};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function scan(){
 document.getElementById('main').innerHTML=`<div class="spin">${esc(t('ui.loading'))} ${esc(t('ui.loading.desc'))}</div>`;
 sel.clear();upd();
 const r=await fetch('/api/scan');const d=await r.json();ITEMS=d.items;RECENT_DAYS=d.recent_days;
 document.getElementById('reccnt').textContent=t('web.recent_info',{n:ITEMS.filter(i=>i.recent).length,days:RECENT_DAYS});
 const {total,avail}=d.disk;
 document.getElementById('disk').textContent=t('web.disk',{used:fmt(total-avail),total:fmt(total),free:fmt(avail),found:fmt(ITEMS.filter(i=>!i.recent).reduce((a,i)=>a+i.size,0)),n:ITEMS.length,took:d.took});
 document.getElementById('used').style.width=(100*(total-avail)/total)+'%';
 render(d.errors);
}
function render(errors){
 const groups={};ITEMS.forEach(i=>(groups[i.gkey]??=[]).push(i));
 const show=document.getElementById('showrec').checked,vis=l=>l.filter(i=>show||!i.recent);
 const order=Object.entries(groups).map(([g,l])=>[g,l.sort((a,b)=>b.size-a.size),vis(l).reduce((a,i)=>a+i.size,0),vis(l).length]).filter(x=>x[3]).sort((a,b)=>b[2]-a[2]);
 let h=errors?.length?`<p class="err">${esc(t('web.errors',{e:errors.join('; ')}))}</p>`:'';
 for(const [g,l,tot,n] of order){
  h+=`<section class="grp collapsed"><div class="gh" onclick="this.parentNode.classList.toggle('collapsed')">
  <input type="checkbox" title="${esc(t('ui.tip.select_all'))}" onclick="event.stopPropagation();grp(this,'${g}')"><h2>${esc(l[0].group)} <span class="mut">(${n})</span></h2><span class="sz">${fmt(tot)}</span><span class="arr">▾</span></div>`;
  for(const i of l){
   h+=`<div class="row${i.recent?' recent':''}" id="r${i.id}" onclick="rowClick(event,'${i.id}')"><input type="checkbox" data-id="${i.id}" onchange="tog('${i.id}',this.checked)">
   <div><div class="t">${esc(i.title)}<span class="b ${i.safety}">${esc(t('ui.label.'+i.safety))}</span>${i.recent?`<span class="b recent">${esc(t('ui.label.recent'))}</span>`:''}</div>
   <div class="d">${esc(i.desc)}${esc(when(i))}</div>
   ${i.path?`<div class="p">${esc(i.path)}</div>`:''}${i.paths?`<details><summary>${esc(t('ui.tip.files'))}</summary>${i.paths.map(p=>`<div>${esc(p)}</div>`).join('')}</details>`:''}${i.warn?`<div class="w">${ic('alert')} ${esc(i.warn)}</div>`:''}</div><div class="sz">${fmt(i.size)}</div></div>`;
  }
  h+='</section>';
 }
 document.getElementById('main').innerHTML=h||`<div class="spin">${ic('check')} ${esc(t('ui.nothing'))}</div>`;
}
const ago=d=>d===0?t('ui.ago.today'):t('ui.ago.days',{n:d});
function when(i){const p=[];if(i.used!=null)p.push(t('ui.when.used',{ago:ago(i.used)}));if(i.age!=null&&i.age!==i.used)p.push(t('ui.when.modified',{ago:ago(i.age)}));return p.length?' · '+p.join(' · '):''}
function toggleRecent(on){if(!on)ITEMS.filter(i=>i.recent).forEach(i=>sel.delete(i.id));render();ITEMS.forEach(i=>{const c=document.querySelector(`[data-id="${i.id}"]`);if(c&&sel.has(i.id)){c.checked=true;c.closest('.row').classList.add('on')}});upd()}
function rowClick(e,id){if(e.target.closest('details,input'))return;const c=document.querySelector(`[data-id="${id}"]`);setCb(id,!c.checked)}
function tog(id,on){on?sel.add(id):sel.delete(id);document.getElementById('r'+id).classList.toggle('on',on);upd()}
const shown=i=>document.getElementById('showrec').checked||!i.recent;
function grp(cb,g){ITEMS.filter(i=>i.gkey===g&&shown(i)&&!(cb.checked&&i.recent)).forEach(i=>setCb(i.id,cb.checked))}
function setCb(id,on){const c=document.querySelector(`[data-id="${id}"]`);c.checked=on;tog(id,on)}
function pick(s){ITEMS.forEach(i=>{if(shown(i))setCb(i.id,s!==null&&i.safety===s&&!i.recent);else sel.delete(i.id)});upd()}
function upd(){const l=ITEMS.filter(i=>sel.has(i.id));
 document.getElementById('selsz').textContent=fmt(l.reduce((a,i)=>a+i.size,0));
 document.getElementById('selcnt').textContent=l.length?t('ui.sel.count',{n:l.length}):t('ui.sel.none');
 document.getElementById('go').disabled=!l.length}
function confirmClean(){
 const l=ITEMS.filter(i=>sel.has(i.id)),dlg=document.getElementById('dlg');
 const risky=l.filter(i=>i.safety==='careful').length,rec=l.filter(i=>i.recent).length,root=l.some(i=>i.gkey==='system');
 dlg.innerHTML=`<h3>${esc(t('ui.confirm.heading',{n:l.length}))} (${fmt(l.reduce((a,i)=>a+i.size,0))})</h3>
 ${risky?note('alert','err',t('ui.confirm.careful',{n:risky})):''}
 ${rec?note('clock','err',t('ui.confirm.recent',{n:rec,days:RECENT_DAYS})):''}
 ${root?note('lock','mut',t('ui.confirm.root')):''}
 <ul>${l.map(i=>`<li>${esc(i.title)} — ${fmt(i.size)}</li>`).join('')}</ul>
 ${note('info','mut',t('ui.confirm.permanent'))}
 <div style="display:flex;gap:8px;justify-content:flex-end"><button onclick="dlg.close()">${esc(t('ui.cancel'))}</button><button class="dan" onclick="doClean()">${esc(t('web.yes_delete'))}</button></div>`;
 dlg.showModal();
}
async function doClean(){
 const dlg=document.getElementById('dlg'),ids=[...sel];
 dlg.innerHTML=`<div class="spin">${esc(t('web.deleting'))}</div>`;
 const r=await fetch('/api/clean',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOKEN},body:JSON.stringify({ids})});
 const {results}=await r.json();const by=Object.fromEntries(ITEMS.map(i=>[i.id,i]));
 const ok=results.filter(x=>x.ok);
 dlg.innerHTML=`<h3>${esc(t('web.done',{ok:ok.length,total:results.length,size:fmt(ok.reduce((a,x)=>a+(by[x.id]?.size||0),0))}))}</h3>
 <ul>${results.map(x=>`<li class="${x.ok?'ok':'err'}">${x.ok?'✓':'✗'} ${esc(by[x.id]?.title)} <span class="mut">— ${esc(x.msg)}</span></li>`).join('')}</ul>
 <div style="text-align:right"><button class="pri" onclick="dlg.close();scan()">${esc(t('web.close_rescan'))}</button></div>`;
}
scan();
</script></body></html>"""


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(_("web.started", url=url))
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n" + _("web.bye"))


if __name__ == "__main__":
    main()
