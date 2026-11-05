"""Check each isolated entry with analysis-only declarations for Noctalia globals."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = ("widget.luau", "panel.luau", "service.luau")


def check_types(binary):
    stubs = "\n".join((ROOT / "types" / name).read_text() for name in ("ui.d.luau", "noctalia.d.luau"))
    with tempfile.TemporaryDirectory(prefix="fitdash-types-") as directory:
        for entry in ENTRIES:
            source = (ROOT / entry).read_text()
            assert source.startswith("--!strict\n"), f"{entry} must use strict mode"
            script = Path(directory) / entry
            script.write_text(
                "--!strict\n--!nolint LocalUnused\n--!nolint FunctionUnused\n"
                + stubs
                + "\n"
                + source.removeprefix("--!strict\n")
            )
            subprocess.run([binary, str(script)], check=True)
            print(entry + ": types passed")


if __name__ == "__main__":
    check_types(os.environ.get("LUAU_ANALYZE", "luau-analyze"))
