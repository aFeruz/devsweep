"""DevSweep tarjimalari: en / ru / uz.

Til tartibi: DEVSWEEP_LANG muhit o'zgaruvchisi → saqlangan sozlama → tizim tili (LANG) → en.
Ruscha ko'plik shakllari muammosidan qochish uchun sonlar "{n} шт." / "{n} дн." ko'rinishida yoziladi.
"""
import json
import os
from pathlib import Path

LANGS = {"en": "English", "ru": "Русский", "uz": "O'zbekcha"}
SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "devsweep" / "settings.json"

T = {
    # ------------------------------------------------------------ guruhlar
    "group.docker": ("Docker", "Docker", "Docker"),
    "group.cache": ("Caches (~/.cache)", "Кэш (~/.cache)", "Kesh (~/.cache)"),
    "group.devcache": ("Developer caches", "Кэши разработки", "Dasturlash keshlari"),
    "group.appcache": ("App caches", "Кэши приложений", "Dasturlar keshi"),
    "group.projects": ("Project build & dependency folders", "Папки сборки и зависимостей проектов",
                       "Loyihalardagi build/paket papkalari"),
    "group.dupes": ("Duplicate files", "Дубликаты файлов", "Dublikat fayllar"),
    "group.installers": ("Installers (.deb, .apk, .iso…)", "Установочные файлы (.deb, .apk, .iso…)",
                         "O'rnatish fayllari (.deb, .apk, .iso…)"),
    "group.big": ("Large files ({mb} MB+)", "Большие файлы ({mb} МБ+)", "Katta fayllar ({mb} MB+)"),
    "group.junk": ("Junk files", "Мусорные файлы", "Keraksiz fayllar"),
    "group.system": ("System (password required)", "Система (нужен пароль)", "Tizim (parol so'raladi)"),

    # ------------------------------------------------------------ docker
    "docker.container.title": ("Stopped container: {name}", "Остановленный контейнер: {name}",
                               "To'xtatilgan konteyner: {name}"),
    "docker.container.desc": (
        "{image} · {status}. Volume data is kept, but the container will have to be recreated.",
        "{image} · {status}. Данные в volume сохранятся, но контейнер придётся создать заново.",
        "{image} · {status}. Volume'dagi ma'lumotlar o'chmaydi, lekin konteynerni qayta yaratish kerak bo'ladi."),
    "docker.dangling.title": ("Dangling <none> images ({n}, {days}+ days old)",
                              "Безымянные <none> образы ({n} шт., старше {days} дн.)",
                              "Nomsiz (dangling) image'lar ({n} ta, {days}+ kunlik)"),
    "docker.dangling.desc": (
        "Leftovers from old builds. Images from the last {days} days are kept ({kept}).",
        "Остатки старых сборок. Образы за последние {days} дн. не трогаются ({kept} шт.).",
        "Eski build'lardan qolgan <none> image'lar. Oxirgi {days} kundagilari tegilmaydi ({kept} ta)."),
    "docker.image.title": ("Image: {ref}", "Образ: {ref}", "Image: {ref}"),
    "docker.image.desc": (
        "Not used by any container · full size {size} (unique part shown; shared layers may be freed too)",
        "Не используется контейнерами · полный размер {size} (показана уникальная часть; общие слои тоже "
        "могут освободиться)",
        "Hech bir konteyner ishlatmayapti · to'liq hajmi {size} (o'ziga xos qismi ko'rsatilgan, umumiy "
        "qatlamlar ham bo'shashi mumkin)"),
    "docker.cache.title": ("Build cache ({n} entries, unused for {days}+ days)",
                           "Кэш сборки ({n} записей, не использовался {days}+ дн.)",
                           "Build cache ({n} ta yozuv, {days}+ kun ishlatilmagan)"),
    "docker.cache.desc": (
        "Old docker build cache. Entries used in the last {days} days ({kept}) are kept.",
        "Старый кэш docker build. Записи за последние {days} дн. ({kept} шт.) сохраняются.",
        "Eski docker build keshi. Oxirgi {days} kunda ishlatilganlari ({kept} ta) saqlanadi."),
    "docker.tinyvol.title": ("Empty/small unused volumes ({n})", "Пустые/мелкие неиспользуемые volume ({n} шт.)",
                             "Bo'sh/kichik ishlatilmagan volume'lar ({n} ta)"),
    "docker.tinyvol.desc": (
        "Under 1 MB, not attached to any container, {days}+ days old.",
        "Меньше 1 МБ, не подключены к контейнерам, старше {days} дн.",
        "Hajmi 1 MB dan kichik, hech bir konteynerga ulanmagan, {days}+ kunlik."),
    "docker.vol.title": ("Volume: {name}", "Volume: {name}", "Volume: {name}"),
    "docker.vol.anon": ("Anonymous volume, not attached to any container.",
                        "Анонимный volume, не подключён к контейнерам.",
                        "Anonim volume, hech bir konteynerga ulanmagan."),
    "docker.vol.named": (
        "Named volume — it may contain a database! Delete only if you are sure.",
        "Именованный volume — может содержать базу данных! Удаляйте, только если уверены.",
        "Nomli volume — ichida ma'lumotlar bazasi bo'lishi mumkin! Ishonchingiz komil bo'lsa o'chiring."),

    # ------------------------------------------------------------ keshlar
    "cache.generic": ("App cache — normally regenerated", "Кэш приложения — обычно создаётся заново",
                      "Dastur keshi — odatda qayta yaratiladi"),
    "cache.google-chrome": ("Chrome browser cache (best with Chrome closed)",
                            "Кэш браузера Chrome (лучше при закрытом Chrome)",
                            "Chrome brauzer keshi (Chrome yopiq bo'lsa yaxshi)"),
    "cache.yarn": ("Yarn package cache — re-downloaded when needed",
                   "Кэш пакетов Yarn — скачается заново при необходимости",
                   "Yarn paketlar keshi — kerak bo'lsa qayta yuklanadi"),
    "cache.ms-playwright": ("Playwright browsers — re-downloaded for tests",
                            "Браузеры Playwright — скачаются заново для тестов",
                            "Playwright brauzerlari — testlar uchun qayta yuklanadi"),
    "cache.ms-playwright-go": ("Playwright-go browsers", "Браузеры Playwright-go", "Playwright-go brauzerlari"),
    "cache.pip": ("pip cache", "Кэш pip", "pip keshi"),
    "cache.typescript": ("TypeScript typings cache", "Кэш типов TypeScript", "TypeScript tiplari keshi"),
    "cache.tracker3": ("GNOME file index — rebuilt automatically", "Индекс файлов GNOME — пересоздаётся сам",
                       "GNOME fayl indeksi — o'zi qayta tuziladi"),
    "cache.mesa_shader_cache": ("GPU shader cache", "Кэш шейдеров GPU", "GPU shader keshi"),
    "cache.prisma": ("Prisma engine cache", "Кэш движков Prisma", "Prisma engine keshi"),
    "cache.node-gyp": ("node-gyp headers", "Заголовки node-gyp", "node-gyp header'lari"),
    "cache.JetBrains": ("JetBrains IDE caches/indexes", "Кэши и индексы JetBrains IDE",
                        "JetBrains IDE keshi/indekslari"),
    "cache.thumbnails": ("Image thumbnails", "Миниатюры изображений", "Rasm kichik nusxalari"),

    "dev.npm": ("npm cache", "Кэш npm", "npm keshi"),
    "dev.npm.desc": ("npm package cache — re-downloaded when needed",
                     "Кэш пакетов npm — скачается заново при необходимости",
                     "npm paketlar keshi — kerak bo'lsa qayta yuklanadi"),
    "dev.gradle": ("Gradle cache", "Кэш Gradle", "Gradle keshi"),
    "dev.gradle.desc": ("Gradle libraries — re-downloaded on the next build",
                        "Библиотеки Gradle — скачаются при следующей сборке",
                        "Gradle kutubxonalari — keyingi build'da qayta yuklanadi"),
    "dev.gradled": ("Gradle daemon logs", "Логи демона Gradle", "Gradle daemon loglari"),
    "dev.gradled.desc": ("Old daemon logs and state", "Старые логи и состояние демона",
                         "Eski daemon loglari va holati"),
    "dev.gradlew": ("Gradle wrapper versions", "Версии Gradle wrapper", "Gradle wrapper versiyalari"),
    "dev.gradlew.desc": ("Downloaded Gradle distributions", "Скачанные дистрибутивы Gradle",
                         "Yuklangan Gradle distributivlari"),
    "dev.m2": ("Maven repository", "Репозиторий Maven", "Maven repo"),
    "dev.m2.desc": ("Maven library cache", "Кэш библиотек Maven", "Maven kutubxonalari keshi"),
    "dev.cargo": ("Cargo registry", "Реестр Cargo", "Cargo registry"),
    "dev.cargo.desc": ("Rust crate cache", "Кэш Rust crate", "Rust crate keshi"),
    "dev.go": ("Go modules", "Модули Go", "Go modullari"),
    "dev.go.desc": ("Go module cache", "Кэш модулей Go", "Go modul keshi"),
    "dev.nvm": ("nvm cache", "Кэш nvm", "nvm keshi"),
    "dev.nvm.desc": ("Node download cache", "Кэш загрузок Node", "Node yuklamalari keshi"),
    "dev.pnpm": ("pnpm store", "Хранилище pnpm", "pnpm store"),
    "dev.pnpm.desc": ("pnpm package store", "Хранилище пакетов pnpm", "pnpm paketlar ombori"),
    "dev.bun": ("bun cache", "Кэш bun", "bun keshi"),
    "dev.bun.desc": ("bun package cache", "Кэш пакетов bun", "bun paketlar keshi"),

    "app.electron.desc": ("Electron / VS Code-style app cache", "Кэш приложения на Electron / VS Code",
                          "Electron/VS Code tipidagi dastur keshi"),
    "app.chrome_model": ("Chrome on-device AI model (Gemini Nano)", "AI-модель Chrome на устройстве (Gemini Nano)",
                         "Chrome on-device AI modeli (Gemini Nano)"),
    "app.chrome_model.desc": (
        "AI model downloaded by Chrome. It may be re-downloaded unless you disable "
        "'optimization-guide-on-device-model' in chrome://flags.",
        "AI-модель, скачанная Chrome. Может скачаться снова, если не отключить "
        "'optimization-guide-on-device-model' в chrome://flags.",
        "Chrome o'zi yuklagan AI model. chrome://flags da 'optimization-guide-on-device-model' ni "
        "o'chirmasangiz qayta yuklab olishi mumkin."),
    "app.chrome_site.desc": ("Website caches, regenerated", "Кэши сайтов, создаются заново",
                             "Sayt keshlari, qayta yaratiladi"),
    "app.cursor_snap": ("Cursor agent snapshots", "Снимки агента Cursor", "Cursor agent snapshot'lari"),
    "app.cursor_snap.desc": (
        "Old checkpoints of Cursor AI agent changes. 'Restore' will stop working in old chats.",
        "Старые чекпоинты изменений AI-агента Cursor. В старых чатах «Restore» перестанет работать.",
        "Cursor AI agent o'zgarishlarining eski nusxalari (checkpoint). Eski chatlarda 'restore' ishlamay qoladi."),
    "app.telegram": ("Telegram media cache", "Медиакэш Telegram", "Telegram media keshi"),
    "app.telegram.desc": ("Cache of viewed photos/videos. Messages stay, media is re-downloaded.",
                          "Кэш просмотренных фото/видео. Сообщения останутся, медиа скачается заново.",
                          "Ko'rilgan rasm/video keshi. Xabarlar o'chmaydi, media qayta yuklanadi."),
    "app.snap_cache": ("snap: {name} cache", "snap: кэш {name}", "snap: {name} keshi"),
    "app.snap_cache.desc": ("Snap app cache", "Кэш snap-приложения", "Snap dastur keshi"),
    "trash": ("Trash", "Корзина", "Savatcha (Trash)"),
    "trash.desc": ("Deleted files in the Trash", "Удалённые файлы в корзине", "O'chirilgan fayllar savatchasi"),
    "warn.running": ("{app} is running — close it before cleaning", "{app} запущен — закройте его перед очисткой",
                     "{app} hozir ishlayapti — o'chirishdan oldin yopib qo'ying"),

    # ------------------------------------------------------------ loyihalar
    "art.node_modules": ("npm/yarn packages — restored with `npm install`",
                         "Пакеты npm/yarn — восстанавливаются через `npm install`",
                         "npm/yarn paketlari — `npm install` bilan qayta tiklanadi"),
    "art..next": ("Next.js build cache — recreated by `next build`/`dev`",
                  "Кэш сборки Next.js — пересоздаётся `next build`/`dev`",
                  "Next.js build keshi — `next build`/`dev` qayta yaratadi"),
    "art..nuxt": ("Nuxt build cache", "Кэш сборки Nuxt", "Nuxt build keshi"),
    "art..turbo": ("Turborepo cache", "Кэш Turborepo", "Turborepo keshi"),
    "art..angular": ("Angular cache", "Кэш Angular", "Angular keshi"),
    "art..parcel-cache": ("Parcel cache", "Кэш Parcel", "Parcel keshi"),
    "art.venv": ("Python virtual environment — restored with `pip install -r requirements.txt`",
                 "Виртуальное окружение Python — восстанавливается `pip install -r requirements.txt`",
                 "Python virtual muhit — `pip install -r requirements.txt` bilan tiklanadi"),
    "art.target": ("Rust/Maven build output — rebuilt", "Результат сборки Rust/Maven — пересобирается",
                   "Rust/Maven build natijasi — qayta build qilinadi"),
    "art.build": ("Gradle build output — rebuilt", "Результат сборки Gradle — пересобирается",
                  "Gradle build natijasi — qayta build qilinadi"),
    "art.age_note": ("age based on project files", "возраст по файлам проекта", "vaqt loyiha fayllari bo'yicha"),

    # ------------------------------------------------------------ fayllar
    "junk.partial": ("Incomplete downloads ({n})", "Недокачанные файлы ({n} шт.)", "Chala yuklangan fayllar ({n} ta)"),
    "junk.partial.desc": ("Unfinished browser downloads — can't be opened, not needed",
                          "Незавершённые загрузки браузера — не открываются, не нужны",
                          "Brauzer yuklashi tugallanmagan — ochilmaydi, keraksiz"),
    "junk.logs": ("Log files ({n})", "Лог-файлы ({n} шт.)", "Log fayllar ({n} ta)"),
    "junk.logs.desc": ("App / npm / Java crash logs — usually not needed",
                       "Логи приложений, npm и падений Java — обычно не нужны",
                       "Dasturlar/npm/Java crash loglari — odatda keraksiz"),
    "junk.temp": ("Temporary & backup files ({n})", "Временные и резервные файлы ({n} шт.)",
                  "Vaqtinchalik va zaxira fayllar ({n} ta)"),
    "junk.temp.desc": ("Editor backups, .tmp, .swp, Thumbs.db, .DS_Store",
                       "Резервные копии редакторов, .tmp, .swp, Thumbs.db, .DS_Store",
                       "Muharrir zaxiralari, .tmp, .swp, Thumbs.db, .DS_Store"),
    "junk.core": ("Core dumps ({n})", "Дампы памяти core ({n} шт.)", "Core dump fayllar ({n} ta)"),
    "junk.core.desc": ("Memory dumps left by crashed programs", "Дампы памяти упавших программ",
                       "Dastur yiqilganda qolgan xotira nusxalari"),
    "dupe.desc": ("An identical copy is kept: {keep}", "Идентичная копия сохраняется: {keep}",
                  "Aynan bir xil nusxa saqlanadi: {keep}"),
    "warn.git": ("Inside git project {repo} — deleting may break it",
                 "Внутри git-проекта {repo} — удаление может его сломать",
                 "{repo} git loyihasi ichida — o'chirsangiz loyiha buzilishi mumkin"),
    "installer.desc": ("Usually not needed once installed", "Обычно не нужен после установки",
                       "O'rnatib bo'lingan bo'lsa odatda keraksiz"),
    "big.desc": ("Large file — check whether you still need it", "Большой файл — проверьте, нужен ли он",
                 "Katta fayl — kerakligini o'zingiz tekshiring"),

    # ------------------------------------------------------------ tizim
    "sys.snap": ("Old snap revision: {name} (rev {rev})", "Старая версия snap: {name} (rev {rev})",
                 "Eski snap versiyasi: {name} (rev {rev})"),
    "sys.snap.desc": ("Snap keeps the previous version after updates. The current version keeps working.",
                      "Snap хранит предыдущую версию после обновления. Текущая версия продолжит работать.",
                      "Snap yangilanganda eski versiyani saqlab qoladi. Hozirgi versiya ishlayveradi."),
    "sys.apt": ("APT package cache", "Кэш пакетов APT", "APT paketlar keshi"),
    "sys.apt.desc": ("Downloaded .deb files — installed packages are not affected",
                     "Скачанные .deb файлы — установленные пакеты не затрагиваются",
                     "Yuklab olingan .deb fayllar — o'rnatilganlarga ta'sir qilmaydi"),
    "sys.journal": ("System journal logs", "Системный журнал (journal)", "Tizim jurnallari (journal)"),
    "sys.journal.desc": ("Old logs, the latest 100 MB are kept", "Старые логи, последние 100 МБ сохраняются",
                         "Eski loglar, oxirgi 100 MB qoldiriladi"),

    # ------------------------------------------------------------ o'chirish natijalari
    "res.deleted": ("deleted", "удалено", "o'chirildi"),
    "res.gone": ("already gone", "уже нет", "allaqachon yo'q"),
    "res.files": ("{n} files deleted", "удалено файлов: {n}", "{n} ta fayl o'chirildi"),
    "res.done": ("done", "выполнено", "bajarildi"),
    "res.cancelled": ("cancelled", "отменено", "bekor qilindi"),
    "res.unknown": ("Unknown item — please rescan", "Неизвестный элемент — пересканируйте",
                    "Noma'lum element — qayta skanerlang"),
    "res.outside": ("Safety: {path} is outside your home folder", "Безопасность: {path} вне домашней папки",
                    "Xavfsizlik: {path} uy papkasidan tashqarida"),

    # ------------------------------------------------------------ umumiy UI
    "ui.loading": ("Scanning…", "Сканирование…", "Skanerlanmoqda…"),
    "ui.loading.desc": ("This can take 1–2 minutes", "Это может занять 1–2 минуты", "Bu 1-2 daqiqa olishi mumkin"),
    "ui.tab.overview": ("Overview", "Обзор", "Umumiy"),
    "ui.tab.details": ("Details", "Подробно", "Batafsil"),
    "ui.tip.refresh": ("Rescan (F5)", "Пересканировать (F5)", "Qayta skanerlash (F5)"),
    "ui.tip.search": ("Search (Ctrl+F)", "Поиск (Ctrl+F)", "Qidirish (Ctrl+F)"),
    "ui.tip.menu": ("Menu", "Меню", "Menyu"),
    "ui.menu.list": ("Details list", "Подробный список", "Batafsil ro'yxat"),
    "ui.menu.pick_safe": ("Select safe items", "Выбрать безопасные", "Xavfsizlarini tanlash"),
    "ui.menu.pick_none": ("Clear selection", "Снять выбор", "Tanlovni tozalash"),
    "ui.menu.font": ("Text size", "Размер текста", "Yozuv o'lchami"),
    "ui.menu.font_up": ("Larger text", "Крупнее", "Yozuvni kattalashtirish"),
    "ui.menu.font_down": ("Smaller text", "Мельче", "Yozuvni kichraytirish"),
    "ui.menu.font_reset": ("Default size", "Стандартный размер", "Standart o'lcham"),
    "ui.menu.lang": ("Language", "Язык", "Til"),
    "ui.toast.font": ("Text size: {n}pt", "Размер текста: {n}pt", "Yozuv o'lchami: {n}pt"),
    "ui.toast.error": ("Scanner error: {e}", "Ошибка сканера: {e}", "Skaner xatosi: {e}"),
    "ui.disk.free": ("{free} free", "Свободно {free}", "{free} bo'sh"),
    "ui.disk.used": ("{used} of {total} used", "Занято {used} из {total}", "{total} dan {used} ishlatilgan"),
    "ui.disk.after": ("After safe clean: ~{free} free", "После безопасной очистки: ~{free} свободно",
                      "Xavfsiz tozalashdan keyin: ~{free} bo'sh bo'ladi"),
    "ui.quick.title": ("Safe clean", "Безопасная очистка", "Xavfsiz tozalash"),
    "ui.quick.desc": (
        "Caches, old Docker leftovers, dependency folders of old projects and junk files. Everything is "
        "regenerated automatically when needed — your personal files and recently used items are never touched.",
        "Кэши, старые остатки Docker, папки зависимостей старых проектов и мусорные файлы. Всё восстановится "
        "автоматически при необходимости — личные файлы и недавно использованное не затрагиваются.",
        "Keshlar, eski Docker qoldiqlari, eski loyihalarning paket papkalari va keraksiz fayllar. Hammasi kerak "
        "bo'lsa avtomatik qayta tiklanadi — shaxsiy fayllaringiz va yaqinda ishlatilgan narsalarga tegilmaydi."),
    "ui.quick.btn": ("Safe clean — {size}", "Очистить — {size}", "Xavfsiz tozalash — {size}"),
    "ui.quick.none": ("No safe junk left!", "Безопасного мусора не осталось!",
                      "Xavfsiz o'chiriladigan musor qolmadi!"),
    "ui.quick.root": ("Also clean system caches", "Также очистить системные кэши", "Tizim keshlarini ham tozalash"),
    "ui.quick.root_plus": ("Also clean system caches (+{size})", "Также очистить системные кэши (+{size})",
                           "Tizim keshlarini ham tozalash (+{size})"),
    "ui.quick.root_sub": ("Old snap revisions, APT cache, journal logs — password required",
                          "Старые версии snap, кэш APT, журналы — нужен пароль",
                          "Eski snap versiyalari, APT keshi, jurnallar — parol so'raladi"),
    "ui.quick.skipped": ("{size} skipped because {apps} is open. Close it and rescan.",
                         "{size} пропущено, потому что открыто: {apps}. Закройте и пересканируйте.",
                         "{size} o'tkazib yuborildi, chunki {apps} hozir ochiq. Yopib, qayta skanerlang."),
    "ui.review.title": ("Review yourself — {size}", "Проверьте сами — {size}", "O'zingiz ko'rib chiqing — {size}"),
    "ui.review.desc": (
        "Docker images and volumes, large files, duplicates, installers. These are never deleted automatically "
        "— you decide.",
        "Образы и volume Docker, большие файлы, дубликаты, установщики. Они никогда не удаляются автоматически "
        "— решаете вы.",
        "Docker image va volume'lar, katta fayllar, dublikatlar, installerlar. Bular avtomatik o'chirilmaydi — "
        "kerakligini o'zingiz hal qilasiz."),
    "ui.review.btn": ("Open list", "Открыть список", "Ro'yxatni ochish"),
    "ui.protected": ("{n} items used in the last {days} days are protected and not counted anywhere.",
                     "{n} шт., использованных за последние {days} дн., защищены и нигде не учитываются.",
                     "Oxirgi {days} kunda ishlatilgan {n} ta element himoyalangan va hech qayerda hisobga "
                     "olinmagan."),
    "ui.items": ("{n} items", "{n} шт.", "{n} ta element"),
    "ui.items_safe": ("{n} items · {s} safe", "{n} шт. · безопасных: {s}", "{n} ta element · {s} tasi xavfsiz"),
    "ui.tip.show_details": ("Show in details", "Показать подробно", "Batafsil ro'yxatda ko'rish"),
    "ui.details.desc": ("Select items one by one. The checkbox next to a section selects all of it.",
                        "Выбирайте элементы по одному. Флажок рядом с разделом выбирает его целиком.",
                        "Har bir elementni alohida tanlang. Bo'lim yonidagi belgi bo'limdagi hammasini tanlaydi."),
    "ui.recent.show": ("Also show recently used", "Показывать недавно использованные",
                       "Yaqinda ishlatilganlarni ham ko'rsatish"),
    "ui.recent.sub": ("{n} items used in the last {days} days", "{n} шт. за последние {days} дн.",
                      "Oxirgi {days} kunda ishlatilgan {n} ta element"),
    "ui.nothing": ("Nothing found", "Ничего не найдено", "Hech narsa topilmadi"),
    "ui.search": ("Search by name or path…", "Поиск по имени или пути…", "Nomi yoki yo'li bo'yicha qidirish…"),
    "ui.tip.select_all": ("Select all", "Выбрать все", "Hammasini tanlash"),
    "ui.tip.files": ("File list", "Список файлов", "Fayllar ro'yxati"),
    "ui.sel.none": ("nothing selected", "ничего не выбрано", "hech narsa tanlanmagan"),
    "ui.sel.count": ("{n} selected", "выбрано: {n}", "{n} ta tanlandi"),
    "ui.delete_selected": ("Delete selected", "Удалить выбранное", "Tanlanganlarni o'chirish"),
    "ui.label.safe": ("safe", "безопасно", "xavfsiz"),
    "ui.label.review": ("review", "проверьте", "ko'rib chiqing"),
    "ui.label.careful": ("careful", "осторожно", "ehtiyot bo'ling"),
    "ui.label.recent": ("recent", "недавно", "yaqinda"),
    "ui.when.used": ("last used: {ago}", "использовалось: {ago}", "oxirgi ishlatilgan: {ago}"),
    "ui.when.modified": ("modified: {ago}", "изменено: {ago}", "o'zgargan: {ago}"),
    "ui.ago.today": ("today", "сегодня", "bugun"),
    "ui.ago.days": ("{n} days ago", "{n} дн. назад", "{n} kun avval"),
    "ui.confirm.careful": ("{n} items are marked “careful”!", "{n} шт. с пометкой «осторожно»!",
                           "{n} ta \"ehtiyot bo'ling\" belgili element bor!"),
    "ui.confirm.recent": ("{n} of them were used in the last {days} days!",
                          "{n} шт. использовались за последние {days} дн.!",
                          "{n} tasi oxirgi {days} kunda ishlatilgan!"),
    "ui.confirm.root": ("System items will ask for your password.", "Для системных элементов потребуется пароль.",
                        "Tizim elementlari uchun parol so'raladi."),
    "ui.confirm.quick_note": ("Safe items only — they are regenerated when needed.",
                              "Только безопасные элементы — при необходимости они восстановятся.",
                              "Faqat xavfsiz elementlar — kerak bo'lsa qayta tiklanadi."),
    "ui.confirm.permanent": ("This cannot be undone (nothing goes to the Trash).",
                             "Это нельзя отменить (в корзину ничего не попадает).",
                             "Bu amalni ortga qaytarib bo'lmaydi (savatchaga tushmaydi)."),
    "ui.confirm.quick_heading": ("Clean {size}?", "Очистить {size}?", "{size} tozalansinmi?"),
    "ui.confirm.heading": ("Delete {n} items?", "Удалить {n} шт.?", "{n} ta element o'chirilsinmi?"),
    "ui.confirm.body": ("{n} items, {size} in total.", "{n} шт., всего {size}.", "{n} ta element, jami {size}."),
    "ui.confirm.list": ("Show list", "Показать список", "Ro'yxatni ko'rish"),
    "ui.cancel": ("Cancel", "Отмена", "Bekor qilish"),
    "ui.clean": ("Clean", "Очистить", "Tozalash"),
    "ui.delete": ("Delete", "Удалить", "O'chirish"),
    "ui.cleaning": ("Cleaning…", "Очистка…", "Tozalanmoqda…"),
    "ui.cleaning.desc": ("{n} items · Docker and snap may take a while", "{n} шт. · Docker и snap могут занять время",
                         "{n} ta element · Docker va snap uchun biroz vaqt ketishi mumkin"),
    "ui.done.freed": ("{size} freed", "Освобождено {size}", "{size} bo'shatildi"),
    "ui.done": ("Done", "Готово", "Tayyor"),
    "ui.done.body": ("{ok} / {total} items cleaned.\nFree space now: {free}",
                     "Очищено {ok} из {total}.\nСейчас свободно: {free}",
                     "{ok} / {total} ta element tozalandi.\nHozir bo'sh joy: {free}"),
    "ui.done.failed": ("Not completed:", "Не выполнено:", "Bajarilmaganlar:"),
    "ui.ok": ("Great", "Отлично", "Zo'r"),

    # ------------------------------------------------------------ brauzer versiyasi
    "web.disk_loading": ("Loading disk info…", "Загрузка данных о диске…", "Disk ma'lumoti yuklanmoqda…"),
    "web.rescan": ("Rescan", "Пересканировать", "Qayta skanerlash"),
    "web.pick_safe": ("Select safe", "Выбрать безопасные", "Xavfsizlarini tanlash"),
    "web.recent_info": ("{n}, last {days} days", "{n} шт., {days} дн.", "{n} ta, oxirgi {days} kun"),
    "web.legend_safe": ("regenerated", "восстановится", "qayta tiklanadi"),
    "web.legend_careful": ("data may be lost", "возможна потеря данных", "ma'lumot yo'qolishi mumkin"),
    "web.disk": ("Disk: {used} used / {total} · free: {free} · found: {found} ({n} items, {took}s)",
                 "Диск: занято {used} / {total} · свободно: {free} · найдено: {found} ({n} шт., {took} с)",
                 "Disk: {used} ishlatilgan / {total} · bo'sh: {free} · topilgan: {found} ({n} ta, {took}s)"),
    "web.errors": ("Some scanners failed: {e}", "Некоторые сканеры завершились с ошибкой: {e}",
                   "Ba'zi skanerlar xato berdi: {e}"),
    "web.deleting": ("Deleting… (Docker/snap may take a while)", "Удаление… (Docker/snap могут занять время)",
                     "O'chirilmoqda… (Docker/snap uchun biroz vaqt ketadi)"),
    "web.done": ("Done: {ok}/{total} succeeded · ~{size} freed", "Готово: {ok}/{total} успешно · ~{size} освобождено",
                 "Tayyor: {ok}/{total} muvaffaqiyatli · ~{size} bo'shatildi"),
    "web.close_rescan": ("Close and rescan", "Закрыть и пересканировать", "Yopish va qayta skanerlash"),
    "web.yes_delete": ("Yes, delete", "Да, удалить", "Ha, o'chirish"),
    "web.started": ("DevSweep is running: {url}  (stop: Ctrl+C)", "DevSweep запущен: {url}  (остановить: Ctrl+C)",
                    "DevSweep ishga tushdi: {url}  (to'xtatish: Ctrl+C)"),
    "web.bye": ("Bye!", "Пока!", "Xayr!"),
}

