# kidl-spike task runner
# See https://github.com/CameronBrooks11/dev-toolbox/blob/main/docs/just-conventions.md

set dotenv-load := true

# KiCad-Master-Lib checkout. Every symbol/footprint nickname resolves through this
# — see _planning/01-kidl-spike.md (R1). Override in .env if yours lives elsewhere.
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
    uv run python -m kidl_spike.build {{ board }}

# The gates fail on errors only; warnings are reported, not gated. Each check
# writes the full report (all severities) first, then gates. Severities come
# from the generated .kicad_pro, which escalates schematic parity to errors.

# Run KiCad's own ERC against a generated schematic
erc board:
    {{ kicad_cli }} sch erc --severity-all \
        -o build/{{ board }}/erc.rpt build/{{ board }}/{{ board }}.kicad_sch
    {{ kicad_cli }} sch erc --severity-error --exit-code-violations \
        -o build/{{ board }}/erc-errors.rpt build/{{ board }}/{{ board }}.kicad_sch

# Run KiCad's own DRC against a generated board: zones refilled, schematic parity
drc board:
    {{ kicad_cli }} pcb drc --refill-zones --schematic-parity --severity-all \
        -o build/{{ board }}/drc.rpt build/{{ board }}/{{ board }}.kicad_pcb
    {{ kicad_cli }} pcb drc --refill-zones --schematic-parity --severity-error \
        --exit-code-violations \
        -o build/{{ board }}/drc-errors.rpt build/{{ board }}/{{ board }}.kicad_pcb

# Export Gerbers, drill files and a PDF render into build/<board>/fab
fab board:
    {{ kicad_cli }} pcb export gerbers --check-zones \
        -l F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
        -o build/{{ board }}/fab/gerbers/ build/{{ board }}/{{ board }}.kicad_pcb
    {{ kicad_cli }} pcb export drill --generate-map --map-format pdf \
        -o build/{{ board }}/fab/drill/ build/{{ board }}/{{ board }}.kicad_pcb
    {{ kicad_cli }} pcb export pdf --check-zones --mode-multipage \
        -l F.Cu,B.Cu,F.SilkS,B.SilkS,Edge.Cuts \
        -o build/{{ board }}/fab/{{ board }}.pdf build/{{ board }}/{{ board }}.kicad_pcb

# Generate and verify a board end to end
verify board: (gen board) (erc board) (drc board)

# Remove build artifacts
clean:
    rm -rf .venv build dist .pytest_cache .ruff_cache .pyright
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
