# Rust Plugin Sync

Консольный сервис для синхронизации Oxide plugins/configs из GitHub.

## Требования
- Windows VDS
- Git for Windows
- Python 3.10+ (Poetry)

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
Создай `C:\deploy\rust-sync.json`:

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
```bash
poetry run rust-sync --config C:\deploy\rust-sync.json
```

## Логи
`C:\deploy\logs\deploy.log` содержит:
- START
- No changes
- Deployed commit <hash>
- ERROR code=<code>
