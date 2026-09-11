import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "assets" / "media-gallery.js"


def run_node(program: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", program, str(MODULE)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_folder_upload_omits_ds_store_before_sending_files() -> None:
    result = run_node(
        """
const media = require(process.argv[1]);
const files = [{name: '.DS_Store'}, {name: 'cover.png'}, {name: 'nested/.DS_Store'}];
process.stdout.write(JSON.stringify({names: media.filterImportFiles(files).map(file => file.name)}));
"""
    )

    assert result == {"names": ["cover.png"]}


def test_history_loader_defaults_to_one_row_and_pages_ten_rows_when_expanded() -> None:
    result = run_node(
        """
const media = require(process.argv[1]);
const paths = [];
async function request(path) {
  paths.push(path);
  return {total: 60, items: Array.from({length: path.includes('limit=1&') ? 1 : 10}, (_, i) => ({id: i}))};
}
(async () => {
  const collapsed = await media.loadRunHistory(request, {batchId: 'batch-1', expanded: false, page: 1});
  const expanded = await media.loadRunHistory(request, {batchId: 'batch-1', expanded: true, page: 6});
  process.stdout.write(JSON.stringify({collapsed, expanded, paths}));
})();
"""
    )

    assert result == {
        "collapsed": {"total": 60, "items": [{"id": 0}], "page": 1, "totalPages": 1},
        "expanded": {
            "total": 60,
            "items": [{"id": index} for index in range(10)],
            "page": 6,
            "totalPages": 6,
        },
        "paths": [
            "/image-processing/runs/history?limit=1&offset=0&batch_id=batch-1",
            "/image-processing/runs/history?limit=10&offset=50&batch_id=batch-1",
        ],
    }
