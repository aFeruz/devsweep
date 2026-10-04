#!/usr/bin/env python3
"""Storage Cleaner — GTK4/libadwaita oynali ilova (GNOME uslubida).

Ishga tushirish:  python3 gui.py
Skanerlash va o'chirish mantiqi cleaner.py dan olinadi.
"""
import json
import sys
import threading
from collections import defaultdict
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleaner  # noqa: E402

APP_ID = "uz.feruz.StorageCleaner"
SETTINGS = Path(GLib.get_user_config_dir()) / "storage-cleaner" / "settings.json"
FONT_MIN, FONT_MAX, FONT_DEFAULT = 10, 20, 13

LABEL = {cleaner.SAFE: ("xavfsiz", "success"), cleaner.REVIEW: ("ko'rib chiqing", "warning"),
         cleaner.CAREFUL: ("ehtiyot bo'ling", "error")}
GROUP_ICON = {
    "Docker": "application-x-executable-symbolic",
    "Tizim": "emblem-system-symbolic",
    "Kesh": "folder-download-symbolic",
    "Dasturlar": "application-x-addon-symbolic",
    "Dasturlash": "utilities-terminal-symbolic",
    "Loyihalardagi": "folder-symbolic",
    "Dublikat": "edit-copy-symbolic",
    "Katta": "drive-harddisk-symbolic",
    "Keraksiz": "user-trash-symbolic",
    "O'rnatish": "package-x-generic-symbolic",
}

CSS = """
window.sc {{ font-size: {font}pt; }}
.hero-size {{ font-size: 2.8em; font-weight: 800; }}
.disk-free {{ font-size: 1.9em; font-weight: 800; }}
.card-title {{ font-size: 1.25em; font-weight: 700; }}
.card-pad {{ padding: 22px; }}
.size-label {{ font-weight: 700; font-feature-settings: "tnum"; }}
.badge {{ font-size: 0.8em; padding: 2px 9px; border-radius: 99px; border: 1px solid currentColor; }}
.big-button {{ font-size: 1.15em; font-weight: 700; padding: 12px 32px; }}
.bottom-bar {{ padding: 12px 18px; border-top: 1px solid alpha(currentColor, 0.15); }}
levelbar.disk-bar trough, levelbar.disk-bar block {{ min-height: 14px; border-radius: 7px; }}
.hint {{ font-size: 0.9em; }}
/* Yopiq bo'lim: ⌄ (pastda ochiladi), ochiq: ⌃ — Yaru teskari ko'rsatgani uchun aniq belgilaymiz */
row.expander image.expander-row-arrow {{
  -gtk-icon-source: -gtk-icontheme("pan-down-symbolic");
  -gtk-icon-transform: rotate(0turn);
  transition: -gtk-icon-transform 200ms ease;
}}
row.expander:checked image.expander-row-arrow {{ -gtk-icon-transform: rotate(0.5turn); }}
"""


def fmt(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {u}" if u == "B" else f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"


def ago(d):
    return "bugun" if d == 0 else f"{d} kun avval"


def group_icon(name):
    return next((v for k, v in GROUP_ICON.items() if name.startswith(k)), "folder-symbolic")


def is_root(i):
    return "parol" in i["group"]


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(s):
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(s))
    except OSError:
        pass


