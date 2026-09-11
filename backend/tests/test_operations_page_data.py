import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "assets" / "operations-page-data.js"


def run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script, str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_package_total_uses_all_synced_tasks_not_only_dispatched_work_orders() -> None:
    result = run_node(
        """
const operations = require(process.argv[1]);
const paths = [];
async function request(path) {
  paths.push(path);
  if (path === "/packages/operations-overview?production_date=2026-09-16") {
    return Array.from({ length: 5 }, (_, index) => ({ package_id: `package-${index}` }));
  }
  if (path === "/tasks/overview?task_date=2026-09-16") {
    return Array.from({ length: 53 }, (_, index) => ({ task_id: `task-${index}` }));
  }
  throw new Error(`unexpected data source: ${path}`);
}
(async () => {
  const data = await operations.loadPackagePageData(request, "2026-09-16");
  process.stdout.write(JSON.stringify({
    packageCount: data.items.length,
    total: data.workOrderTotal,
    paths,
  }));
})();
"""
    )

    assert result == {
        "packageCount": 5,
        "total": 53,
        "paths": [
            "/packages/operations-overview?production_date=2026-09-16",
            "/tasks/overview?task_date=2026-09-16",
        ],
    }


def test_workorder_heading_prominently_includes_daily_total() -> None:
    result = run_node(
        """
const operations = require(process.argv[1]);
const tasks = Array.from({ length: 53 }, (_, index) => ({ task_id: `task-${index}` }));
process.stdout.write(JSON.stringify({ subtitle: operations.workOrderSubtitle(tasks) }));
"""
    )

    assert result["subtitle"] == "当天共 53 条工单 · 罗列需要生产运营包的剧目，并显示搜索、标题、封面、说明、社群、合成进度"
