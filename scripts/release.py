#!/usr/bin/env python3
"""Corta un release con disciplina SemVer (SDD 23): una versión, una sola fuente del número.

Hace (en orden):
  1. valida que la versión sea X.Y.Z y que el working tree esté limpio,
  2. mueve `## [Unreleased]` del CHANGELOG a `## [X.Y.Z] - FECHA`,
  3. setea `appVersion` en Chart.yaml y el tag en deploy/build/online-game-kaniko.yaml,
  4. git commit "release vX.Y.Z" + git tag vX.Y.Z,
  5. imprime los próximos pasos (build + helm upgrade --set image.tag=X.Y.Z).

Uso:  python scripts/release.py X.Y.Z [--dry-run]   (o:  make release V=X.Y.Z)
No hace push (lo hacés vos): `git push --follow-tags`.
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def bump_changelog(text: str, version: str, date: str) -> str:
    """Inserta `## [version] - date` justo debajo de `## [Unreleased]` (las entradas acumuladas
    pasan a ser las del release; queda un [Unreleased] vacío arriba)."""
    marker = "## [Unreleased]"
    if marker not in text:
        raise SystemExit("CHANGELOG sin sección '## [Unreleased]'")
    return text.replace(marker, f"{marker}\n\n## [{version}] - {date}", 1)


def set_chart_appversion(text: str, version: str) -> str:
    return re.sub(r'(?m)^appVersion:.*$', f'appVersion: "{version}"', text)


def set_build_tag(text: str, version: str) -> str:
    return re.sub(r"online-game:[0-9]+\.[0-9]+\.[0-9]+", f"online-game:{version}", text)


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    dry = "--dry-run" in argv
    if not args or not _SEMVER.match(args[0]):
        print("uso: release.py X.Y.Z [--dry-run]", file=sys.stderr)
        return 2
    version = args[0]
    date = _dt.date.today().isoformat()

    if not dry:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
        if dirty:
            print("ABORT: working tree con cambios sin commitear.", file=sys.stderr)
            return 1

    files = {
        ROOT / "CHANGELOG.md": bump_changelog,
        ROOT / "deploy/helm/Chart.yaml": set_chart_appversion,
        ROOT / "deploy/build/online-game-kaniko.yaml": set_build_tag,
    }
    for path, fn in files.items():
        original = path.read_text(encoding="utf-8")
        updated = fn(original, version, date) if fn is bump_changelog else fn(original, version)
        if dry:
            estado = "cambia" if updated != original else "sin cambios"
            print(f"[dry-run] {path.relative_to(ROOT)}: {estado}")
            continue
        path.write_text(updated, encoding="utf-8")

    if dry:
        print(f"[dry-run] release {version} ({date}) — no se tocó git")
        return 0

    _git("add", "CHANGELOG.md", "deploy/helm/Chart.yaml", "deploy/build/online-game-kaniko.yaml")
    _git("commit", "-m", f"release v{version}")
    _git("tag", f"v{version}")
    print(f"\n✅ release v{version} commiteado y taggeado. Próximos pasos:")
    print("   git push --follow-tags")
    print("   kubectl create -f deploy/build/online-game-kaniko.yaml   # build (gate de tests)")
    print("   helm upgrade galaxy deploy/helm -n online-game -f <values> --atomic"
          f" --set image.tag={version}")
    print("   helm test galaxy -n online-game")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
