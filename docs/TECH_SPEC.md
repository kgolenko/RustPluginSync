# ТЗ v1.0 (2026‑01‑27): авто‑синхронизация с GitHub на Windows VDS без входящих портов (вариант №2)

## 1) Цель
Автоматизировать доставку и применение файлов **Oxide plugins** и **Oxide config** на Rust‑сервере Windows VDS:

- Источник истины: GitHub репозиторий.
- Доставка: **консольный сервис (Python)** сам периодически проверяет изменения и применяет их.
- Безопасность: **не открывать входящие порты** на VDS.
- Надёжность: атомарное применение (по возможности), минимальное логирование, работа в одном процессе.

## 2) Исходные данные
- Путь к Rust серверу:
  `C:\Users\Administrator\Desktop\266Server`
- Целевые директории:
  - плагины: `C:\Users\Administrator\Desktop\266Server\oxide\plugins`
  - конфиги: `C:\Users\Administrator\Desktop\266Server\oxide\config`

## 3) Область поставки (что именно доставляем)
Доставляются **только**:

- `plugins/*.cs`
- `config/*.json`

Опционально (если нужно в будущем):

- `data/` (в Oxide есть `oxide/data`, но чаще это runtime и его не надо версионировать)

Не доставляются и не версионируются:

- логи
- сохранения мира / save‑файлы
- steamcmd / binaries
- любые секреты

## 4) Архитектура решения

### 4.1 Компоненты на сервере
1. Git (Git for Windows)
2. Python 3.x + Poetry
3. Рабочая директория деплоя:
   `C:\deploy\rust-plugins-config` — клон репозитория
4. Консольный сервис (Python-скрипт):
   `C:\deploy\rust-sync.py` (рабочее имя)

   - запускается вручную в терминале
   - с заданным интервалом выполняет синхронизацию
   - вся логика синхронизации находится внутри процесса

### 4.2 Без открытия портов
Сервер инициирует соединение **только исходящее** к GitHub (SSH/HTTPS).

## 5) Требования к репозиторию

### 5.1 Структура репо
```
rust-plugins-config/
  plugins/
    *.cs
  config/
    *.json
  README.md
  .gitignore
```

### 5.2 Ветки
- `main` — прод (то, что должно оказаться на сервере)
  Опционально:
- `staging` — тест (если появится тестовый сервер)

### 5.3 .gitignore (минимум)
- игнорировать локальные мусорные файлы, IDE, временное, логи.
- **Не класть** в репо токены/ключи/пароли.

## 6) Доступ GitHub → Server
Требование: сервер должен иметь доступ к репо **без интерактивного ввода пароля**.

Рекомендуемый способ: **SSH Deploy Key** (исходящее соединение, безопасно, без PAT).

### 6.1 SSH Deploy Key (требование)
- На сервере генерируется ключ `ed25519`
- Публичный ключ добавляется в GitHub репозиторий как Deploy key (Read‑only или Read/Write — зависит от модели)
- Клонирование на сервер: `git clone git@github.com:USER/REPO.git`

## 7) Поведение консольного сервиса

### 7.1 Параметры (конфигурируемость)
Сервис должен поддерживать как минимум параметры/переменные:

Путь к конфигу:
- `ConfigPath = "C:\deploy\rust-sync.json"`

Ключи в конфиге:
- `RepoPath = "C:\deploy\rust-plugins-config"`
- `ServerRoot = "C:\Users\Administrator\Desktop\266Server"`
- `PluginsTarget = "<ServerRoot>\\oxide\\plugins"`
- `ConfigTarget  = "<ServerRoot>\\oxide\\config"`
- `LogPath = "C:\deploy\logs\deploy.log"`
- `IntervalSeconds = 120` (по умолчанию)
- `Branch = "main"` (по умолчанию)
- `GitRetryCount = 3`
- `GitRetryDelaySeconds = 10`

Пример `C:\deploy\rust-sync.json`:
```json
{
  "RepoPath": "C:\\deploy\\rust-plugins-config",
  "ServerRoot": "C:\\Users\\Administrator\\Desktop\\266Server",
  "PluginsTarget": "C:\\Users\\Administrator\\Desktop\\266Server\\oxide\\plugins",
  "ConfigTarget": "C:\\Users\\Administrator\\Desktop\\266Server\\oxide\\config",
  "LogPath": "C:\\deploy\\logs\\deploy.log",
  "IntervalSeconds": 120,
  "Branch": "main",
  "GitRetryCount": 3,
  "GitRetryDelaySeconds": 10
}
```

### 7.2 Логика выполнения (алгоритм)
1. Проверка существования папок `RepoPath`, `PluginsTarget`, `ConfigTarget`. Если нет — лог и выход с кодом ≠ 0.
2. `git fetch` (без мержа). При ошибке — ретраи `GitRetryCount` раз с паузой `GitRetryDelaySeconds`.
3. Определение: есть ли новые коммиты относительно локального `HEAD`.

   - если нет изменений → лог “No changes” → выход с кодом 0.
