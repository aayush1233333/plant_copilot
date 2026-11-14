import pathlib
import zipfile

SKIP = {".venv", "venv", "__pycache__", ".pytest_cache", ".checkpoints", ".git"}
OUT = pathlib.Path("plant_copilot_submission.zip")

files = [
    p for p in sorted(pathlib.Path(".").rglob("*"))
    if p.is_file() and p.name != OUT.name and not any(part in SKIP for part in p.parts)
]

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in files:
        zf.write(p, p.as_posix())

print(f"Packaged {len(files)} files into {OUT} ({OUT.stat().st_size} bytes)")
with zipfile.ZipFile(OUT, "r") as zf:
    for name in zf.namelist():
        print(" -", name)
