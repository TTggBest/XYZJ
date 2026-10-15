import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from zhiju.services.country_catalog import list_country_options


def test_french_channel_import_recommends_french_and_list_labels_it_in_chinese():
    root = Path(__file__).resolve().parents[2]
    program = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1] + '/assets/app.js', 'utf8');
const labels = source.slice(source.indexOf('  const languageNames ='), source.indexOf('  function channelIdentity('));
const form = source.slice(source.indexOf('  function youtubeChannelImportForm('), source.indexOf('  async function openYouTubeChannelImport('));
const context = {esc: value => String(value ?? ''), icon: () => ''};
vm.createContext(context);
vm.runInContext(labels + form, context);
const html = context.youtubeChannelImportForm({
  candidates: [{id:'french-channel', title:'Ella Vuelve y Vence', youtube_channel_id:'UC-french', youtube_country_code:'FR', youtube_default_language:null}],
  countries: JSON.parse(process.argv[2])
});
assert.match(html, /value="FR" selected/);
assert.match(html, /data-import-language value="fr"/);
assert.match(html, /data-import-timezone value="Europe\/Paris"/);
assert.equal(context.languageLabel('fr'), '法语（fr）');
assert.equal(context.languageLabel('en'), '英语（en）');
"""
    result = subprocess.run(
        ["node", "-e", program, str(root), json.dumps([asdict(c) for c in list_country_options()])],
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
