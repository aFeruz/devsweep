#!/usr/bin/env python3
"""Storage Cleaner — laptopdagi keraksiz fayllarni topib, tanlab o'chiradigan lokal app.

Ishga tushirish:  python3 cleaner.py   (brauzerda http://127.0.0.1:8765 ochiladi)
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
    rc, out, _ = run(["du", "-sk", "--one-file-system", str(path)], timeout=600)
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


def item(group, title, desc, size, safety, action, path=None, age=None, warn=None,
         used=None, track_recent=False, paths=None):
    """age — oxirgi o'zgarish (kun); used — oxirgi ishlatilgan (kun).
    track_recent=True bo'lsa, RECENT_DAYS ichida ishlatilgan narsa "yaqinda" deb belgilanadi."""
    iid = f"i{len(ACTIONS)}"
    ACTIONS[iid] = action
    last = used if used is not None else age
    recent = bool(track_recent and last is not None and last < RECENT_DAYS)
    if recent:
        safety = CAREFUL
    return Item(id=iid, group=group, title=title, desc=desc, size=size, safety=safety,
                path=str(path) if path else None, paths=paths, age=age, used=used, warn=warn, recent=recent)


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
                raise RuntimeError(f"Xavfsizlik: {p} uy papkasidan tashqarida")
            if p.is_file() or p.is_symlink():
                p.unlink()
                n += 1
        return f"{n} ta fayl o'chirildi"
    return {"kind": "py", "fn": _do}


def rm_path(path, contents_only=False):
    """Faqat $HOME ichidagi yo'llarni o'chiradi."""
    def _do():
        p = Path(path)
        real = p.resolve()
        if HOME.resolve() not in real.parents:
            raise RuntimeError(f"Xavfsizlik: {p} uy papkasidan tashqarida")
        if not p.exists():
            return "allaqachon yo'q"
        targets = list(p.iterdir()) if contents_only else [p]
        for t in targets:
            if t.is_symlink() or t.is_file():
                t.unlink()
            else:
                shutil.rmtree(t)
        return "o'chirildi"
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
        rc, o, _ = run(["docker", kind, "inspect", "--format", fmt, *ids[i:i + 200]], timeout=120)
        for line in o.splitlines():
            parts = line.split("|")
            out[parts[0]] = parts[1:]
    return out


