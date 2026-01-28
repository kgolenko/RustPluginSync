# Rust Plugin Sync

Консольный сервис для синхронизации Oxide plugins/configs из GitHub.

## Требования
- Windows VDS
- Git for Windows
- Python 3.10+

## Подготовка перед стартом
1. Убедись, что установлен Git for Windows и `git` доступен в `PATH`.
2. Установи Python 3.10+ (или через `Install.ps1`, см. ниже).

## Один стартовый скрипт (bootstrap + запуск)
Запусти один скрипт — он сам выполнит bootstrap, если нет конфига:

```bat
Start.bat
```

Если всё уже настроено, он сразу запускает сервис.
Если нужно принудительно — запускай с флагом `-Bootstrap`.

## Установка Python и зависимостей (автоматически)
Из корня репозитория:
```powershell
.\Install.ps1 -InstallDeps
```
Скрипт поставит Python (через winget, если нет), обновит pip и установит зависимости проекта.

### Как добавить ключ в GitHub
1. Скопируй вывод публичного ключа из консоли (строка начинается с `ssh-ed25519`).
2. Открой нужный репозиторий в GitHub.
3. Перейди: **Settings → Deploy keys → Add deploy key**.
4. Вставь ключ в поле **Key**, задай название (например, `rust-sync`).
5. Оставь **Read-only** (рекомендуется) и нажми **Add key**.

Проверка SSH:
```powershell
ssh -T git@github.com
```

Клонирование репозитория:
```powershell
git clone git@github.com:USER/REPO.git C:\deploy\rust-plugins-config
```

## Конфиг
Если файла нет, при первом запуске bootstrap создаст `C:\deploy\rust-sync.json` и заполнит его на основе введённых путей.

Пример `C:\deploy\rust-sync.json`:

```json
{
  "LogPath": "C:\\deploy\\logs\\deploy.log",
  "IntervalSeconds": 120,
  "Branch": "main",
  "GitRetryCount": 3,
  "GitRetryDelaySeconds": 10,
  "GitTimeoutSeconds": 30,
  "StartupDelaySeconds": 1,
  "DryRun": false,
  "Servers": [
    {
      "Name": "main",
      "RepoPath": "C:\\deploy\\rust-plugins-config",
      "ServerRoot": "C:\\Users\\Administrator\\Desktop\\server",
      "PluginsTarget": "C:\\Users\\Administrator\\Desktop\\server\\oxide\\plugins",
      "ConfigTarget": "C:\\Users\\Administrator\\Desktop\\server\\oxide\\config",
      "Branch": "main",
      "PluginsPattern": ["*.cs"],
      "ConfigPattern": ["*.json"],
      "ExcludePatterns": [],
      "DeleteExtraneous": false,
      "Enabled": true
    }
  ]
}
```

Чтобы добавить ещё сервер, просто добавь новый объект в массив `Servers`.

### Новые опции
- `Branch` — можно задавать отдельно для каждого сервера, по умолчанию берётся глобальная `Branch`.
- `PluginsPattern` / `ConfigPattern` — include‑паттерны (список или строка, поддерживает `**`).
- `ExcludePatterns` — паттерны для исключения файлов.
- `DeleteExtraneous` — если `true`, удалит файлы в целевых папках, которых нет в репозитории.
- `Enabled` — быстро отключить сервер без удаления из конфигурации.
- `DryRun` (глобальный флаг) — если `true`, ничего не копируется и не удаляется, только логируются действия. CLI-флаг `--dry-run` имеет приоритет.

## Установка
Если не используешь `Install.ps1`, можно вручную:
```powershell
python -m pip install -e .
```

## Запуск
Запуск через единый скрипт:
```bat
Start.bat
```

Запуск с веб-интерфейсом:
```powershell
.\Start.ps1 -Web
```

URL по умолчанию: `http://<server-ip>:8787`

## Логи
`C:\deploy\logs\deploy.log` содержит:
- START
- No changes
- Deployed commit <hash>
- ERROR code=<code>

## Поведение синхронизации
- Проверяет хэши файлов даже если коммит не изменился — локальные ручные правки будут перезаписаны из репозитория.
- При `DeleteExtraneous=true` удаляет лишние файлы в `PluginsTarget` и `ConfigTarget`, которые не присутствуют в репозитории (с учётом include/exclude паттернов).
- `DryRun` выводит детальный список: create/update/delete для каждого файла, без фактических изменений.
