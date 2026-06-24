"""SDD 23 — make release: transforms del CHANGELOG/Chart/build (sin git)."""
from scripts import release


def test_bump_changelog_inserts_version_under_unreleased():
    src = "# Changelog\n\n## [Unreleased]\n\n### 2026-06-24 — algo\n- x\n"
    out = release.bump_changelog(src, "1.3.0", "2026-06-24")
    assert "## [Unreleased]\n\n## [1.3.0] - 2026-06-24" in out
    assert "### 2026-06-24 — algo" in out  # las entradas quedan bajo la versión


def test_bump_changelog_requires_unreleased():
    import pytest

    with pytest.raises(SystemExit):
        release.bump_changelog("# Changelog\nsin seccion\n", "1.0.0", "2026-06-24")


def test_set_chart_appversion():
    out = release.set_chart_appversion('name: x\nappVersion: "0.1.0"\n', "1.3.0")
    assert 'appVersion: "1.3.0"' in out and "0.1.0" not in out


def test_set_build_tag():
    out = release.set_build_tag('--destination=registry:5000/online-game:1.2.3"', "1.3.0")
    assert "online-game:1.3.0" in out and "1.2.3" not in out


def test_main_rejects_bad_version():
    assert release.main(["release.py", "nope"]) == 2
