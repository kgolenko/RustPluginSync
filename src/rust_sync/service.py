import argparse
import fnmatch
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_ENV = 1
EXIT_GIT = 2
EXIT_JSON = 3
EXIT_COPY = 4
EXIT_CONFIG = 5
GIT_TIMEOUT_SECONDS = 30
STARTUP_DELAY_SECONDS = 1

DEFAULT_CONFIG_PATH = r"C:\deploy\rust-sync.json"
DEFAULT_PLUGINS_REPO_DIR = r"C:\deploy\rust-plugins-config"
DEFAULT_KEY_DIR = r"C:\deploy\keys"
DEFAULT_KEY_NAME = "rust-sync"
DEFAULT_INSTALL_DIR = r"C:\deploy"
DEFAULT_SAMPLE_CONFIG = {
    "LogPath": r"C:\deploy\logs\deploy.log",
    "IntervalSeconds": 120,
    "Branch": "main",
    "GitRetryCount": 3,
    "GitRetryDelaySeconds": 10,
    "GitTimeoutSeconds": GIT_TIMEOUT_SECONDS,
    "StartupDelaySeconds": STARTUP_DELAY_SECONDS,
    "DryRun": False,
    "Servers": [
        {
            "Name": "main",
            "RepoPath": DEFAULT_PLUGINS_REPO_DIR,
            "ServerRoot": r"C:\Users\Administrator\Desktop\server",
            "PluginsTarget": r"C:\Users\Administrator\Desktop\server\oxide\plugins",
            "ConfigTarget": r"C:\Users\Administrator\Desktop\server\oxide\config",
            "Branch": "main",
            "PluginsPattern": ["*.cs"],
            "ConfigPattern": ["*.json"],
            "ExcludePatterns": [],
            "DeleteExtraneous": False,
            "Enabled": True,
        }
    ],
}


@dataclass
class ServerConfig:
    name: str
    repo_path: Path
    server_root: Path
    plugins_target: Path
    config_target: Path
    branch: str | None
    plugins_pattern: list[str]
    config_pattern: list[str]
    exclude_patterns: list[str]
    delete_extraneous: bool
    enabled: bool


@dataclass
class Settings:
    log_path: Path
    interval_seconds: int
    branch: str
    git_retry_count: int
    git_retry_delay_seconds: int
    git_timeout_seconds: int
    startup_delay_seconds: int
    dry_run: bool
    servers: list[ServerConfig]


@dataclass
class DeploymentRecord:
    server: str
    commit: str
    author: str
    files: list[str]
    duration_seconds: float
    timestamp: str
    status: str


@dataclass
class ServerStatus:
    name: str
    last_deploy_time: str | None = None
    last_commit: str | None = None
    last_error: str | None = None
    last_duration_seconds: float | None = None
    last_run_time: str | None = None
    last_status: str = "UNKNOWN"


class SyncState:
    def __init__(self, server_names: list[str]) -> None:
        self._lock = threading.Lock()
        self._servers: dict[str, ServerStatus] = {
            name: ServerStatus(name=name) for name in server_names
        }
        self._history: list[DeploymentRecord] = []
        self._max_history = 200

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "servers": [self._servers[name].__dict__ for name in self._servers],
                "history": [item.__dict__ for item in self._history],
            }

    def update_server_status(self, name: str, **kwargs: Any) -> None:
        with self._lock:
            server = self._servers.get(name)
            if not server:
                return
            for key, value in kwargs.items():
                if hasattr(server, key):
                    setattr(server, key, value)

    def add_history(self, record: DeploymentRecord) -> None:
        with self._lock:
            self._history.append(record)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]


class SyncController:
    def __init__(self) -> None:
        self._paused = False
        self._run_once = threading.Event()
        self._lock = threading.Lock()
        self._dry_run_override = False

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def request_run_once(self) -> None:
        self._run_once.set()

    def consume_run_once(self) -> bool:
        if self._run_once.is_set():
            self._run_once.clear()
            return True
        return False

    def set_dry_run(self, value: bool) -> None:
        with self._lock:
            self._dry_run_override = value

    def get_dry_run(self) -> bool:
        with self._lock:
            return self._dry_run_override


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _write_sample_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_SAMPLE_CONFIG, f, ensure_ascii=False, indent=2)