5. Если изменения есть:

   - сохранить текущий commit hash как “previous”
   - `git reset --hard origin/<Branch>`
6. Валидации перед применением:

   - Проверка, что в `plugins/` только `.cs` (опционально строгая)
   - Проверка, что все файлы в `config/` — валидный JSON.
   - Если валидация не прошла → откат `git reset --hard <previous>` → выход с ошибкой.
7. Применение:

   - копировать `RepoPath\plugins\*.cs` → `PluginsTarget`
   - копировать `RepoPath\config\*.json` → `ConfigTarget`
   - копирование должно перезаписывать существующие файлы
8. Лог “Deployed commit <hash>”.

### 7.3 Псевдокод (MVP)
```text
load config from ConfigPath
log START

while true:
  if not paths exist (RepoPath, PluginsTarget, ConfigTarget):
    log ERROR code=1
    sleep IntervalSeconds
    continue

  retry GitRetryCount times:
    run git fetch
    if success: break
    else sleep GitRetryDelaySeconds
  if fetch failed after retries:
    log ERROR code=2
    sleep IntervalSeconds
    continue

  local = git rev-parse HEAD
  remote = git rev-parse origin/<Branch>
  if local == remote:
    log "No changes"
    sleep IntervalSeconds
    continue

  previous = local
  run git reset --hard origin/<Branch>

  validate plugins/*.cs (optional strict)
  validate config/*.json (parse JSON)
  if validation failed:
    run git reset --hard <previous>
    log ERROR code=3
    sleep IntervalSeconds
    continue

  copy RepoPath\\plugins\\*.cs -> PluginsTarget (overwrite)
  copy RepoPath\\config\\*.json -> ConfigTarget (overwrite)
  if copy failed:
    log ERROR code=4
    sleep IntervalSeconds
    continue

  log "Deployed commit <remote>"
  sleep IntervalSeconds
```

### 7.4 Выходные коды
- `0` — успешно (включая “нет изменений”)
- `1` — ошибка окружения (нет папок/прав)
- `2` — ошибка git
- `3` — ошибка валидации JSON
- `4` — ошибка копирования

## 8) Запуск сервиса

### 8.1 Режим запуска (MVP)
- Ручной запуск из терминала
- Процесс должен продолжать работу, пока окно не закрыто

### 8.2 Будущая автоматизация (опционально)
- Автозапуск без Task Scheduler (например, через NSSM/службу)

## 9) Нефункциональные требования

### 9.1 Безопасность
- Не открывать входящие порты
- SSH ключ хранится на сервере, публичная часть — в GitHub Deploy keys
- Логи не должны содержать секреты

### 9.2 Надёжность
- Валидация JSON до копирования
- При ошибке — не повреждать рабочие файлы (по возможности)

### 9.3 Наблюдаемость
- Минимальный лог‑файл `C:\deploy\logs\deploy.log`
  - Старт
  - No changes
  - Deployed commit <hash>
  - Ошибка с кодом

## 13) Best practices (Python + Poetry)
- Управление зависимостями через Poetry (`pyproject.toml`, `poetry.lock`)
- Запуск скрипта через `poetry run ...` или собранный entrypoint
- Минимум внешних зависимостей, использовать стандартную библиотеку

## 10) Границы (что НЕ делаем в рамках этого ТЗ)
- Авто‑рестарт Rust‑сервера / авто‑reload конкретных плагинов через RCON (можно добавить отдельным этапом)
- Управление несколькими серверами из одного репо
- UI/панель управления

## 11) Критерии приёмки
Считаем сделанным, если:

1. После `git push` в `main` в течение N минут на сервере появляются обновлённые:

   - `...\oxide\plugins\*.cs`
   - `...\oxide\config\*.json`
2. Если изменений нет — сервис не трогает файлы и пишет “No changes”.
3. При невалидном JSON в `config/` деплой **не применяется**, в лог пишется ошибка, рабочие файлы остаются прежними.
4. Процесс стабильно работает в консольном режиме и не завершает работу самопроизвольно.

## 12) План внедрения (шаги)
1. Создать GitHub репо, залить `plugins/` и `config/`.
2. На VDS:

   - установить Git for Windows
   - создать `C:\deploy\`
   - сгенерировать SSH ключ, добавить Deploy key в GitHub
   - `git clone` в `C:\deploy\rust-plugins-config`
3. Разместить `rust-sync.py` в `C:\deploy\`
4. Создать `C:\deploy\rust-sync.json` с параметрами `RepoPath`, `ServerRoot`, `IntervalSeconds`, `Branch` и путями логов
5. Запустить консольный сервис вручную
6. Тест: изменить плагин/конфиг в GitHub → дождаться синхронизации → проверить, что файлы обновились и есть запись в логе.
