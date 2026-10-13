"""Run after uv sync --project backend --extra embedding --extra ocr --extra packaging."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
command = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name",
    "server",
    "--distpath",
    str(root / "backend/dist"),
    "--workpath",
    str(root / "backend/build"),
    "--specpath",
    str(root / "backend/build"),
    "--paths",
    str(root / "backend/src"),
]
for package in [
    "edge_knowledge",
    "chromadb",
    "sentence_transformers",
    "transformers",
    "torch",
    "tokenizers",
    "pypdf",
    "docx",
    "uvicorn",
    "PIL",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "shapely",
    "keyring",
    "av",
    "tzdata",
]:
    command.extend(["--collect-all", package])
if sys.platform == "darwin":
    for package in ["objc", "Foundation", "Vision", "Quartz", "CoreML"]:
        command.extend(["--collect-all", package])
command.append(str(root / "backend/build_entry.py"))
subprocess.run(command, cwd=root, check=True)
