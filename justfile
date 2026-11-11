# pkidl task runner. spike/ has its own justfile for the boards it builds.
# See https://github.com/CameronBrooks11/dev-toolbox/blob/main/docs/just-conventions.md

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

# Refill and DRC every corpus reference with KiCad, then print the scorecard
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
    uv run python scripts/corpus.py score build/corpus
