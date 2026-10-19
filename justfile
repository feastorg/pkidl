# kidl-spike task runner
# See https://github.com/CameronBrooks11/dev-toolbox/blob/main/docs/just-conventions.md

set dotenv-load := true

# KiCad-Master-Lib checkout. Every symbol/footprint nickname resolves through this
# — see _planning/00-prereqs.md (R1). Override in .env if yours lives elsewhere.
export KICAD_MASTER_LIB := env_var_or_default("KICAD_MASTER_LIB", justfile_directory() / "../KiCad-Master-Lib")

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

# ─── Hardware ────────────────────────────────────────────────────────────────
# KiCad output is a build artifact, not source. Everything under build/ is
# generated and gitignored — regenerate it, never hand-edit it.

# Verify the toolchain and library resolution are actually wired up
doctor:
    uv run python -m kidl_spike.doctor

# Generate a board's KiCad files from Python (e.g. `just gen loaf`)
gen board:
    uv run python -m kidl_spike.boards.{{ board }}

# Run KiCad's own ERC against a generated schematic
erc board:
    {{ kicad_cli }} sch erc --exit-code-violations \
        -o build/{{ board }}/erc.rpt build/{{ board }}/{{ board }}.kicad_sch

# Run KiCad's own DRC against a generated board, including schematic parity
drc board:
    {{ kicad_cli }} pcb drc --schematic-parity --exit-code-violations \
        -o build/{{ board }}/drc.rpt build/{{ board }}/{{ board }}.kicad_pcb

# Generate and verify a board end to end
verify board: (gen board) (erc board) (drc board)

# Remove build artifacts
clean:
    rm -rf .venv build dist .pytest_cache .ruff_cache .pyright
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
