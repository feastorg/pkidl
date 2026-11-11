"""Board generators — one module per BREAD board.

Each module builds a board's electrical layer in SKiDL and emits KiCad files
into ``build/``. KiCad is the oracle for correctness; see ``just verify``.
"""
