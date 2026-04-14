import json
import secrets
from pathlib import Path


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    example_path = here / "local.settings.example.json"
    out_path = here / "local.settings.json"

    if not example_path.exists():
        raise SystemExit(f"Missing {example_path}")

    data = json.loads(example_path.read_text(encoding="utf-8"))
    values = data.setdefault("Values", {})
    if values.get("JWT_SECRET", "").startswith("CHANGE_ME") or not values.get("JWT_SECRET"):
        values["JWT_SECRET"] = secrets.token_urlsafe(48)
    values.setdefault("AzureWebJobsSecretStorageType", "Files")
    values.setdefault("LOCAL_DEV_MODE", "1")

    # Ensure Azure Functions can import dependencies even if it ignores the venv.
    python_packages = (here / ".python_packages" / "lib" / "site-packages").resolve()
    values["PYTHONPATH"] = str(python_packages)
    values.setdefault("PYTHON_ISOLATE_WORKER_DEPENDENCIES", "1")

    venv_python = (here / ".venv" / "bin" / "python").resolve()
    if venv_python.exists():
        # Make Azure Functions Core Tools use the venv python so imports work locally.
        values["languageWorkers__python__defaultExecutablePath"] = str(venv_python)

    data["IsEncrypted"] = False

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print("JWT_SECRET was generated (or preserved if already set in the example).")


if __name__ == "__main__":
    main()
