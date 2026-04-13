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
    data["IsEncrypted"] = False

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print("JWT_SECRET was generated (or preserved if already set in the example).")


if __name__ == "__main__":
    main()