_IDX = {"en": 0, "ru": 1, "uz": 2}

# Inglizcha birlik shakli (n == 1): "1 item", "1 day ago". Ruscha "шт./дн." va o'zbekcha uchun kerak emas.
EN_ONE = {
    "ui.items": "{n} item",
    "ui.items_safe": "{n} item · {s} safe",
    "ui.ago.days": "{n} day ago",
    "ui.confirm.heading": "Delete {n} item?",
    "ui.confirm.body": "{n} item, {size} in total.",
    "ui.confirm.careful": "{n} item is marked “careful”!",
    "ui.confirm.recent": "{n} of them was used in the last {days} days!",
    "ui.cleaning.desc": "{n} item · Docker and snap may take a while",
    "ui.protected": "{n} item used in the last {days} days is protected and not counted anywhere.",
    "ui.recent.sub": "{n} item used in the last {days} days",
    "res.files": "{n} file deleted",
}
_lang = "en"


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


def detect_lang():
    for cand in (os.environ.get("DEVSWEEP_LANG"), load_settings().get("lang"),
                 os.environ.get("LANGUAGE", "").split(":")[0], os.environ.get("LC_ALL"),
                 os.environ.get("LC_MESSAGES"), os.environ.get("LANG")):
        code = (cand or "")[:2].lower()
        if code in LANGS:
            return code
    return "en"


def set_lang(code):
    global _lang
    _lang = code if code in LANGS else "en"


def get_lang():
    return _lang


def _(key, lang=None, **kw):
    row = T.get(key)
    if row is None:
        return key
    lang = lang or _lang
    text = EN_ONE.get(key, row[0]) if lang == "en" and kw.get("n") == 1 else row[_IDX[lang]]
    return text.format(**kw) if kw else text


def table(prefix, lang=None):
    """Brauzer uchun: prefix bilan boshlanadigan kalitlar lug'ati (+ inglizcha birlik shakllari '.one')."""
    out = {k: _(k, lang) for k in T if k.startswith(prefix)}
    if (lang or _lang) == "en":
        out.update({f"{k}.one": v for k, v in EN_ONE.items() if k.startswith(prefix)})
    return out


set_lang(detect_lang())