def scan_docker():
    items = []
    if not shutil.which("docker"):
        return items
    rc, out, _ = run(["docker", "system", "df", "-v", "--format", "{{json .}}"], timeout=120)
    if rc != 0:
        return items
    d = json.loads(out)
    G = "Docker"
    hours = f"{RECENT_DAYS * 24}h"

    # --- konteynerlar: oxirgi ishga tushgan/to'xtagan vaqtiga qarab
    conts = [c for c in d.get("Containers") or [] if c.get("State") != "running"]
    info = docker_inspect("container", [c["ID"] for c in conts],
                          "{{.Id}}|{{.Created}}|{{.State.StartedAt}}|{{.State.FinishedAt}}")
    for c in conts:
        full = next((v for k, v in info.items() if k.startswith(c["ID"])), [])
        used = days_since(*map(parse_time, full))
        items.append(item(G, f"To'xtatilgan konteyner: {c.get('Names', '?')}",
                          f"{c.get('Image', '')} · {c.get('Status', '')}. Volume'dagi ma'lumotlar o'chmaydi, "
                          f"lekin konteynerni qayta yaratish kerak bo'ladi.",
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
        items.append(item(G, f"Nomsiz (dangling) image'lar ({len(old_d)} ta, {RECENT_DAYS}+ kunlik)",
                          f"Eski build'lardan qolgan <none> image'lar. Oxirgi {RECENT_DAYS} kundagilari tegilmaydi"
                          f" ({len(dangling) - len(old_d)} ta).",
                          sum(parse_docker_size(i.get("UniqueSize")) for i in old_d), SAFE,
                          cmd("docker", "image", "prune", "-f", "--filter", f"until={hours}")))

    for i in unused:
        if i.get("Repository") == "<none>":
            continue
        ref = f"{i['Repository']}:{i['Tag']}"
        items.append(item(G, f"Image: {ref}",
                          f"Hech bir konteyner ishlatmayapti · to'liq hajmi {i.get('Size')} "
                          f"(o'ziga xos qismi ko'rsatilgan, umumiy qatlamlar ham bo'shashi mumkin)",
                          parse_docker_size(i.get("UniqueSize")), REVIEW, cmd("docker", "rmi", ref),
                          used=i["_used"], track_recent=True))

    # --- build cache: LastUsedAt bo'yicha, faqat eskilari
    cache = [c for c in d.get("BuildCache") or [] if c.get("InUse") != "true"]
    for c in cache:
        c["_used"] = days_since(parse_time(c.get("LastUsedAt")), parse_time(c.get("CreatedAt")))
    old_c = [c for c in cache if (c["_used"] or 0) >= RECENT_DAYS]
    if old_c:
        items.append(item(G, f"Build cache ({len(old_c)} ta yozuv, {RECENT_DAYS}+ kun ishlatilmagan)",
                          f"Eski docker build keshi. Oxirgi {RECENT_DAYS} kunda ishlatilganlari "
                          f"({len(cache) - len(old_c)} ta) saqlanadi.",
                          sum(parse_docker_size(c.get("Size")) for c in old_c), SAFE,
                          cmd("docker", "builder", "prune", "-a", "-f", "--filter", f"until={hours}")))

    # --- volume'lar: ulanmagan, yaratilgan vaqtiga qarab
    vols = [v for v in d.get("Volumes") or [] if v.get("Links") == "0"]
    info = docker_inspect("volume", [v["Name"] for v in vols], "{{.Name}}|{{.CreatedAt}}")
    for v in vols:
        v["_used"] = days_since(*map(parse_time, info.get(v["Name"], [])))
    tiny = [v for v in vols if parse_docker_size(v.get("Size")) < 1e6 and (v["_used"] or 0) >= RECENT_DAYS]
    if tiny:
        items.append(item(G, f"Bo'sh/kichik ishlatilmagan volume'lar ({len(tiny)} ta)",
                          f"Hajmi 1 MB dan kichik, hech bir konteynerga ulanmagan, {RECENT_DAYS}+ kunlik.",
                          sum(parse_docker_size(v.get("Size")) for v in tiny), SAFE,
                          cmd("docker", "volume", "rm", *[v["Name"] for v in tiny])))
    for v in vols:
        if v in tiny or (parse_docker_size(v.get("Size")) < 1e6 and (v["_used"] or 0) < RECENT_DAYS):
            continue
        anon = "com.docker.volume.anonymous" in (v.get("Labels") or "")
        items.append(item(G, f"Volume: {v['Name'][:40]}",
                          ("Anonim volume, hech bir konteynerga ulanmagan." if anon else
                           "Nomli volume — ichida ma'lumotlar bazasi bo'lishi mumkin! Ishonchingiz komil bo'lsa o'chiring."),
                          parse_docker_size(v.get("Size")), REVIEW if anon else CAREFUL,
                          cmd("docker", "volume", "rm", v["Name"]), used=v["_used"], track_recent=True))
    return items


KNOWN_CACHE = {
    "google-chrome": "Chrome brauzer keshi (Chrome yopiq bo'lsa yaxshi)",
    "yarn": "Yarn paketlar keshi — kerak bo'lsa qayta yuklanadi",
    "ms-playwright": "Playwright brauzerlari — testlar uchun qayta yuklanadi",
    "ms-playwright-go": "Playwright-go brauzerlari",
    "pip": "pip keshi",
    "typescript": "TypeScript tiplari keshi",
    "tracker3": "GNOME fayl indeksi — o'zi qayta tuziladi",
    "mesa_shader_cache": "GPU shader keshi",
    "prisma": "Prisma engine keshi",
    "node-gyp": "node-gyp header'lari",
    "JetBrains": "JetBrains IDE keshi/indekslari",
    "thumbnails": "Rasm kichik nusxalari",
}

APP_PROCS = {"google-chrome": ("chrome",), "Cursor": ("cursor", "Cursor"), "Code": ("code",),
             "Code - Insiders": ("code-insiders",), "TelegramDesktop": ("Telegram", "telegram-desktop")}


def warn_for(name):
    procs = APP_PROCS.get(name)
    if procs and running(*procs):
        return f"{name} hozir ishlayapti — o'chirishdan oldin yopib qo'ying"
    return None


def scan_user_paths():
    """(group, title, desc, path, safety, contents_only)"""
    cands = []
    cache = HOME / ".cache"
    if cache.is_dir():
        for p in cache.iterdir():
            if p.is_dir() and not p.is_symlink():
                cands.append(("Kesh (~/.cache)", p.name, KNOWN_CACHE.get(p.name, "Dastur keshi — odatda qayta yaratiladi"),
                              p, SAFE, False, APP_PROCS.get(p.name) and warn_for(p.name)))

    dev = [
        (".npm/_cacache", "npm keshi", "npm paketlar keshi — kerak bo'lsa qayta yuklanadi"),
        (".gradle/caches", "Gradle keshi", "Gradle kutubxonalari — keyingi build'da qayta yuklanadi"),
        (".gradle/daemon", "Gradle daemon loglari", "Eski daemon loglari va holati"),
        (".gradle/wrapper/dists", "Gradle wrapper versiyalari", "Yuklangan Gradle distributivlari"),
        (".m2/repository", "Maven repo", "Maven kutubxonalari keshi"),
        (".cargo/registry", "Cargo registry", "Rust crate keshi"),
        ("go/pkg/mod", "Go modullari", "Go modul keshi"),
        (".nvm/.cache", "nvm keshi", "Node yuklamalari keshi"),
        (".local/share/pnpm/store", "pnpm store", "pnpm paketlar ombori"),
        (".bun/install/cache", "bun keshi", "bun paketlar keshi"),
    ]
    for rel, title, desc in dev:
        p = HOME / rel
        if p.is_dir():
            cands.append(("Dasturlash keshlari", title, desc, p, SAFE, False, None))

    cfg = HOME / ".config"
    if cfg.is_dir():
        for app in cfg.iterdir():
            if not app.is_dir():
                continue
            for sub in ("Cache", "Code Cache", "GPUCache", "CachedData", "CachedExtensionVSIXs",
                        "Service Worker/CacheStorage", "logs", "Crashpad"):
                p = app / sub
                if p.is_dir():
                    cands.append(("Dasturlar keshi", f"{app.name} → {sub}", "Electron/VS Code tipidagi dastur keshi",
                                  p, SAFE, False, warn_for(app.name)))

    chrome = cfg / "google-chrome"
    if chrome.is_dir():
        p = chrome / "OptGuideOnDeviceModel"
        if p.is_dir():
            cands.append(("Dasturlar keshi", "Chrome on-device AI modeli (Gemini Nano)",
                          "Chrome o'zi yuklagan AI model. chrome://flags da 'optimization-guide-on-device-model' ni "
                          "o'chirmasangiz qayta yuklab olishi mumkin.", p, REVIEW, False, warn_for("google-chrome")))
        for prof in chrome.iterdir():
            for sub in ("Service Worker/CacheStorage", "Code Cache", "GPUCache"):
                p = prof / sub
                if prof.is_dir() and p.is_dir():
                    cands.append(("Dasturlar keshi", f"Chrome [{prof.name}] → {sub}", "Sayt keshlari, qayta yaratiladi",
                                  p, SAFE, False, warn_for("google-chrome")))

    p = cfg / "Cursor" / "snapshots"
    if p.is_dir():
        cands.append(("Dasturlar keshi", "Cursor agent snapshot'lari",
                      "Cursor AI agent o'zgarishlarining eski nusxalari (checkpoint). Eski chatlarda 'restore' ishlamay qoladi.",
                      p, REVIEW, False, warn_for("Cursor")))

    p = HOME / ".local/share/TelegramDesktop/tdata/user_data"
    if p.is_dir():
        cands.append(("Dasturlar keshi", "Telegram media keshi",
                      "Ko'rilgan rasm/video keshi. Xabarlar o'chmaydi, media qayta yuklanadi.",
                      p, REVIEW, False, warn_for("TelegramDesktop")))

    snapdir = HOME / "snap"
    if snapdir.is_dir():
        for p in snapdir.glob("*/*/.cache"):
            if p.is_dir() and not p.is_symlink():
                cands.append(("Kesh (~/.cache)", f"snap: {p.parts[-3]} keshi", "Snap dastur keshi", p, SAFE, False, None))

    trash = HOME / ".local/share/Trash"
    if trash.is_dir():
        cands.append(("Tizim", "Savatcha (Trash)", "O'chirilgan fayllar savatchasi", trash, SAFE, True, None))

    items = []
    with ThreadPoolExecutor(8) as ex:
        sizes = list(ex.map(lambda c: du(c[3]), cands))
    for (g, title, desc, p, safety, contents, warn), size in zip(cands, sizes):
        if size >= MIN_SIZE:
            items.append(item(g, title, desc, size, safety, rm_path(p, contents), path=p, age=age_days(p), warn=warn))
    return items


ARTIFACTS = {
    "node_modules": (None, "npm/yarn paketlari — `npm install` bilan qayta tiklanadi"),
    ".next": (None, "Next.js build keshi — `next build`/`dev` qayta yaratadi"),
    ".nuxt": (None, "Nuxt build keshi"),
    ".turbo": (None, "Turborepo keshi"),
    ".angular": (None, "Angular keshi"),
    ".parcel-cache": (None, "Parcel keshi"),
    ".venv": ("pyvenv.cfg", "Python virtual muhit — `pip install -r requirements.txt` bilan tiklanadi"),
    "venv": ("pyvenv.cfg", "Python virtual muhit — `pip install -r requirements.txt` bilan tiklanadi"),
    "target": ("..Cargo.toml|..pom.xml", "Rust/Maven build natijasi — qayta build qilinadi"),
    "build": ("..build.gradle|..build.gradle.kts", "Gradle build natijasi — qayta build qilinadi"),
}
# Uy papkasining yuqori darajasida aylanilmaydigan papkalar (keshlar boshqa skanerda)
SKIP_DIRS = {"snap", "go", "Android"}  # Android SDK fayllari emulator uchun kerak

JUNK = [
    ("Chala yuklangan fayllar", SAFE, "Brauzer yuklashi tugallanmagan — ochilmaydi, keraksiz",
     re.compile(r".*\.(crdownload|part|partial|download)$", re.I)),
    ("Log fayllar", REVIEW, "Dasturlar/npm/Java crash loglari — odatda keraksiz",
     re.compile(r"(.*\.log(\.\d+)?|npm-debug\.log.*|yarn-error\.log|hs_err_pid\d+\.log|replay_pid\d+\.log)$", re.I)),
    ("Vaqtinchalik va zaxira fayllar", REVIEW, "Muharrir zaxiralari, .tmp, .swp, Thumbs.db, .DS_Store",
     re.compile(r"(.*\.(tmp|temp|swp|swo|bak|old|orig)|.*~|\.DS_Store|Thumbs\.db|desktop\.ini)$", re.I)),
    ("Core dump fayllar", SAFE, "Dastur yiqilganda qolgan xotira nusxalari",
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
    return f"{repo.name} git loyihasi ichida — o'chirsangiz loyiha buzilishi mumkin" if repo else None


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
        items.append(item("Loyihalardagi build/paket papkalari", f"{p.parent.name}/{p.name}",
                          ARTIFACTS[p.name][1] + " · vaqt loyiha fayllari bo'yicha",
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
            items.append(item("Dublikat fayllar", p.name, f"Aynan bir xil nusxa saqlanadi: {keep}",
                              st.st_size, CAREFUL if warn else REVIEW, rm_files([p]), path=p, warn=warn,
                              age=days_since(st.st_mtime), used=days_since(st.st_mtime, st.st_atime),
                              track_recent=True))

    # --- installerlar va katta fayllar
    for p, st in files:
        if p in taken:
            continue
        used = days_since(st.st_mtime, st.st_atime)
        if INSTALLER.fullmatch(p.name) and st.st_size >= MIN_SIZE:
            items.append(item("O'rnatish fayllari (.deb, .apk, .iso…)", p.name,
                              "O'rnatib bo'lingan bo'lsa odatda keraksiz", st.st_size, REVIEW, rm_files([p]),
                              path=p, warn=file_warn(p), age=days_since(st.st_mtime), used=used, track_recent=True))
        elif st.st_size >= BIG_FILE:
            items.append(item(f"Katta fayllar ({BIG_FILE >> 20} MB+)", p.name,
                              "Katta fayl — kerakligini o'zingiz tekshiring", st.st_size, CAREFUL, rm_files([p]),
                              path=p, warn=file_warn(p), age=days_since(st.st_mtime), used=used, track_recent=True))

    # --- keraksiz fayllar (turlari bo'yicha jamlangan)
    for (title, safety, desc, _), lst in junk.items():
        old = [(p, st) for p, st in lst if (days_since(st.st_mtime) or 0) >= 1]
        size = sum(st.st_size for _, st in old)
        if size >= 100 * 1024:
            old.sort(key=lambda x: -x[1].st_size)
            paths = [str(p) for p, _ in old]
            items.append(item("Keraksiz fayllar", f"{title} ({len(old)} ta)", desc, size, safety,
                              rm_files(paths), paths=paths[:200]))
    return items


def scan_system():
    G = "Tizim (parol so'raladi)"
    items = []
    rc, out, _ = run(["snap", "list", "--all"])
    if rc == 0:
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and "disabled" in parts[-1]:
                name, rev = parts[0], parts[2]
                f = Path(f"/var/lib/snapd/snaps/{name}_{rev}.snap")
                size = f.stat().st_size if f.exists() else 0
                items.append(item(G, f"Eski snap versiyasi: {name} (rev {rev})",
                                  "Snap yangilanganda eski versiyani saqlab qoladi. Hozirgi versiya ishlayveradi.",
                                  size, SAFE, root_cmd("snap", "remove", name, f"--revision={rev}")))
    size = du("/var/cache/apt/archives")
    if size >= MIN_SIZE:
        items.append(item(G, "APT paketlar keshi", "Yuklab olingan .deb fayllar — o'rnatilganlarga ta'sir qilmaydi",
                          size, SAFE, root_cmd("apt-get", "clean")))
    rc, out, _ = run(["journalctl", "--disk-usage"])
    m = re.search(r"([\d.]+)([KMGT])", out)
    if m:
        size = int(float(m.group(1)) * {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}[m.group(2)])
        if size > 150 << 20:
            items.append(item(G, "Tizim jurnallari (journal)", "Eski loglar, oxirgi 100 MB qoldiriladi",
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
        rc, out, _ = run(["df", "-B1", "--output=size,avail", str(HOME)])
        total, avail = (int(x) for x in out.splitlines()[1].split()) if rc == 0 else (0, 0)
        return {"items": items, "errors": errors, "took": round(time.time() - t, 1), "recent_days": RECENT_DAYS,
                "disk": {"total": total, "avail": avail}}


def clean(ids):
    results = []
    root_batch = []
    for iid in ids:
        a = ACTIONS.get(iid)
        if a is None:
            results.append({"id": iid, "ok": False, "msg": "Noma'lum element — qayta skanerlang"})
        elif a["kind"] == "py":
            try:
                results.append({"id": iid, "ok": True, "msg": a["fn"]()})
            except Exception as e:
                results.append({"id": iid, "ok": False, "msg": str(e)})
        elif a["kind"] == "cmd":
            rc, out, err = run(a["cmd"], timeout=900)
            results.append({"id": iid, "ok": rc == 0, "msg": (err or out).strip()[-300:] or "bajarildi"})
        else:
            root_batch.append((iid, a["cmd"]))
    if root_batch:
        # Bitta parol so'rovi bilan barcha root buyruqlarini bajaramiz
        script = "\n".join(f"{shlex.join(c)} && echo 'OK {i}' || echo 'FAIL {i}'" for i, c in root_batch)
        rc, out, err = run(["pkexec", "sh", "-c", script], timeout=1800)
        for i, _ in root_batch:
            ok = f"OK {i}" in out
            results.append({"id": i, "ok": ok, "msg": "bajarildi" if ok else (err.strip()[-300:] or "bekor qilindi")})
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
        if self.path == "/":
            self.send(200, PAGE.replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
        elif self.path == "/api/scan":
            self.send(200, json.dumps(full_scan()))
        else:
            self.send(404, "{}")

    def do_POST(self):
        if self.path != "/api/clean" or self.headers.get("X-Token") != TOKEN:
            return self.send(403, '{"error":"forbidden"}')
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
        self.send(200, json.dumps({"results": clean(body.get("ids", []))}))


PAGE = r"""<!doctype html>
<html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Storage Cleaner</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1c2230;--mut:#6b7385;--line:#e4e7ec;--acc:#2f6fed;--safe:#1f9d55;--rev:#c98a00;--car:#d64545;--sel:#eef3ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--mut:#8b93a5;--line:#262c38;--acc:#5b8cff;--safe:#3ec27a;--rev:#e3a92b;--car:#f06565;--sel:#1b2436}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 16px 8px;max-width:1000px;margin:auto}
h1{margin:0 0 4px;font-size:22px}.mut{color:var(--mut)}
.bar{height:10px;background:var(--line);border-radius:6px;overflow:hidden;margin:10px 0 4px}.bar>i{display:block;height:100%;background:var(--acc)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:7px 12px;border-radius:8px;cursor:pointer}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}button.dan{background:var(--car);border-color:var(--car);color:#fff}
button:disabled{opacity:.5;cursor:default}
main{max-width:1000px;margin:auto;padding:0 16px 120px}
.grp{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden}
.gh{display:flex;align-items:center;gap:10px;padding:12px 14px;cursor:pointer;user-select:none}
.gh h2{font-size:15px;margin:0;flex:1}.gh .sz{font-weight:600}
.row{display:grid;grid-template-columns:22px 1fr auto;gap:10px;padding:10px 14px;border-top:1px solid var(--line);align-items:start}
.row.on{background:var(--sel)}.row{cursor:pointer}
.t{font-weight:500;word-break:break-word}.d{font-size:12.5px;color:var(--mut)}.p{font:11.5px ui-monospace,monospace;color:var(--mut);word-break:break-all}
.w{font-size:12px;color:var(--car)}
.sz{white-space:nowrap;text-align:right}
.b{font-size:11px;padding:1px 7px;border-radius:10px;border:1px solid;margin-left:6px;white-space:nowrap}
.b.safe{color:var(--safe)}.b.review{color:var(--rev)}.b.careful{color:var(--car)}
input[type=checkbox]{width:16px;height:16px;margin-top:2px;accent-color:var(--acc)}
footer{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:12px 16px}
footer .in{max-width:1000px;margin:auto;display:flex;align-items:center;gap:12px;flex-wrap:wrap}footer .in>div{flex:1}
.hide,.norecent .row.recent{display:none}.b.recent{color:var(--acc)}
details{font-size:12px;color:var(--mut)}details div{font:11.5px ui-monospace,monospace;word-break:break-all}.collapsed .row{display:none}
dialog{border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--fg);max-width:640px;width:calc(100% - 32px)}
dialog ul{max-height:45vh;overflow:auto;padding-left:18px}.ok{color:var(--safe)}.err{color:var(--car)}
.spin{padding:60px 0;text-align:center}
</style></head><body>
<header>
 <h1>🧹 Storage Cleaner</h1>
 <div class="mut" id="disk">Disk ma'lumoti yuklanmoqda…</div>
 <div class="bar"><i id="used" style="width:0"></i></div>
 <div class="tools">
  <button onclick="scan()">🔄 Qayta skanerlash</button>
  <button onclick="pick('safe')">✅ Xavfsizlarini tanlash</button>
  <button onclick="pick(null)">Tanlovni tozalash</button>
  <label style="align-self:center"><input type="checkbox" id="showrec" onchange="toggleRecent(this.checked)">
   Yaqinda ishlatilganlarni ham ko'rsatish (<span id="reccnt">0</span>)</label>
  <span class="mut" style="align-self:center">
   <span class="b safe">xavfsiz</span> qayta tiklanadi ·
   <span class="b review">ko'rib chiqing</span> ·
   <span class="b careful">ehtiyot bo'ling</span> ma'lumot yo'qolishi mumkin</span>
 </div>
</header>
<main id="main" class="norecent"><div class="spin">Skanerlanmoqda… (1-2 daqiqa olishi mumkin)</div></main>
<footer><div class="in"><div><b id="selsz">0 B</b> <span class="mut" id="selcnt">tanlanmagan</span></div>
<button class="dan" id="go" disabled onclick="confirmClean()">🗑 Tanlanganlarni o'chirish</button></div></footer>
<dialog id="dlg"></dialog>
<script>
const TOKEN="__TOKEN__";let ITEMS=[],RECENT_DAYS=14;const sel=new Set();
const fmt=b=>{const u=['B','KB','MB','GB','TB'];let i=0;while(b>=1024&&i<4){b/=1024;i++}return (i?b.toFixed(1):b)+' '+u[i]};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LBL={safe:'xavfsiz',review:"ko'rib chiqing",careful:'ehtiyot bo\'ling'};
async function scan(){
 document.getElementById('main').innerHTML='<div class="spin">Skanerlanmoqda… (1-2 daqiqa olishi mumkin)</div>';
 sel.clear();upd();
 const r=await fetch('/api/scan');const d=await r.json();ITEMS=d.items;RECENT_DAYS=d.recent_days;
 document.getElementById('reccnt').textContent=`${ITEMS.filter(i=>i.recent).length} ta, oxirgi ${RECENT_DAYS} kun`;
 const {total,avail}=d.disk;
 document.getElementById('disk').textContent=`Disk: ${fmt(total-avail)} ishlatilgan / ${fmt(total)} · bo'sh: ${fmt(avail)} · topilgan: ${fmt(ITEMS.reduce((a,i)=>a+i.size,0))} (${ITEMS.length} ta, ${d.took}s)`;
 document.getElementById('used').style.width=(100*(total-avail)/total)+'%';
 render(d.errors);
}
function render(errors){
 const groups={};ITEMS.forEach(i=>(groups[i.group]??=[]).push(i));
 const show=document.getElementById('showrec').checked,vis=l=>l.filter(i=>show||!i.recent);
 const order=Object.entries(groups).map(([g,l])=>[g,l.sort((a,b)=>b.size-a.size),vis(l).reduce((a,i)=>a+i.size,0),vis(l).length]).filter(x=>x[3]).sort((a,b)=>b[2]-a[2]);
 let h=errors?.length?`<p class="err">Ba'zi skanerlar xato berdi: ${esc(errors.join('; '))}</p>`:'';
 for(const [g,l,tot,n] of order){
  h+=`<section class="grp collapsed"><div class="gh" onclick="this.parentNode.classList.toggle('collapsed')">
  <input type="checkbox" onclick="event.stopPropagation();grp(this,'${esc(g)}')"><h2>▸ ${esc(g)} <span class="mut">(${n})</span></h2><span class="sz">${fmt(tot)}</span></div>`;
  for(const i of l){
   h+=`<div class="row${i.recent?' recent':''}" id="r${i.id}" onclick="rowClick(event,'${i.id}')"><input type="checkbox" data-id="${i.id}" onchange="tog('${i.id}',this.checked)">
   <div><div class="t">${esc(i.title)}<span class="b ${i.safety}">${LBL[i.safety]}</span>${i.recent?'<span class="b recent">yaqinda ishlatilgan</span>':''}</div>
   <div class="d">${esc(i.desc)}${when(i)}</div>
   ${i.path?`<div class="p">${esc(i.path)}</div>`:''}${i.paths?`<details><summary>Fayllar ro'yxati</summary>${i.paths.map(p=>`<div>${esc(p)}</div>`).join('')}</details>`:''}${i.warn?`<div class="w">⚠ ${esc(i.warn)}</div>`:''}</div><div class="sz">${fmt(i.size)}</div></div>`;
  }
  h+='</section>';
 }
 document.getElementById('main').innerHTML=h||'<div class="spin">Hech narsa topilmadi 🎉</div>';
}
const ago=d=>d===0?'bugun':d+' kun avval';
function when(i){const p=[];if(i.used!=null)p.push(`oxirgi ishlatilgan: ${ago(i.used)}`);if(i.age!=null&&i.age!==i.used)p.push(`o'zgargan: ${ago(i.age)}`);return p.length?' · '+p.join(' · '):''}
function toggleRecent(on){if(!on)ITEMS.filter(i=>i.recent).forEach(i=>sel.delete(i.id));render();ITEMS.forEach(i=>{const c=document.querySelector(`[data-id="${i.id}"]`);if(c&&sel.has(i.id)){c.checked=true;c.closest('.row').classList.add('on')}});upd()}
function rowClick(e,id){if(e.target.closest('details,input'))return;const c=document.querySelector(`[data-id="${id}"]`);setCb(id,!c.checked)}
function tog(id,on){on?sel.add(id):sel.delete(id);document.getElementById('r'+id).classList.toggle('on',on);upd()}
const shown=i=>document.getElementById('showrec').checked||!i.recent;
function grp(cb,g){ITEMS.filter(i=>i.group===g&&shown(i)&&!(cb.checked&&i.recent)).forEach(i=>setCb(i.id,cb.checked))}
function setCb(id,on){const c=document.querySelector(`[data-id="${id}"]`);c.checked=on;tog(id,on)}
function pick(s){ITEMS.forEach(i=>{if(shown(i))setCb(i.id,s!==null&&i.safety===s&&!i.recent);else sel.delete(i.id)});upd()}
function upd(){const l=ITEMS.filter(i=>sel.has(i.id));
 document.getElementById('selsz').textContent=fmt(l.reduce((a,i)=>a+i.size,0));
 document.getElementById('selcnt').textContent=l.length?`${l.length} ta tanlandi`:'tanlanmagan';
 document.getElementById('go').disabled=!l.length}
function confirmClean(){
 const l=ITEMS.filter(i=>sel.has(i.id)),dlg=document.getElementById('dlg');
 const risky=l.filter(i=>i.safety==='careful').length,rec=l.filter(i=>i.recent).length,root=l.some(i=>i.group.includes('parol'));
 dlg.innerHTML=`<h3>${l.length} ta element o'chirilsinmi? (${fmt(l.reduce((a,i)=>a+i.size,0))})</h3>
 ${risky?`<p class="err">⚠ ${risky} ta "ehtiyot bo'ling" belgili element bor — ular qaytarib bo'lmaydi!</p>`:''}
 ${rec?`<p class="err">⚠ ${rec} tasi oxirgi ${RECENT_DAYS} kunda ishlatilgan!</p>`:''}
 ${root?'<p class="mut">Tizim elementlari uchun parol oynasi chiqadi.</p>':''}
 <ul>${l.map(i=>`<li>${esc(i.title)} — ${fmt(i.size)}</li>`).join('')}</ul>
 <p class="mut">Bu amalni ortga qaytarib bo'lmaydi (savatchaga tushmaydi).</p>
 <div style="display:flex;gap:8px;justify-content:flex-end"><button onclick="dlg.close()">Bekor qilish</button><button class="dan" onclick="doClean()">Ha, o'chirish</button></div>`;
 dlg.showModal();
}
async function doClean(){
 const dlg=document.getElementById('dlg'),ids=[...sel];
 dlg.innerHTML='<div class="spin">O\'chirilmoqda… (Docker/snap uchun biroz vaqt ketadi)</div>';
 const r=await fetch('/api/clean',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOKEN},body:JSON.stringify({ids})});
 const {results}=await r.json();const by=Object.fromEntries(ITEMS.map(i=>[i.id,i]));
 const ok=results.filter(x=>x.ok);
 dlg.innerHTML=`<h3>Tayyor: ${ok.length}/${results.length} muvaffaqiyatli · ~${fmt(ok.reduce((a,x)=>a+(by[x.id]?.size||0),0))} bo'shatildi</h3>
 <ul>${results.map(x=>`<li class="${x.ok?'ok':'err'}">${x.ok?'✓':'✗'} ${esc(by[x.id]?.title)} <span class="mut">— ${esc(x.msg)}</span></li>`).join('')}</ul>
 <div style="text-align:right"><button class="pri" onclick="dlg.close();scan()">Yopish va qayta skanerlash</button></div>`;
}
scan();
</script></body></html>"""


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Storage Cleaner ishga tushdi: {url}  (to'xtatish: Ctrl+C)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nXayr!")


if __name__ == "__main__":
    main()
