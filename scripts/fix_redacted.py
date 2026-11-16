import os
import glob

files = [
    "app/services/chemistry_service.py",
    "app/database.py",
]

for fpath in files:
    with open(fpath, "r") as f:
        content = f.read()
    # Replace literal [redacted] placeholders
    replacements = {
        "max_tokens=[redacted]": "max_tokens=4096",
        "api_key=[redacted]": 'api_key=os.getenv("DEEPSEEK_API_KEY", "")',
        "password = [redacted]": 'password = os.getenv("NEO4J_PASSWORD", "neo4j")',
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    with open(fpath, "w") as f:
        f.write(content)
    print(f"Fixed: {fpath}")
print("All done")
