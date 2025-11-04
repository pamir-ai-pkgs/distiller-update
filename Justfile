default:
    @just --list

build arch="arm64":
    #!/usr/bin/env bash
    set -e
    export DEB_BUILD_OPTIONS="parallel=$(nproc)"
    debuild -us -uc -b -a{{ arch }} -d --lintian-opts --profile=debian
    mkdir -p dist && mv ../*.deb dist/ 2>/dev/null || true
    rm -f ../*.{dsc,tar.*,changes,buildinfo,build}

changelog:
    gbp dch -R --ignore-branch --release

clean:
    rm -rf debian/.debhelper debian/files debian/*.log debian/*.substvars debian/distiller-update debian/debhelper-build-stamp dist
    rm -f ../*.deb ../*.dsc ../*.tar.* ../*.changes ../*.buildinfo ../*.build
    rm -rf build *.egg-info .venv .pytest_cache htmlcov .coverage
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Python project recipes
setup:
    uv sync

lint:
    uv run ruff check src/
    uv run ruff format --check src/
    uv run mypy src/

fix:
    uv run ruff check --fix src/
    uv run ruff format src/
