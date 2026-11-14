(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ZhijuDramaPackages = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const text = (value, missing = '暂无产物') => value ? `<div class="drama-package-text">${esc(value)}</div>` : `<p class="drama-package-missing">${missing}</p>`;
  const current = (rows, key) => [...new Map([...rows].reverse().map(row => [key(row), row])).values()];
  function identity(record) {
    return `<strong>${esc(record.channel_name)}</strong>${record.channel_operational_name && record.channel_operational_name !== record.channel_name ? `<span>${esc(record.channel_operational_name)}</span>` : ''}<span>${esc(record.language_name || record.language || '语言未登记')} · ${esc(record.production_date)} · 包版本 ${record.version_number}</span>`;
  }
  function renderHistory(data, selected, statusLabel) {
    const rows = data.items.map(record => `<tr><td><input type="checkbox" data-drama-package-select="${esc(record.package_id)}" aria-label="选择 ${esc(record.channel_name)} ${esc(record.production_date)} 包版本 ${record.version_number}" ${selected.has(record.package_id) ? 'checked' : ''}></td><td class="drama-package-identity">${identity(record)}</td><td>${esc(statusLabel(record.status))}</td><td><button class="button button-secondary button-small" data-action="drama-package-open" data-id="${esc(record.package_id)}">打开运营包</button></td></tr>`).join('');
    return `<div class="drama-package-view"><div class="drama-package-summary"><div><h3>${esc(data.drama_name)}</h3><span class="cell-sub mono">${esc(data.drama_code)}</span><p>${data.channel_count} 个频道 · ${data.package_count} 个已生产运营包 · 全部生产日期</p></div></div>${rows ? `<div class="drama-package-tools"><span id="dramaPackageSelectedCount">已选 ${selected.size} 个运营包</span><button id="dramaPackageCompare" class="button button-primary" data-action="drama-package-compare" ${selected.size < 2 ? 'disabled' : ''}>并排对比</button></div><div class="table-wrap"><table class="data-table drama-package-records"><thead><tr><th>选择</th><th>频道 / 生产日期 / 包版本</th><th>状态</th><th></th></tr></thead><tbody>${rows}</tbody></table></div><p class="field-help">选择同剧不同频道或日期的运营包进行对比；同一工单的历史包版本分别保留。已有部分产物的包按实际状态显示。</p>` : '<div class="empty-state"><h3>尚未生产运营包</h3><p>这部剧目前没有可查看的运营包产物。</p></div>'}</div>`;
  }
  function image(assetId, title) {
    if (!assetId) return '<p class="drama-package-missing">尚未关联封面图片</p>';
    const path = `/api/v3/media-assets/${encodeURIComponent(assetId)}`;
    return `<a class="drama-package-image-link" href="${path}/content" target="_blank" rel="noopener"><img class="drama-package-image" src="${path}/thumbnail" alt="${esc(title)}" loading="lazy"><span class="drama-package-missing" hidden>图片暂不可读取</span></a>`;
  }
  function renderDetails(history, details, statusLabel) {
    const models = details.map(({record, outputs}) => ({record, outputs,
      titles: current(outputs.titles || [], row => row.variant_number),
      covers: current(outputs.covers || [], row => `${row.title_id}:${row.aspect_ratio}`),
      community: current(outputs.community_posts || [], row => row.sequence_number)}));
    const cells = [];
    for (const model of models) cells.push(`<header class="drama-package-compare-head drama-package-identity">${identity(model.record)}<span>${esc(statusLabel(model.record.status))}</span></header>`);
    for (const number of [1, 2, 3]) {
      for (const model of models) {
        const title = model.titles.find(row => row.variant_number === number);
        cells.push(`<section class="drama-package-compare-cell"><h4>标题 ${['A','B','C'][number-1]}</h4>${text(title?.localized_title, '标题尚未生成')}<h5>中文参考</h5>${text(title?.chinese_translation, '暂无中文参考')}<h5>核心词 / 卖点</h5>${text(title?.core_phrase, '暂无记录')}</section>`);
      }
      for (const model of models) {
        const title = model.titles.find(row => row.variant_number === number);
        const covers = model.covers.filter(row => title && row.title_id === title.id).sort((a,b) => a.aspect_ratio.localeCompare(b.aspect_ratio));
        cells.push(`<section class="drama-package-compare-cell"><h4>标题 ${['A','B','C'][number-1]} 对应封面</h4>${covers.length ? covers.map(cover => `<h5>${esc(cover.aspect_ratio)} 提示词</h5>${text(cover.creative_prompt)}${image(cover.asset_id, `标题${number}对应封面`)}`).join('') : '<p class="drama-package-missing">暂无当前标题对应的封面</p>'}</section>`);
      }
    }
    for (const model of models) {
      const description = model.outputs.descriptions?.[0];
      cells.push(`<section class="drama-package-compare-cell"><h4>说明</h4>${text(description?.localized_text)}<h5>中文参考</h5>${text(description?.chinese_translation, '暂无中文参考')}</section>`);
    }
    for (const model of models) cells.push(`<section class="drama-package-compare-cell"><h4>社群</h4>${model.community.length ? model.community.sort((a,b)=>a.sequence_number-b.sequence_number).map(post => `<h5>社群 ${post.sequence_number}</h5>${text(post.localized_text)}<h5>中文参考</h5>${text(post.chinese_translation, '暂无中文参考')}<h5>图片提示词</h5>${text(post.image_prompt)}${post.asset_ids?.length ? post.asset_ids.map(id => image(id, `社群${post.sequence_number}图片`)).join('') : '<p class="drama-package-missing">尚未关联社群图片</p>'}`).join('') : '<p class="drama-package-missing">暂无社群产物</p>'}</section>`);
    return `<div class="drama-package-view"><div class="drama-package-tools"><button class="button button-secondary" data-action="drama-package-back">返回运营包记录</button><span>${esc(history.drama_name)} · ${details.length > 1 ? `${details.length} 个包并排对比` : '运营包详情'}</span></div><p class="field-help">展示各包当前产物；封面按对应标题绑定，未生成或未关联的内容单独标明。</p><div class="drama-package-comparison"><div class="drama-package-compare-grid" style="--package-columns:${details.length}">${cells.join('')}</div></div></div>`;
  }
  return {renderHistory, renderDetails};
});
