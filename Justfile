default:
    @just --list

setup:
    uv sync

clean:
    rm -rf debian/.debhelper debian/files debian/*.log debian/*.substvars debian/distiller-update debian/debhelper-build-stamp dist
    rm -f ../*.deb ../*.dsc ../*.tar.* ../*.changes ../*.buildinfo ../*.build
    rm -rf build *.egg-info .venv uv.lock .pytest_cache htmlcov .coverage
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true

build arch="all":
    #!/usr/bin/env bash
    set -e
    export DEB_BUILD_OPTIONS="parallel=$(nproc)"
    debuild -us -uc -b -d --lintian-opts --profile=debian
    mkdir -p dist && mv ../*.deb dist/ 2>/dev/null || true
    rm -f ../*.{dsc,tar.*,changes,buildinfo,build}

changelog:
    dch -i

test:
    uv run pytest

test-cov:
    uv run pytest --cov=distiller_update --cov-report=term-missing --cov-report=html

lint:
    uv run ruff check src/
    uv run ruff format --check src/
    uv run mypy src/

fix:
    uv run ruff check --fix src/
    uv run ruff format src/

man:
    #!/usr/bin/env bash
    set -e
    if ! command -v help2man &> /dev/null; then
        echo "Error: help2man not found. Install with: sudo apt install help2man"
        exit 1
    fi
    VERSION=$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
    DATE=$(date '+%Y-%m-%d')
    mkdir -p debian
    chmod +x debian/distiller-update-help
    help2man \
        --name='APT update checker for Pamir AI Distiller devices' \
        --section=1 \
        --version-string="$VERSION" \
        --no-info \
        --include=debian/distiller-update.help2man.include \
        --output=debian/distiller-update.1 \
        debian/distiller-update-help
    # Fix program name in generated man page
    sed -i 's/DISTILLER-UPDATE-HELP/DISTILLER-UPDATE/; s/distiller-update-help/distiller-update/g' debian/distiller-update.1
    echo "Generated debian/distiller-update.1 (version $VERSION, $DATE)"