def scrolled_label(text, height):
    lbl = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
    return Gtk.ScrolledWindow(child=lbl, min_content_height=height, propagate_natural_width=True)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Storage Cleaner", default_width=980, default_height=860)
        self.add_css_class("sc")
        self.settings = load_settings()
        self.items, self.disk = [], {"total": 0, "avail": 0}
        self.selected, self.checks = set(), {}
        self.query, self.show_recent, self.focus_group = "", False, None
        self.include_root = self.settings.get("include_root", True)

        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.apply_font()
        self.setup_actions(app)

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        # --- sarlavha: varaqlar + tugmalar
        header = Adw.HeaderBar()
        self.tabs = Adw.ViewStack()
        header.set_title_widget(Adw.ViewSwitcher(stack=self.tabs, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Qayta skanerlash (F5)")
        self.refresh_btn.connect("clicked", lambda *_: self.scan())
        header.pack_start(self.refresh_btn)

        menu = Gio.Menu()
        sel = Gio.Menu()
        sel.append("Xavfsizlarini tanlash", "win.pick-safe")
        sel.append("Tanlovni tozalash", "win.pick-none")
        menu.append_section("Batafsil ro'yxat", sel)
        font = Gio.Menu()
        font.append("Yozuvni kattalashtirish", "win.font-up")
        font.append("Yozuvni kichraytirish", "win.font-down")
        font.append("Standart o'lcham", "win.font-reset")
        menu.append_section("Yozuv o'lchami", font)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menyu"))
        self.search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Qidirish (Ctrl+F)")
        header.pack_end(self.search_btn)
        view.add_top_bar(header)

        # --- yuklanish / asosiy
        self.root = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.loading = Adw.StatusPage(title="Skanerlanmoqda…", description="Bu 1-2 daqiqa olishi mumkin",
                                      child=Gtk.Spinner(spinning=True, width_request=56, height_request=56))
        self.root.add_named(self.loading, "loading")
        self.root.add_named(self.tabs, "main")
        view.set_content(self.root)

        self.overview_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.tabs.add_titled_with_icon(self.overview_scroll, "overview", "Umumiy", "starred-symbolic")
        self.tabs.add_titled_with_icon(self.build_details(), "details", "Batafsil", "view-list-symbolic")
        self.tabs.connect("notify::visible-child-name", self.on_tab_changed)

        self.scan()

    # ---------------------------------------------------------------- sozlamalar
    def setup_actions(self, app):
        for name, fn, accels in (
                ("font-up", lambda *_: self.change_font(1), ["<Ctrl>plus", "<Ctrl>equal", "<Ctrl>KP_Add"]),
                ("font-down", lambda *_: self.change_font(-1), ["<Ctrl>minus", "<Ctrl>KP_Subtract"]),
                ("font-reset", lambda *_: self.change_font(0), ["<Ctrl>0"]),
                ("pick-safe", lambda *_: self.pick_safe(), []),
                ("pick-none", lambda *_: self.pick_none(), []),
                ("refresh", lambda *_: self.scan(), ["F5", "<Ctrl>r"]),
                ("search", lambda *_: self.open_search(), ["<Ctrl>f"])):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", fn)
            self.add_action(act)
            app.set_accels_for_action(f"win.{name}", accels)

    def apply_font(self):
        size = self.settings.get("font", FONT_DEFAULT)
        css = CSS.format(font=size)
        self.css.load_from_data(css, len(css.encode()))

    def change_font(self, delta):
        size = FONT_DEFAULT if delta == 0 else self.settings.get("font", FONT_DEFAULT) + delta
        self.settings["font"] = max(FONT_MIN, min(FONT_MAX, size))
        save_settings(self.settings)
        self.apply_font()
        self.toasts.add_toast(Adw.Toast(title=f"Yozuv o'lchami: {self.settings['font']}pt", timeout=1))

    # ---------------------------------------------------------------- skan
    def scan(self):
        if not self.refresh_btn.get_sensitive():
            return
        self.refresh_btn.set_sensitive(False)
        self.loading.set_title("Skanerlanmoqda…")
        self.loading.set_description("Bu 1-2 daqiqa olishi mumkin")
        self.root.set_visible_child_name("loading")
        self.selected.clear()

        def work():
            try:
                data = cleaner.full_scan()
            except Exception as e:  # noqa: BLE001
                data = {"items": [], "errors": [repr(e)], "disk": {"total": 0, "avail": 0}}
            GLib.idle_add(self.on_scanned, data)

        threading.Thread(target=work, daemon=True).start()

    def on_scanned(self, data):
        self.items, self.disk = data["items"], data["disk"]
        self.refresh_btn.set_sensitive(True)
        for e in data.get("errors") or []:
            self.toasts.add_toast(Adw.Toast(title=f"Skaner xatosi: {e[:80]}", timeout=6))
        self.render_overview()
        self.render_details()
        self.root.set_visible_child_name("main")
        return False

    # ---------------------------------------------------------------- "Umumiy" varaq
    def quick_items(self):
        """Bir tugmada o'chiriladiganlar: xavfsiz, yaqinda ishlatilmagan, dasturi ochiq emas."""
        return [i for i in self.items
                if i["safety"] == cleaner.SAFE and not i["recent"] and not i.get("warn")
                and (self.include_root or not is_root(i))]

    def render_overview(self):
        total, avail = self.disk["total"], self.disk["avail"]
        quick = self.quick_items()
        quick_size = sum(i["size"] for i in quick)
        quick_ids = {i["id"] for i in quick}
        review = [i for i in self.items if i["id"] not in quick_ids and not i["recent"]]
        skipped_open = [i for i in self.items if i["safety"] == cleaner.SAFE and not i["recent"] and i.get("warn")]

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=32,
                      margin_start=16, margin_end=16)

        # disk kartasi
        disk = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["card", "card-pad"])
        row = Gtk.Box(spacing=12)
        row.append(Gtk.Image(icon_name="drive-harddisk-symbolic", pixel_size=40))
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        txt.append(Gtk.Label(label=f"{fmt(avail)} bo'sh", xalign=0, css_classes=["disk-free"]))
        txt.append(Gtk.Label(label=f"{fmt(total)} dan {fmt(total - avail)} ishlatilgan", xalign=0,
                             css_classes=["dim-label"]))
        row.append(txt)
        disk.append(row)
        used = (total - avail) / total if total else 0
        lvl = Gtk.LevelBar(min_value=0, max_value=1, value=used, css_classes=["disk-bar"])
        for o in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            lvl.remove_offset_value(o)
        disk.append(lvl)
        if quick_size:
            disk.append(Gtk.Label(label=f"Xavfsiz tozalashdan keyin: ~{fmt(avail + quick_size)} bo'sh bo'ladi",
                                  xalign=0, css_classes=["dim-label", "hint"]))
        box.append(disk)

        # xavfsiz tozalash kartasi
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, css_classes=["card", "card-pad"])
        head = Gtk.Box(spacing=14)
        head.append(Gtk.Image(icon_name="emblem-ok-symbolic", pixel_size=40, css_classes=["success"]))
        ht = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        ht.append(Gtk.Label(label="Xavfsiz tozalash", xalign=0, css_classes=["card-title"]))
        ht.append(Gtk.Label(label="Keshlar, eski Docker qoldiqlari, eski loyihalarning paket papkalari va "
                                  "keraksiz fayllar. Hammasi kerak bo'lsa avtomatik qayta tiklanadi — shaxsiy "
                                  "fayllaringiz va yaqinda ishlatilgan narsalarga tegilmaydi.",
                            xalign=0, wrap=True, css_classes=["dim-label"]))
        head.append(ht)
        card.append(head)
        card.append(Gtk.Label(label=fmt(quick_size), xalign=0, css_classes=["hero-size", "success"]))

        if quick:
            by_group = defaultdict(list)
            for i in quick:
                by_group[i["group"]].append(i)
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
            for g, lst in sorted(by_group.items(), key=lambda x: -sum(i["size"] for i in x[1])):
                r = Adw.ActionRow(use_markup=False, activatable=True,
                                  tooltip_text="Batafsil ro'yxatda ko'rish")
                r.set_title(g)
                r.set_subtitle(f"{len(lst)} ta element")
                r.add_prefix(Gtk.Image(icon_name=group_icon(g)))
                r.add_suffix(Gtk.Label(label=fmt(sum(i["size"] for i in lst)), css_classes=["size-label"]))
                r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                r.connect("activated", lambda _r, name=g: self.show_group(name))
                lb.append(r)
            card.append(lb)

        root_items = [i for i in self.items if is_root(i) and i["safety"] == cleaner.SAFE and not i["recent"]]
        if root_items:  # tizim musori bo'lsa, uni qo'shish/qo'shmaslikni tanlash
            sw = Adw.SwitchRow(use_markup=False, active=self.include_root)
            sw.set_title(f"Tizim keshlarini ham tozalash (+{fmt(sum(i['size'] for i in root_items))})"
                         if not self.include_root else "Tizim keshlarini ham tozalash")
            sw.set_subtitle("Eski snap versiyalari, APT keshi, jurnallar — parol so'raladi")
            sw.connect("notify::active", self.on_root_toggled)
            opt = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
            opt.append(sw)
            card.append(opt)

        if quick:
            btn = Gtk.Button(label=f"🧹  Xavfsiz tozalash — {fmt(quick_size)}", halign=Gtk.Align.CENTER,
                             css_classes=["suggested-action", "pill", "big-button"], margin_top=6)
            btn.connect("clicked", lambda *_: self.confirm(quick, quick_mode=True))
            card.append(btn)
        else:
            card.append(Gtk.Label(label="🎉 Xavfsiz o'chiriladigan musor qolmadi!", xalign=0))

        if skipped_open:
            names = sorted({i["warn"].split(" hozir")[0] for i in skipped_open})
            card.append(Gtk.Label(
                label=f"ℹ {fmt(sum(i['size'] for i in skipped_open))} o'tkazib yuborildi, chunki "
                      f"{', '.join(names)} hozir ochiq. Yopib, qayta skanerlang.",
                xalign=0, wrap=True, css_classes=["dim-label", "hint"]))
        box.append(card)

        # ko'rib chiqish kerak bo'lganlar
        rv = Gtk.Box(spacing=14, css_classes=["card", "card-pad"])
        rv.append(Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=40, css_classes=["warning"]))
        rt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER, spacing=2)
        rt.append(Gtk.Label(label=f"O'zingiz ko'rib chiqing — {fmt(sum(i['size'] for i in review))}",
                            xalign=0, css_classes=["card-title"]))
        rt.append(Gtk.Label(label="Docker image va volume'lar, katta fayllar, dublikatlar, installerlar. "
                                  "Bular avtomatik o'chirilmaydi — kerakligini o'zingiz hal qilasiz.",
                            xalign=0, wrap=True, css_classes=["dim-label"]))
        rv.append(rt)
        go = Gtk.Button(label="Ro'yxatni ochish", valign=Gtk.Align.CENTER, css_classes=["pill"])
        go.connect("clicked", lambda *_: self.tabs.set_visible_child_name("details"))
        rv.append(go)
        box.append(rv)

        n_recent = sum(i["recent"] for i in self.items)
        if n_recent:
            box.append(Gtk.Label(
                label=f"🛡 Oxirgi {cleaner.RECENT_DAYS} kunda ishlatilgan {n_recent} ta element himoyalangan "
                      f"va hech qayerda hisobga olinmagan.", wrap=True, css_classes=["dim-label", "hint"]))

        self.overview_scroll.set_child(Adw.Clamp(child=box, maximum_size=760))

    def on_root_toggled(self, sw, _):
        self.include_root = sw.get_active()
        self.settings["include_root"] = self.include_root
        save_settings(self.settings)
        GLib.idle_add(self.render_overview)

    def show_group(self, name):
        self.focus_group = name
        self.render_details()
        self.tabs.set_visible_child_name("details")

    # ---------------------------------------------------------------- "Batafsil" varaq
    def build_details(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search_bar = Gtk.SearchBar()
        entry = Gtk.SearchEntry(placeholder_text="Nomi yoki yo'li bo'yicha qidirish…", hexpand=True)
        entry.connect("search-changed", self.on_search)
        self.search_entry = entry
        self.search_bar.set_child(Adw.Clamp(child=entry, maximum_size=760))
        self.search_bar.connect_entry(entry)
        self.search_btn.bind_property("active", self.search_bar, "search-mode-enabled",
                                      GObject.BindingFlags.BIDIRECTIONAL)
        box.append(self.search_bar)

        self.details_scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        box.append(self.details_scroll)

        bar = Gtk.Box(spacing=12, css_classes=["bottom-bar"])
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        self.sel_size = Gtk.Label(label="0 B", xalign=0, css_classes=["title-2"])
        self.sel_count = Gtk.Label(label="tanlanmagan", xalign=0, css_classes=["dim-label"])
        info.append(self.sel_size)
        info.append(self.sel_count)
        bar.append(info)
        self.del_btn = Gtk.Button(label="Tanlanganlarni o'chirish", sensitive=False, valign=Gtk.Align.CENTER,
                                  css_classes=["destructive-action", "pill", "big-button"])
        self.del_btn.connect("clicked", lambda *_: self.confirm(self.sel_items()))
        bar.append(self.del_btn)
        box.append(bar)
        return box

    def open_search(self):
        self.tabs.set_visible_child_name("details")
        self.search_btn.set_active(True)
        self.search_entry.grab_focus()

    def on_tab_changed(self, *_):
        if self.tabs.get_visible_child_name() != "details":
            self.search_btn.set_active(False)
        self.search_btn.set_sensitive(self.tabs.get_visible_child_name() == "details")

    def visible(self, i):
        if i["recent"] and not self.show_recent:
            return False
        if self.query:
            return self.query in f"{i['title']} {i.get('path') or ''} {i['group']}".lower()
        return True

    def render_details(self):
        self.checks = {}
        page = Adw.PreferencesPage()

        top = Adw.PreferencesGroup(description="Har bir elementni alohida tanlang. Bo'lim yonidagi belgi "
                                               "bo'limdagi hammasini tanlaydi.")
        n_recent = sum(i["recent"] for i in self.items)
        sw = Adw.SwitchRow(use_markup=False, active=self.show_recent)
        sw.set_title("Yaqinda ishlatilganlarni ham ko'rsatish")
        sw.set_subtitle(f"Oxirgi {cleaner.RECENT_DAYS} kunda ishlatilgan {n_recent} ta element")
        sw.connect("notify::active", self.on_recent_toggled)
        top.add(sw)
        page.add(top)

        groups = defaultdict(list)
        for i in self.items:
            if self.visible(i):
                groups[i["group"]].append(i)
        content = Adw.PreferencesGroup()
        focus_row = None
        for name, lst in sorted(groups.items(), key=lambda g: -sum(i["size"] for i in g[1])):
            lst.sort(key=lambda i: -i["size"])
            exp = self.group_row(name, lst)
            if name == self.focus_group:
                exp.set_expanded(True)
                focus_row = exp
            content.add(exp)
        if not groups:
            content.add(Adw.ActionRow(title="Hech narsa topilmadi"))
        page.add(content)
        self.details_scroll.set_child(page)
        if focus_row:
            GLib.timeout_add(150, lambda: (page.scroll_to_top(), focus_row.grab_focus(), False)[-1])
        self.focus_group = None
        self.update_selection()

    def group_row(self, name, lst):
        exp = Adw.ExpanderRow(use_markup=False, expanded=bool(self.query))
        exp.set_title(name)
        safe_n = sum(i["safety"] == cleaner.SAFE for i in lst)
        exp.set_subtitle(f"{len(lst)} ta element" + (f" · {safe_n} tasi xavfsiz" if safe_n else ""))
        exp.add_prefix(Gtk.Image(icon_name=group_icon(name), pixel_size=24))
        exp.add_suffix(Gtk.Label(label=fmt(sum(i["size"] for i in lst)), css_classes=["size-label"]))
        gcheck = Gtk.CheckButton(valign=Gtk.Align.CENTER, tooltip_text="Hammasini tanlash",
                                 active=all(i["id"] in self.selected for i in lst))
        gcheck.connect("toggled", self.on_group_toggled, lst)
        exp.add_suffix(gcheck)
        for i in lst:
            exp.add_row(self.item_row(i))
        return exp

    def item_row(self, i):
        parts = [i["desc"]]
        if i.get("used") is not None:
            parts.append(f"oxirgi ishlatilgan: {ago(i['used'])}")
        elif i.get("age") is not None:
            parts.append(f"o'zgargan: {ago(i['age'])}")
        sub = " · ".join(parts)
        if i.get("path"):
            sub += f"\n{i['path']}"
        if i.get("warn"):
            sub += f"\n⚠ {i['warn']}"
        row = Adw.ActionRow(use_markup=False, subtitle_lines=4, title_lines=2)  # avval markup o'chadi
        row.set_title(i["title"])
        row.set_subtitle(sub)
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=i["id"] in self.selected)
        check.connect("toggled", self.on_item_toggled, i["id"])
        row.add_prefix(check)
        row.set_activatable_widget(check)
        self.checks[i["id"]] = check

        text, cls = LABEL[i["safety"]]
        if i["recent"]:
            row.add_suffix(Gtk.Label(label="yaqinda", css_classes=["badge", "accent"], valign=Gtk.Align.CENTER))
        row.add_suffix(Gtk.Label(label=text, css_classes=["badge", cls], valign=Gtk.Align.CENTER))
        row.add_suffix(Gtk.Label(label=fmt(i["size"]), css_classes=["size-label"], width_chars=9, xalign=1))
        if i.get("paths"):
            btn = Gtk.MenuButton(icon_name="view-list-symbolic", valign=Gtk.Align.CENTER,
                                 css_classes=["flat"], tooltip_text="Fayllar ro'yxati")
            lbl = Gtk.Label(label="\n".join(i["paths"]), selectable=True, xalign=0, css_classes=["monospace"])
            btn.set_popover(Gtk.Popover(child=Gtk.ScrolledWindow(child=lbl, min_content_width=520,
                                                                 min_content_height=260)))
            row.add_suffix(btn)
        return row

    # ---------------------------------------------------------------- tanlash
    def set_selected(self, iid, on):
        (self.selected.add if on else self.selected.discard)(iid)
        c = self.checks.get(iid)
        if c and c.get_active() != on:
            c.set_active(on)

    def on_item_toggled(self, check, iid):
        self.set_selected(iid, check.get_active())
        self.update_selection()

    def on_group_toggled(self, gcheck, lst):
        on = gcheck.get_active()
        for i in lst:
            if not (on and i["recent"]):  # yaqinda ishlatilganlarni ommaviy tanlamaymiz
                self.set_selected(i["id"], on)
        self.update_selection()

    def on_recent_toggled(self, sw, _):
        self.show_recent = sw.get_active()
        if not self.show_recent:
            self.selected -= {i["id"] for i in self.items if i["recent"]}
        GLib.idle_add(self.render_details)

    def on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        self.render_details()

    def pick_safe(self):
        self.tabs.set_visible_child_name("details")
        for i in self.items:
            self.set_selected(i["id"], i["safety"] == cleaner.SAFE and not i["recent"] and self.visible(i))
        self.update_selection()

    def pick_none(self):
        for iid in list(self.selected):
            self.set_selected(iid, False)
        self.update_selection()

    def sel_items(self):
        return [i for i in self.items if i["id"] in self.selected]

    def update_selection(self):
        lst = self.sel_items()
        self.sel_size.set_label(fmt(sum(i["size"] for i in lst)))
        self.sel_count.set_label(f"{len(lst)} ta tanlandi" if lst else "hech narsa tanlanmagan")
        self.del_btn.set_sensitive(bool(lst))

    # ---------------------------------------------------------------- o'chirish
    def confirm(self, lst, quick_mode=False):
        total = sum(i["size"] for i in lst)
        notes = []
        careful = sum(i["safety"] == cleaner.CAREFUL for i in lst)
        recent = sum(i["recent"] for i in lst)
        if careful:
            notes.append(f"⚠ {careful} ta \"ehtiyot bo'ling\" belgili element bor!")
        if recent:
            notes.append(f"⚠ {recent} tasi oxirgi {cleaner.RECENT_DAYS} kunda ishlatilgan!")
        if any(is_root(i) for i in lst):
            notes.append("🔑 Tizim elementlari uchun parol so'raladi.")
        if quick_mode:
            notes.append("Faqat xavfsiz elementlar — kerak bo'lsa qayta tiklanadi.")
        else:
            notes.append("Bu amalni ortga qaytarib bo'lmaydi (savatchaga tushmaydi).")

        dlg = Adw.AlertDialog(heading=f"{fmt(total)} tozalansinmi?" if quick_mode
                              else f"{len(lst)} ta element o'chirilsinmi?",
                              body=f"{len(lst)} ta element, jami {fmt(total)}.\n\n" + "\n".join(notes))
        exp = Gtk.Expander(label="Ro'yxatni ko'rish", expanded=not quick_mode)
        exp.set_child(scrolled_label("\n".join(f"• {i['title']} — {fmt(i['size'])}" for i in lst),
                                     min(260, 24 * len(lst) + 10)))
        dlg.set_extra_child(exp)
        dlg.add_response("cancel", "Bekor qilish")
        dlg.add_response("go", "Tozalash" if quick_mode else "O'chirish")
        dlg.set_response_appearance("go", Adw.ResponseAppearance.SUGGESTED if quick_mode
                                    else Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, r: r == "go" and self.do_clean(lst))
        dlg.present(self)

    def do_clean(self, lst):
        self.refresh_btn.set_sensitive(False)
        self.loading.set_title("Tozalanmoqda…")
        self.loading.set_description(f"{len(lst)} ta element · Docker va snap uchun biroz vaqt ketishi mumkin")
        self.root.set_visible_child_name("loading")
        before = self.disk["avail"]
        by_id = {i["id"]: i for i in lst}

        def work():
            results = cleaner.clean([i["id"] for i in lst])
            GLib.idle_add(self.on_cleaned, results, by_id, before)

        threading.Thread(target=work, daemon=True).start()

    def on_cleaned(self, results, by_id, before):
        ok = [r for r in results if r["ok"]]
        fail = [r for r in results if not r["ok"]]
        rc, out, _ = cleaner.run(["df", "-B1", "--output=avail", str(cleaner.HOME)])
        after = int(out.split()[-1]) if rc == 0 else before
        freed = max(0, after - before)

        body = f"{len(ok)} / {len(results)} ta element tozalandi.\nHozir bo'sh joy: {fmt(after)}"
        dlg = Adw.AlertDialog(heading=f"🎉 {fmt(freed)} bo'shatildi" if freed else "Tayyor", body=body)
        if fail:
            dlg.set_extra_child(scrolled_label(
                "Bajarilmaganlar:\n" + "\n".join(
                    f"✗ {by_id.get(r['id'], {}).get('title', r['id'])} — {r['msg']}" for r in fail),
                min(220, 24 * len(fail) + 30)))
        dlg.add_response("ok", "Zo'r")
        dlg.present(self)
        self.refresh_btn.set_sensitive(True)
        self.scan()
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
