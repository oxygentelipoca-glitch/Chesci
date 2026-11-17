"""Seed the isolated competition demo using the normal reviewed-record importer."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--directory", type=Path, default=None)
    target.add_argument("--configured-databases", action="store_true",
                        help="向环境变量明确指定的比赛数据库追加演示数据")
    parser.add_argument("--neo4j", action="store_true", help="另同步到已配置的专用演示图数据库")
    args = parser.parse_args()
    if args.configured_databases:
        if not all(os.environ.get(name) for name in ("DATABASE_URL", "CHEMISTRY_DB_URL")):
            parser.error("--configured-databases 需要同时设置 DATABASE_URL 和 CHEMISTRY_DB_URL")
    else:
        directory = (args.directory or Path(".chemroute-demo")).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        os.environ["DATABASE_URL"] = f"sqlite:///{directory / 'demo-users.db'}"
        os.environ["CHEMISTRY_DB_URL"] = f"sqlite:///{directory / 'demo-reactions.db'}"
    sys.path.insert(0, str(ROOT))
    from app.chemistry.scifinder_import import import_reviewed_reactions

    for filename, pages, label in [
        ("demo-routes.json", 2, "人工编写的演示数据"),
        ("published-cinnamic-acid.json", 5, "公开论文记录"),
    ]:
        fixture = ROOT / "docs" / filename
        raw = fixture.read_bytes()
        data = json.loads(raw)
        result = import_reviewed_reactions(
            schemes=data["schemes"], reactions=data["reactions"], file_name=filename,
            source_sha256=hashlib.sha256(raw).hexdigest(), page_count=pages, model_used=label,
        )
        print(f"{label}：新增 {result['reactions_imported']} 条")
    if not args.configured_databases:
        print(directory / "demo-reactions.db")
    if args.neo4j:
        from app.chemistry.knowledge_graph import sync_to_neo4j
        synced = sync_to_neo4j()
        if not synced.get("success"):
            parser.exit(1, f"{synced}\n")
        print(synced)


if __name__ == "__main__":
    main()
