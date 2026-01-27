import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_ENV = 1
EXIT_GIT = 2
EXIT_JSON = 3
EXIT_COPY = 4

DEFAULT_CONFIG_PATH = r"C:\deploy\rust-sync.json"


@dataclass
class Settings:
    repo_path: Path
    server_root: Path
    plugins_target: Path
    config_target: Path
    log_path: Path
    interval_seconds: int
    branch: str
    git_retry_count: int
    git_retry_delay_seconds: int


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _settings_from_config(cfg: dict[str, Any]) -> Settings:
    def _req(key: str) -> Any:
        if key not in cfg:
            raise KeyError(f"Missing config key: {key}")
        return cfg[key]

    repo_path = Path(_req("RepoPath"))
    server_root = Path(_req("ServerRoot"))
    plugins_target = Path(_req("PluginsTarget"))
    config_target = Path(_req("ConfigTarget"))
    log_path = Path(_req("LogPath"))

    interval_seconds = int(cfg.get("IntervalSeconds", 120))
    branch = str(cfg.get("Branch", "main"))
    git_retry_count = int(cfg.get("GitRetryCount", 3))
    git_retry_delay_seconds = int(cfg.get("GitRetryDelaySeconds", 10))

    return Settings(
        repo_path=repo_path,
        server_root=server_root,
        plugins_target=plugins_target,
        config_target=config_target,
        log_path=log_path,
        interval_seconds=interval_seconds,
        branch=branch,
        git_retry_count=git_retry_count,
        git_retry_delay_seconds=git_retry_delay_seconds,
    )


def _ensure_paths(settings: Settings) -> bool:
    return (
        settings.repo_path.exists()
        and settings.plugins_target.exists()
        and settings.config_target.exists()
    )


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _git_fetch_with_retries(settings: Settings) -> bool:
    for attempt in range(1, settings.git_retry_count + 1):
        code, _, err = _run_git(["fetch"], settings.repo_path)
        if code == 0:
            return True
        logging.error("ERROR code=%s git fetch failed (attempt %s/%s): %s", EXIT_GIT, attempt, settings.git_retry_count, err)
        time.sleep(settings.git_retry_delay_seconds)
    return False


def _git_rev_parse(settings: Settings, ref: str) -> str | None:
    code, out, err = _run_git(["rev-parse", ref], settings.repo_path)
    if code != 0:
        logging.error("ERROR code=%s git rev-parse %s failed: %s", EXIT_GIT, ref, err)
        return None
    return out


def _git_reset_hard(settings: Settings, ref: str) -> bool:
    code, _, err = _run_git(["reset", "--hard", ref], settings.repo_path)
    if code != 0:
        logging.error("ERROR code=%s git reset --hard %s failed: %s", EXIT_GIT, ref, err)
        return False
    return True


def _validate_json_files(path: Path) -> bool:
    for file in path.glob("*.json"):
        try:
            with file.open("r", encoding="utf-8") as f:
                json.load(f)
        except Exception as exc:
            logging.error("ERROR code=%s invalid JSON: %s (%s)", EXIT_JSON, file, exc)
            return False
    return True


def _copy_files(src_dir: Path, pattern: str, dest_dir: Path) -> bool:
    try:
        for file in src_dir.glob(pattern):
            if file.is_file():
                shutil.copy2(file, dest_dir / file.name)
        return True
    except Exception as exc:
        logging.error("ERROR code=%s copy failed from %s to %s: %s", EXIT_COPY, src_dir, dest_dir, exc)
        return False


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )


def run(settings: Settings) -> None:
    logging.info("START")
    while True:
        if not _ensure_paths(settings):
            logging.error("ERROR code=%s missing paths", EXIT_ENV)
            time.sleep(settings.interval_seconds)
            continue

        if not _git_fetch_with_retries(settings):
            time.sleep(settings.interval_seconds)
            continue

        local = _git_rev_parse(settings, "HEAD")
        remote = _git_rev_parse(settings, f"origin/{settings.branch}")
        if not local or not remote:
            time.sleep(settings.interval_seconds)
            continue

        if local == remote:
            logging.info("No changes")
            time.sleep(settings.interval_seconds)
            continue

        previous = local
        if not _git_reset_hard(settings, remote):
            time.sleep(settings.interval_seconds)
            continue

        if not _validate_json_files(settings.repo_path / "config"):
            _git_reset_hard(settings, previous)
            time.sleep(settings.interval_seconds)
            continue

        if not _copy_files(settings.repo_path / "plugins", "*.cs", settings.plugins_target):
            time.sleep(settings.interval_seconds)
            continue
        if not _copy_files(settings.repo_path / "config", "*.json", settings.config_target):
            time.sleep(settings.interval_seconds)
            continue

        logging.info("Deployed commit %s", remote)
        time.sleep(settings.interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rust plugins/config sync service")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON")
    args = parser.parse_args()

    try:
        cfg = _load_config(Path(args.config))
        settings = _settings_from_config(cfg)
    except Exception as exc:
        print(f"ERROR code={EXIT_ENV} config load failed: {exc}")
        sys.exit(EXIT_ENV)

    _setup_logging(settings.log_path)
    try:
        run(settings)
    except KeyboardInterrupt:
        logging.info("STOP")


if __name__ == "__main__":
    main()
