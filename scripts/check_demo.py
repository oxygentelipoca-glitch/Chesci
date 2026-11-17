"""Exercise the public demo against disposable databases, with external AI disabled."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(ROOT))
    with TemporaryDirectory() as directory:
        demo_dir = Path(directory)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{demo_dir / 'demo-users.db'}",
            CHEMISTRY_DB_URL=f"sqlite:///{demo_dir / 'demo-reactions.db'}",
            DEEPSEEK_API_KEY="", HF_HUB_OFFLINE="1",
        )
        for _ in range(2):
            subprocess.run([sys.executable, str(ROOT / "scripts/seed_chemistry.py"),
                            "--directory", directory], cwd=directory, check=True)

        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            def post(endpoint, **data):
                response = client.post("/api/chemistry/" + endpoint, json=data)
                response.raise_for_status()
                return response.json()["data"]

            query = {"query": "肉桂酸", "starting_material": "苯甲醛"}
            analysis = post("analyze", **query, max_temperature=80)
            matches = analysis["filter_matches"]
            assert matches["total_ranked"] == 3
            assert matches["total_exact"] == 1
            first = matches["items"][0]
            second = next(r for r in matches["items"] if r["temp_val"] == 110)
            assert first["temp_val"] == 65 and first["exact"]
            paper = next(r for r in matches["items"] if r["literature_doi"])
            assert paper["literature_doi"] == "10.22146/ijc.21626"
            assert paper["temp_val"] is None and paper["checks"][0]["status"] == "unknown"
            assert paper["time_val"] == 5 and paper["yield_"] == "85.3 ± 2.9%"
            assert [ref["url"].split("#")[-1] for ref in paper["source_refs"]] == ["page=2", "page=3"]
            for threshold, expected in [(80, "met"), (85, "unknown"), (90, "conflict")]:
                result = post("analyze", **query, min_yield=threshold)["filter_matches"]
                row = next(r for r in result["items"] if r["id"] == paper["id"])
                assert row["checks"][0]["status"] == expected
            assert second["score"]["total"] > first["score"]["total"]
            assert [r["checks"][0]["status"] for r in (first, second)] == ["met", "conflict"]
            assert "110 °C" in second["checks"][0]["record"] and second["source_page"] == 2
            assert "模拟来源卡 B" in second["literature_title"]
            for candidate in matches["items"]:
                dimensions = candidate["score"]["dimensions"]
                assert sum(d["weight"] for d in dimensions) == 100
                assert abs(candidate["score"]["total"] - sum(d["score"] * d["weight"]/100 for d in dimensions)) < 0.1
            absent = post("analyze", **query, solvent="without")["filter_matches"]
            assert absent["total_exact"] == 0
            assert all(r["checks"][0]["status"] == ("conflict" if r["id"] == paper["id"] else "unknown")
                       for r in absent["items"])
            assert post("analyze", **query, max_temperature=45)["filter_matches"]["total_exact"] == 0
            record = paper
            plan = post("experiment-plan", compound={"name": query["query"]}, route={
                "temperature": record["conditions_summary"][0]["temperature"],
                "literature_title": record["literature_title"],
                "yield": record["yield_"],
            })
            assert plan.get("mode") == "offline_record"
            assert "回流" in plan["plan"] and paper["yield_"] in plan["plan"]
            assert paper["literature_title"] in plan["plan"]
    print("通过：重复初始化、80/45 °C 约束、选定路线的离线草案和来源。")


if __name__ == "__main__":
    main()
