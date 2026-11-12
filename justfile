# pkidl task runner. spike/ has its own justfile for the boards it builds.

# KiCad ships as a flatpak locally and as a plain binary in CI/containers.
kicad_cli := env_var_or_default("KICAD_CLI", "flatpak run --command=kicad-cli org.kicad.KiCad")

# Default: show available recipes
default:
    @just --list

# Install dependencies and set up environment
setup:
    uv sync

# Format code (mutates working tree — use locally)
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Verify formatting (non-mutating — use in CI)
fmt-check:
    uv run ruff format --check .

# Run linters
lint:
    uv run ruff check .

# Type-check
typecheck:
    uv run pyright

# Format + lint + type-check (non-mutating — safe for CI)
check: fmt-check lint typecheck

# Run tests
test:
    uv run pytest

# DRC every corpus reference, build and DRC every board.py, print the scorecard
corpus:
    #!/usr/bin/env bash
    set -euo pipefail
    for ref in corpus/*/*/reference.kicad_pcb; do
        d="build/corpus/$(basename "$(dirname "$ref")")"
        mkdir -p "$d"
        rm -f "$d/not-refilled"
        cp "$ref" "$d/"
        # Some of these older boards' pours never finish refilling in KiCad 10; past
        # ten minutes, the board is checked on its pours as saved, and marked.
        if ! timeout 600 {{ kicad_cli }} pcb drc --refill-zones --save-board --severity-all \
                --format json -o "$d/drc.json" "$d/reference.kicad_pcb"; then
            cp "$ref" "$d/"
            {{ kicad_cli }} pcb drc --severity-all --format json \
                -o "$d/drc.json" "$d/reference.kicad_pcb"
            echo "KiCad's refill ran past 600 s; DRC on the zones as saved" > "$d/not-refilled"
        fi
    done
    # A board file that does not build is a row of the scorecard, and fails the recipe
    # once the scorecard is printed.
    built=0
    uv run python scripts/corpus.py build build/corpus || built=$?
    for board in build/corpus/*/built.kicad_pcb; do
        [ -e "$board" ] || continue
        d="$(dirname "$board")"
        rm -f "$d/built-drc.json"
        grep -qs '"built": true' "$d/built.json" || continue
        {{ kicad_cli }} pcb drc --refill-zones --save-board --severity-all \
            --format json -o "$d/built-drc.json" "$board"
    done
    uv run python scripts/corpus.py score build/corpus
    exit "$built"
