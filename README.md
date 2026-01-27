# Rust Plugin Sync

Консольный сервис для синхронизации Oxide plugins/configs из GitHub.

## Требования
- Windows VDS
- Git for Windows
- Python 3.10+ (Poetry)

## Установка Python и Poetry
1. Установи Python 3.10+ с официального сайта (важно включить опцию **Add Python to PATH**).
2. Проверь установку Python:
   ```powershell
   python --version
   ```
3. Установи Poetry через pipx (рекомендуется):
   ```powershell
   python -m pip install --user pipx
   python -m pipx ensurepath
   pipx install poetry
   ```
4. Проверь Poetry:
   ```powershell
   poetry --version
   ```

## Подготовка перед стартом
1. Убедись, что установлен Git for Windows и `git` доступен в `PATH`.
2. Установи Poetry (любой удобный способ) и проверь:
   ```bash
   poetry --version
   ```
3. Установи зависимости проекта:
   ```bash
   poetry install
   ```

## Быстрый старт (минимум ручной работы)
Запусти мастер‑скрипт на сервере:

```bat
scripts\\bootstrap.bat
```

Скрипт:
- создаст SSH ключ и пропишет его в `~\\.ssh\\config`
- покажет публичный ключ для GitHub Deploy Keys
- попросит путь к Rust серверу
- попросит SSH URL репозитория с плагинами и клонирует его
- создаст `C:\\deploy\\rust-sync.json`

## Настройка SSH (Deploy Key)
Запусти скрипт на сервере:

```bat
scripts\setup-ssh.bat
```

Он:
- создаст `C:\deploy\keys\rust-sync` (ed25519)
- добавит запись `github.com` в `%USERPROFILE%\.ssh\config`
- выведет публичный ключ в консоль (для добавления в Deploy Keys)

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
Если файла нет, при первом запуске сервис создаст `C:\deploy\rust-sync.json` и завершится. Отредактируй его и запусти снова.

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

## Установка
Из корня репозитория:

```bash
poetry install
```

## Запуск
Запуск через BAT-скрипт:
```bat
scripts\run-service.bat
```

Или вручную:
```bash
poetry run rust-sync --config C:\deploy\rust-sync.json
```

## Логи
`C:\deploy\logs\deploy.log` содержит:
- START
- No changes
- Deployed commit <hash>
- ERROR code=<code>