def _write_bootstrap_config(
    path: Path, server_root: Path, plugins_repo_dir: Path
) -> None:
    config = deepcopy(DEFAULT_SAMPLE_CONFIG)
    config["Servers"][0]["RepoPath"] = str(plugins_repo_dir)
    config["Servers"][0]["ServerRoot"] = str(server_root)
    config["Servers"][0]["PluginsTarget"] = str(server_root / "oxide" / "plugins")
    config["Servers"][0]["ConfigTarget"] = str(server_root / "oxide" / "config")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _settings_from_config(cfg: dict[str, Any]) -> Settings:
    def _require_positive(value: int, name: str) -> int:
        if value <= 0:
            raise ValueError(f"{name} must be > 0 (got {value})")
        return value

    def _parse_patterns(value: Any, default: list[str]) -> list[str]:
        if value is None:
            return default
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError(f"Patterns must be list or string (got {value})")
        if not value and default:
            raise ValueError("Patterns list cannot be empty")
        patterns = [str(v).strip() for v in value if str(v).strip()]
        if not patterns and value:
            raise ValueError("Patterns list cannot be empty")
        return patterns

    def _parse_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        raise ValueError(f"Bool expected (got {value})")

    def _req(key: str) -> Any:
        if key not in cfg:
            raise KeyError(f"Missing config key: {key}")
        return cfg[key]

    log_path = Path(_req("LogPath"))
    interval_seconds = _require_positive(
        int(cfg.get("IntervalSeconds", 120)), "IntervalSeconds"
    )
    branch = str(cfg.get("Branch", "main"))
    git_retry_count = _require_positive(
        int(cfg.get("GitRetryCount", 3)), "GitRetryCount"
    )
    git_retry_delay_seconds = int(cfg.get("GitRetryDelaySeconds", 10))
    git_timeout_seconds = _require_positive(
        int(cfg.get("GitTimeoutSeconds", GIT_TIMEOUT_SECONDS)), "GitTimeoutSeconds"
    )
    startup_delay_seconds = _require_positive(
        int(cfg.get("StartupDelaySeconds", STARTUP_DELAY_SECONDS)),
        "StartupDelaySeconds",
    )
    dry_run = _parse_bool(cfg.get("DryRun"), False)

    servers_cfg = _req("Servers")
    if not isinstance(servers_cfg, list) or not servers_cfg:
        raise ValueError("Servers must be a non-empty list")

    servers: list[ServerConfig] = []
    for item in servers_cfg:
        name = str(item.get("Name", "")).strip()
        if not name:
            raise KeyError("Server Name is required")
        repo_path = Path(item["RepoPath"])
        server_root = Path(item["ServerRoot"])
        plugins_target = Path(
            item.get("PluginsTarget", str(server_root / "oxide" / "plugins"))
        )
        config_target = Path(
            item.get("ConfigTarget", str(server_root / "oxide" / "config"))
        )
        branch_override = item.get("Branch")
        plugins_pattern = _parse_patterns(item.get("PluginsPattern"), ["*.cs"])
        config_pattern = _parse_patterns(item.get("ConfigPattern"), ["*.json"])
        exclude_patterns = _parse_patterns(item.get("ExcludePatterns", []), [])
        delete_extraneous = _parse_bool(item.get("DeleteExtraneous"), False)
        enabled = _parse_bool(item.get("Enabled"), True)

        servers.append(
            ServerConfig(
                name=name,
                repo_path=repo_path,
                server_root=server_root,
                plugins_target=plugins_target,
                config_target=config_target,
                branch=branch_override,
                plugins_pattern=plugins_pattern,
                config_pattern=config_pattern,
                exclude_patterns=exclude_patterns,
                delete_extraneous=delete_extraneous,
                enabled=enabled,
            )
        )

    return Settings(
        log_path=log_path,
        interval_seconds=interval_seconds,
        branch=branch,
        git_retry_count=git_retry_count,
        git_retry_delay_seconds=git_retry_delay_seconds,
        git_timeout_seconds=git_timeout_seconds,
        startup_delay_seconds=startup_delay_seconds,
        servers=servers,
        dry_run=dry_run,
    )


def validate_config_dict(cfg: dict[str, Any]) -> list[str]:
    try:
        _settings_from_config(cfg)
        return []
    except Exception as exc:
        return [str(exc)]


def _ensure_paths(server: ServerConfig) -> bool:
    return (
        server.repo_path.exists()
        and (server.repo_path / ".git").exists()
        and server.plugins_target.exists()
        and server.config_target.exists()
    )


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _collect_files(
    base: Path, includes: list[str], excludes: list[str]
) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for pattern in includes:
        for file in base.rglob(pattern):
            if not file.is_file():
                continue
            rel = file.relative_to(base).as_posix()
            if any(fnmatch.fnmatch(rel, ex) for ex in excludes):
                continue
            files[rel] = file
    return files


def _run_git(args: list[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout_seconds}s"


def _run_cmd(args: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _ensure_ssh_config_entry(config_path: Path, key_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    entry = "\n".join(
        [
            "Host github.com",
            "  HostName github.com",
            "  User git",
            f"  IdentityFile {key_path}",
            "  IdentitiesOnly yes",
            "",
        ]
    )
    config_path.write_text(entry, encoding="ascii")


def _ensure_ssh_key(key_dir: Path, key_name: str) -> tuple[Path, Path]:
    key_dir.mkdir(parents=True, exist_ok=True)
    private_key_path = key_dir / key_name
    public_key_path = Path(f"{private_key_path}.pub")

    if not private_key_path.exists():
        code, _, err = _run_cmd(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-C",
                "rust-sync",
                "-f",
                str(private_key_path),
                "-N",
                "",
                "-q",
            ]
        )
        if code != 0:
            raise RuntimeError(f"ssh-keygen failed: {err}")
    else:
        code, _, _ = _run_cmd(
            ["ssh-keygen", "-y", "-P", "", "-f", str(private_key_path)]
        )
        if code != 0:
            print(
                "Existing SSH key is passphrase-protected and will block "
                "non-interactive checks."
            )
            regen = input("Regenerate key without passphrase? (y/n): ").strip().lower()
            if regen == "y":
                try:
                    private_key_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    public_key_path.unlink(missing_ok=True)
                except Exception:
                    pass
                code, _, err = _run_cmd(
                    [
                        "ssh-keygen",
                        "-t",
                        "ed25519",
                        "-C",
                        "rust-sync",
                        "-f",
                        str(private_key_path),
                        "-N",
                        "",
                        "-q",
                    ]
                )
                if code != 0:
                    raise RuntimeError(f"ssh-keygen failed: {err}")

    return private_key_path, public_key_path


def _check_ssh_access(private_key_path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [
            "ssh",
            "-i",
            str(private_key_path),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-T",
            "git@github.com",
        ],
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    text = output.lower()
    ok = "successfully authenticated" in text or "hi " in text
    return ok, output.strip()


def _bootstrap_interactive(
    config_path: Path,
    plugins_repo_dir: Path,
    key_dir: Path,
    key_name: str,
    install_dir: Path,
) -> None:
    print("== Rust Plugin Sync bootstrap ==")
    install_dir.mkdir(parents=True, exist_ok=True)

    if shutil.which("git") is None:
        print(f"ERROR code={EXIT_ENV} git not found in PATH")
        sys.exit(EXIT_ENV)
    if shutil.which("ssh") is None or shutil.which("ssh-keygen") is None:
        print(f"ERROR code={EXIT_ENV} ssh/ssh-keygen not found in PATH")
        sys.exit(EXIT_ENV)

    private_key_path, public_key_path = _ensure_ssh_key(key_dir, key_name)
    ssh_config_path = Path.home() / ".ssh" / "config"
    _ensure_ssh_config_entry(ssh_config_path, private_key_path)

    print(f"SSH config path: {ssh_config_path}")
    print("SSH config contents:")
    print(ssh_config_path.read_text(encoding="utf-8", errors="replace"))
    print(f"Private key exists: {private_key_path.exists()}")
    print(f"Public key exists:  {public_key_path.exists()}")
    print("")
    print("Public key (add to GitHub Deploy Keys, read-only):")
    print(public_key_path.read_text(encoding="utf-8", errors="replace").strip())

    input("Press Enter after you added the key to GitHub: ")

    while True:
        print("Checking SSH access to GitHub...")
        ok, output = _check_ssh_access(private_key_path)
        if output:
            print("SSH output:")
            print(output)
        else:
            print("SSH output:")
            print("(empty output)")
        if ok:
            break
        print("SSH check failed. Verify Deploy Key and access.")
        retry = input("Retry SSH check? (y/n): ").strip().lower()
        if retry != "y":
            cont = input("Continue anyway (skip SSH check)? (y/n): ").strip().lower()
            if cont != "y":
                sys.exit(EXIT_ENV)
            break

    server_root_input = input(
        r"Enter Rust server path (e.g. C:\Users\Administrator\Desktop\server): "
    ).strip()
    if not server_root_input:
        print("ERROR: ServerRoot is required")
        sys.exit(EXIT_ENV)
    server_root = Path(server_root_input)

    repo_url = input(
        "Enter plugins repo SSH URL (e.g. git@github.com:USER/REPO.git): "
    ).strip()
    if not repo_url:
        print("ERROR: Repo URL is required")
        sys.exit(EXIT_ENV)

    if not plugins_repo_dir.exists():
        code, _, err = _run_cmd(["git", "clone", repo_url, str(plugins_repo_dir)])
        if code != 0:
            print(f"ERROR code={EXIT_GIT} git clone failed: {err}")
            sys.exit(EXIT_GIT)

    _write_bootstrap_config(config_path, server_root, plugins_repo_dir)
    print(f"Config created: {config_path}")


def _git_fetch_with_retries(settings: Settings, server: ServerConfig) -> bool:
    for attempt in range(1, settings.git_retry_count + 1):
        code, _, err = _run_git(
            ["fetch"], server.repo_path, settings.git_timeout_seconds
        )
        if code == 0:
            return True
        logging.error(
            "[%s] ERROR code=%s git fetch failed (attempt %s/%s): %s",
            server.name,
            EXIT_GIT,
            attempt,
            settings.git_retry_count,
            err,
        )
        time.sleep(settings.git_retry_delay_seconds)
    return False


def _git_rev_parse(settings: Settings, server: ServerConfig, ref: str) -> str | None:
    code, out, err = _run_git(
        ["rev-parse", ref], server.repo_path, settings.git_timeout_seconds
    )
    if code != 0:
        logging.error(
            "[%s] ERROR code=%s git rev-parse %s failed: %s",
            server.name,
            EXIT_GIT,
            ref,
            err,
        )
        return None
    return out


def _git_reset_hard(settings: Settings, server: ServerConfig, ref: str) -> bool:
    code, _, err = _run_git(
        ["reset", "--hard", ref], server.repo_path, settings.git_timeout_seconds
    )
    if code != 0:
        logging.error(
            "[%s] ERROR code=%s git reset --hard %s failed: %s",
            server.name,
            EXIT_GIT,
            ref,
            err,
        )
        return False
    return True


def _validate_json_from_ref(settings: Settings, server: ServerConfig, ref: str) -> bool:
    code, out, err = _run_git(
        ["ls-tree", "-r", "--name-only", ref, "config"],
        server.repo_path,
        settings.git_timeout_seconds,
    )
    if code != 0:
        logging.error(
            "[%s] ERROR code=%s git ls-tree %s failed: %s",
            server.name,
            EXIT_GIT,
            ref,
            err,
        )
        return False
    files = []
    for line in out.splitlines():
        if not line:
            continue
        rel = line.strip()
        if any(fnmatch.fnmatch(rel, ex) for ex in server.exclude_patterns):
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in server.config_pattern):
            files.append(rel)
    for file in files:
        code, content, err = _run_git(
            ["show", f"{ref}:{file}"],
            server.repo_path,
            settings.git_timeout_seconds,
        )
        if code != 0:
            logging.error(
                "[%s] ERROR code=%s git show %s failed: %s",
                server.name,
                EXIT_GIT,
                file,
                err,
            )
            return False
        try:
            json.loads(content)
        except Exception as exc:
            logging.error(
                "[%s] ERROR code=%s invalid JSON in %s (%s)",
                server.name,
                EXIT_JSON,
                file,
                exc,
            )
            return False
    return True


def _git_commit_info(
    settings: Settings, server: ServerConfig, ref: str
) -> tuple[str, list[str]]:
    code, out, err = _run_git(
        ["show", "--name-only", "--pretty=format:%an", ref],
        server.repo_path,
        settings.git_timeout_seconds,
    )
    if code != 0:
        logging.error(
            "[%s] ERROR code=%s git show %s failed: %s",
            server.name,
            EXIT_GIT,
            ref,
            err,
        )
        return "unknown", []
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    author = lines[0] if lines else "unknown"
    files = lines[1:] if len(lines) > 1 else []
    return author, files


def _sync_tree(
    server: ServerConfig,
    src_dir: Path,
    dest_dir: Path,
    include_patterns: list[str],
    exclude_patterns: list[str],
    delete_extraneous: bool,
    dry_run: bool,
) -> bool:
    try:
        src_files = _collect_files(src_dir, include_patterns, exclude_patterns)
        dest_files = _collect_files(dest_dir, include_patterns, exclude_patterns)

        for rel, src_file in src_files.items():
            dest_path = dest_dir / rel
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.exists():
                src_hash = _hash_file(src_file)
                dest_hash = _hash_file(dest_path)
                if src_hash == dest_hash:
                    continue
                action = f"update {rel}"
            else:
                src_hash = _hash_file(src_file)
                dest_hash = None
                action = f"create {rel}"

            if dry_run:
                logging.info(
                    "[%s][DRY-RUN] Would %s (src=%s dest=%s)",
                    server.name,
                    action,
                    src_file,
                    dest_path if dest_hash is not None else "new",
                )
                continue

            shutil.copy2(src_file, dest_path)
            logging.info("[%s] %s", server.name, action)

        if delete_extraneous:
            extras = set(dest_files.keys()) - set(src_files.keys())
            for rel in extras:
                path = dest_dir / rel
                if dry_run:
                    logging.info("[%s][DRY-RUN] Would delete %s", server.name, path)
                    continue
                try:
                    path.unlink()
                    logging.info("[%s] Deleted extraneous %s", server.name, path)
                except Exception as exc:
                    logging.error(
                        "[%s] ERROR code=%s failed to delete %s: %s",
                        server.name,
                        EXIT_COPY,
                        path,
                        exc,
                    )
                    return False

        return True
    except Exception as exc:
        logging.error(
            "[%s] ERROR code=%s sync failed from %s to %s: %s",
            server.name,
            EXIT_COPY,
            src_dir,
            dest_dir,
            exc,
        )
        return False


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def create_runtime(
    settings: Settings,
) -> tuple[SyncState, SyncController, "SyncRunner"]:
    state = SyncState([srv.name for srv in settings.servers])
    controller = SyncController()
    stop_event = threading.Event()
    runner = SyncRunner(
        settings=settings,
        state=state,
        controller=controller,
        stop_event=stop_event,
    )
    return state, controller, runner


def run(settings: Settings) -> None:
    state, controller, runner = create_runtime(settings)
    logging.info("START")
    time.sleep(settings.startup_delay_seconds)
    runner.run_forever()


def _run_cycle(
    settings: Settings, state: SyncState, controller: SyncController
) -> None:
    for server in settings.servers:
        if not server.enabled:
            logging.info("[%s] Skipped (disabled)", server.name)
            continue
        state.update_server_status(server.name, last_run_time=_utc_now_iso())
        if not _ensure_paths(server):
            missing = []
            if not server.repo_path.exists():
                missing.append(f"RepoPath={server.repo_path}")
            if not (server.repo_path / ".git").exists():
                missing.append(f"RepoPath missing .git={server.repo_path}")
            if not server.plugins_target.exists():
                missing.append(f"PluginsTarget={server.plugins_target}")
            if not server.config_target.exists():
                missing.append(f"ConfigTarget={server.config_target}")
            error_msg = "; ".join(missing)
            logging.error(
                "[%s] ERROR code=%s missing paths: %s",
                server.name,
                EXIT_ENV,
                error_msg,
            )
            state.update_server_status(
                server.name, last_error=error_msg, last_status="ERROR"
            )
            continue

        branch = server.branch or settings.branch

        if not _git_fetch_with_retries(settings, server):
            state.update_server_status(server.name, last_status="ERROR")
            continue

        local = _git_rev_parse(settings, server, "HEAD")
        remote = _git_rev_parse(settings, server, f"origin/{branch}")
        if not local or not remote:
            state.update_server_status(server.name, last_status="ERROR")
            continue

        deploy_needed = local != remote
        if not deploy_needed:
            logging.info("[%s] No commit diff, verifying hashes", server.name)

        if not _validate_json_from_ref(settings, server, f"origin/{branch}"):
            state.update_server_status(server.name, last_status="ERROR")
            continue

        if not _git_reset_hard(settings, server, remote):
            state.update_server_status(server.name, last_status="ERROR")
            continue

        effective_dry_run = settings.dry_run or controller.get_dry_run()
        start = time.time()

        synced_plugins = _sync_tree(
            server,
            server.repo_path / "plugins",
            server.plugins_target,
            server.plugins_pattern,
            server.exclude_patterns,
            server.delete_extraneous,
            effective_dry_run,
        )
        if not synced_plugins:
            state.update_server_status(server.name, last_status="ERROR")
            continue

        synced_config = _sync_tree(
            server,
            server.repo_path / "config",
            server.config_target,
            server.config_pattern,
            server.exclude_patterns,
            server.delete_extraneous,
            effective_dry_run,
        )
        if not synced_config:
            state.update_server_status(server.name, last_status="ERROR")
            continue

        duration = time.time() - start
        author, files = _git_commit_info(settings, server, remote)
        state.update_server_status(
            server.name,
            last_commit=remote,
            last_duration_seconds=duration,
            last_error=None,
            last_status="OK",
        )
        if deploy_needed:
            state.update_server_status(server.name, last_deploy_time=_utc_now_iso())
            state.add_history(
                DeploymentRecord(
                    server=server.name,
                    commit=remote,
                    author=author,
                    files=files,
                    duration_seconds=duration,
                    timestamp=_utc_now_iso(),
                    status="OK",
                )
            )
            logging.info("[%s] Deployed commit %s", server.name, remote)


class SyncRunner:
    def __init__(
        self,
        settings: Settings,
        state: SyncState,
        controller: SyncController,
        stop_event: threading.Event,
    ):
        self.settings = settings
        self.state = state
        self.controller = controller
        self._stop_event = stop_event

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            if self.controller.consume_run_once():
                _run_cycle(self.settings, self.state, self.controller)
                if self.controller.is_paused():
                    self._sleep_with_stop(1)
                else:
                    self._sleep_with_stop(self.settings.interval_seconds)
                continue

            if self.controller.is_paused():
                self._sleep_with_stop(1)
                continue

            _run_cycle(self.settings, self.state, self.controller)
            self._sleep_with_stop(self.settings.interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()

    def _sleep_with_stop(self, seconds: int) -> None:
        remaining = max(0, int(seconds * 2))
        while remaining > 0 and not self._stop_event.is_set():
            time.sleep(0.5)
            remaining -= 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Rust plugins/config sync service")
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON"
    )
    parser.add_argument(
        "--plugins-repo-dir",
        default=DEFAULT_PLUGINS_REPO_DIR,
        help="Path to plugins repo clone",
    )
    parser.add_argument(
        "--key-dir",
        default=DEFAULT_KEY_DIR,
        help="Path to SSH keys directory",
    )
    parser.add_argument(
        "--key-name",
        default=DEFAULT_KEY_NAME,
        help="SSH key base filename",
    )
    parser.add_argument(
        "--install-dir",
        default=DEFAULT_INSTALL_DIR,
        help="Base install directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not modify files, only log planned actions",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Run interactive bootstrap before starting",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start web UI (runs sync loop in background)",
    )
    parser.add_argument(
        "--web-host",
        default="0.0.0.0",
        help="Web UI host",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8787,
        help="Web UI port",
    )
    args = parser.parse_args()

    try:
        config_path = Path(args.config)
        if args.bootstrap or not config_path.exists():
            _bootstrap_interactive(
                config_path=config_path,
                plugins_repo_dir=Path(args.plugins_repo_dir),
                key_dir=Path(args.key_dir),
                key_name=args.key_name,
                install_dir=Path(args.install_dir),
            )
        cfg = _load_config(config_path)
        settings = _settings_from_config(cfg)
    except FileNotFoundError:
        _write_sample_config(Path(args.config))
        print(f"ERROR code={EXIT_ENV} config created at: {args.config}")
        print("Please edit the config and restart the service.")
        sys.exit(EXIT_ENV)
    except json.JSONDecodeError as exc:
        print(f"ERROR code={EXIT_CONFIG} config JSON invalid: {exc}")
        sys.exit(EXIT_CONFIG)
    except (KeyError, ValueError) as exc:
        print(f"ERROR code={EXIT_CONFIG} config validation failed: {exc}")
        sys.exit(EXIT_CONFIG)
    except Exception as exc:
        print(f"ERROR code={EXIT_CONFIG} config load failed: {exc}")
        sys.exit(EXIT_CONFIG)

    if args.dry_run:
        settings.dry_run = True

    if shutil.which("git") is None:
        print(f"ERROR code={EXIT_ENV} git not found in PATH")
        sys.exit(EXIT_ENV)

    _setup_logging(settings.log_path)
    if args.web:
        from rust_sync.webapp import WebRuntime, run_web

        runtime = WebRuntime(settings=settings, config_path=config_path)
        runtime.start()
        run_web(
            runtime=runtime,
            host=args.web_host,
            port=args.web_port,
        )
        return

    try:
        run(settings)
    except KeyboardInterrupt:
        logging.info("STOP")


if __name__ == "__main__":
    main()
