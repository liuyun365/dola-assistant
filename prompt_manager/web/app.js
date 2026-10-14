'use strict';

const $ = (sel) => document.querySelector(sel);

const state = {
  currentFile: null,
  shots: [],
  assets: [],
  assetNames: [],
  nameToImage: {},     // 资产名 -> 图片path
  shotRefs: {},        // 分镜index -> [资产名]
  mapping: {},         // 分镜index -> [图片path]
  instances: [],
  instance: localStorage.getItem('pm_instance') || '',
  shotInstances: {},   // 分镜index -> 实例id（覆盖全局）
  roots: [],
  drives: [],
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), 2000);
}

async function api(method, path, body) {
  const opt = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opt.body = JSON.stringify(body);
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((data && data.error) || r.status);
  return data;
}

// ---------------------------------------------------------------- 实例
function populateInstanceSelect(sel, selectedVal) {
  sel.innerHTML = '';
  const list = state.instances || [];
  if (!list.length) {
    sel.innerHTML = '<option value="">（无可用实例）</option>';
    return;
  }
  list.forEach(it => {
    const o = document.createElement('option');
    o.value = it.id;
    o.textContent = `${it.id}${it.name ? ' (' + it.name + ')' : ''}${it.current ? ' ◀当前' : ''}${it.running ? '' : ' [未运行]'}`;
    sel.appendChild(o);
  });
  if (selectedVal) sel.value = selectedVal;
}

async function loadInstances() {
  try {
    const d = await api('GET', '/api/instances');
    const sel = $('#instanceSel');
    if (d.instances && d.instances.error) {
      state.instances = [];
      sel.innerHTML = '<option value="">豆啦啦未连接（请先打开豆啦啦客户端，再点"重试连接"）</option>';
      return;
    }
    state.instances = d.instances || [];
    populateInstanceSelect(sel, state.instance);
  } catch (e) {
    state.instances = [];
    $('#instanceSel').innerHTML = '<option value="">连接失败（点"重试连接"）</option>';
  }
}

// 手动重试连接豆啦啦（"豆啦啦未连接"时，确认客户端已开后点此刷新实例列表）
$('#btnReloadInst').addEventListener('click', async () => {
  const sel = $('#instanceSel');
  sel.innerHTML = '<option value="">连接中…</option>';
  await loadInstances();
  if ((state.instances || []).length) {
    toast('已连接豆啦啦，实例列表已刷新');
  } else {
    toast('仍未连上：请确认豆啦啦客户端已打开，且至少登录并打开一个实例');
  }
});

$('#instanceSel').addEventListener('change', () => {
  state.instance = $('#instanceSel').value;
  localStorage.setItem('pm_instance', state.instance);
  // 全局实例变更：各分镜实例跟随（清除单独覆盖）
  state.shotInstances = {};
  document.querySelectorAll('.shot-inst').forEach(sel => { sel.value = state.instance; });
});

// ---------------------------------------------------------------- 文档树
async function loadRoots() {
  const d = await api('GET', '/api/roots');
  state.roots = d.roots || [];
  const tree = $('#tree');
  tree.innerHTML = '';
  const roots = state.roots;
  $('#rootCount').textContent = roots.length ? `(${roots.length})` : '';
  if (!roots.length) {
    tree.innerHTML = '<div class="tree-empty">尚未添加文件夹/文件。<br>点顶部「+ 添加文件夹」或「+ 添加文件」。</div>';
    return;
  }
  for (const r of roots) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    const row = document.createElement('div');
    row.className = 'tree-row';
    const isDir = r.type === 'folder';
    row.innerHTML = `<span class="twist">${isDir ? '▸' : ''}</span>`
      + `<span class="ico">${isDir ? '📁' : '📄'}</span>`
      + `<span class="label"></span>`
      + `<span class="rm" title="移除">×</span>`;
    row.querySelector('.label').textContent = r.path;
    node.appendChild(row);
    tree.appendChild(node);

    row.querySelector('.rm').addEventListener('click', async (ev) => {
      ev.stopPropagation();
      await api('DELETE', '/api/roots?path=' + encodeURIComponent(r.path));
      loadRoots();
    });

    if (isDir) {
      let loaded = false, open = false;
      const childBox = document.createElement('div');
      childBox.className = 'tree-children';
      childBox.style.display = 'none';
      node.appendChild(childBox);
      row.addEventListener('click', async () => {
        open = !open;
        row.querySelector('.twist').textContent = open ? '▾' : '▸';
        childBox.style.display = open ? 'block' : 'none';
        if (open && !loaded) { loaded = true; await listDir(r.path, childBox); }
      });
    } else {
      row.addEventListener('click', () => {
        document.querySelectorAll('.tree-row').forEach(x => x.classList.remove('active'));
        row.classList.add('active');
        openFile(r.path);
      });
    }
  }
}

async function listDir(path, box) {
  box.innerHTML = '<div class="tree-empty">加载中…</div>';
  try {
    const d = await api('GET', '/api/list?path=' + encodeURIComponent(path));
    box.innerHTML = '';
    if (!d.children || !d.children.length) { box.innerHTML = '<div class="tree-empty">空文件夹</div>'; return; }
    for (const c of d.children) {
      const node = document.createElement('div');
      node.className = 'tree-node';
      const row = document.createElement('div');
      row.className = 'tree-row';
      row.innerHTML = `<span class="twist">${c.type === 'dir' ? '▸' : ''}</span>`
        + `<span class="ico">${c.type === 'dir' ? '📁' : (c.kind === 'image' ? '🖼️' : '📄')}</span>`
        + `<span class="label"></span>`;
      row.querySelector('.label').textContent = c.name;
      node.appendChild(row);
      box.appendChild(node);
      if (c.type === 'dir') {
        let loaded = false, open = false;
        const cb = document.createElement('div');
        cb.className = 'tree-children'; cb.style.display = 'none';
        node.appendChild(cb);
        row.addEventListener('click', async () => {
          open = !open;
          row.querySelector('.twist').textContent = open ? '▾' : '▸';
          cb.style.display = open ? 'block' : 'none';
          if (open && !loaded) { loaded = true; await listDir(c.path, cb); }
        });
      } else if (c.kind === 'text') {
        row.addEventListener('click', () => {
          document.querySelectorAll('.tree-row').forEach(x => x.classList.remove('active'));
          row.classList.add('active');
          openFile(c.path);
        });
      }
    }
  } catch (e) {
    box.innerHTML = '<div class="tree-empty">读取失败：' + e.message + '</div>';
  }
}

async function addRoot(path, type) {
  try {
    await api('POST', '/api/roots', { path: path.trim(), type });
    toast('已添加');
    loadRoots();
  } catch (e) { toast('添加失败：' + e.message); }
}

// ---------------------------------------------------------------- 可视化选择器
const picker = { mode: 'folder', onPick: null, current: '', selected: null, checked: new Set() };

function pickerModeInfo() {
  if (picker.mode === 'folder') return { title: '选择文件夹', ok: '选择此文件夹', hint: '单击文件夹选中（高亮），双击进入；确认请点「选择此文件夹」。' };
  if (picker.mode === 'file') return { title: '选择文件', ok: '选择此文件', hint: '双击文件夹进入；单击文件选中后点「选择此文件」。' };
  return { title: '选择图片（可多选）', ok: '导入选中', hint: '双击文件夹进入；勾选多张图片后点「导入选中」。' };
}

function parentDir(p) {
  if (!p) return '';
  if (/^[A-Za-z]:\\?$/.test(p)) return '';
  const norm = p.replace(/\/+$/, '').replace(/\\+$/, '');
  const i = Math.max(norm.lastIndexOf('\\'), norm.lastIndexOf('/'));
  if (i <= 0) return '';
  let res = norm.slice(0, i);
  if (/^[A-Za-z]:$/.test(res)) res += '\\';
  return res;
}

async function openPicker(mode, onPick) {
  picker.mode = mode; picker.onPick = onPick; picker.selected = null; picker.checked = new Set();
  const info = pickerModeInfo();
  $('#pickerTitle').textContent = info.title;
  $('#pickerOk').textContent = info.ok;
  $('#pickerFoot').textContent = info.hint;
  let drives = [];
  try { drives = (await api('GET', '/api/drives')).drives || []; } catch (e) { drives = []; }
  state.drives = drives;
  const ds = $('#pickerDrives'); ds.innerHTML = '';
  drives.forEach(d => { const o = document.createElement('option'); o.value = d.path; o.textContent = d.name; ds.appendChild(o); });
  const saved = localStorage.getItem('pm_picker_last_dir');
  let start = saved || state.currentFile || (state.roots[0] && state.roots[0].path) || (drives[0] && drives[0].path) || 'C:\\';
  if (/^[A-Za-z]:$/.test(start)) start += '\\';
  const initDir = parentDir(start) || start;
  if (initDir) await navigate(initDir);
  else showRoot();
  $('#pickerModal').classList.remove('hidden');
}

function showRoot() {
  picker.current = '';
  $('#pickerDrives').value = '';
  const body = $('#pickerBody');
  body.innerHTML = '';
  const drives = state.drives || [];
  if (!drives.length) { body.innerHTML = '<div class="tree-empty">未检测到驱动器</div>'; return; }
  drives.forEach(d => {
    const row = document.createElement('div');
    row.className = 'pk-row';
    row.innerHTML = `<span class="pk-ico">💾</span><span class="pk-name"></span>`;
    row.querySelector('.pk-name').textContent = d.name;
    row.addEventListener('click', () => {
      document.querySelectorAll('.pk-row').forEach(x => x.classList.remove('sel'));
      row.classList.add('sel'); picker.selected = d.path;
    });
    row.addEventListener('dblclick', () => navigate(d.path));
    body.appendChild(row);
  });
}

async function navigate(path) {
  if (!path) return;
  picker.current = path;
  const ds = $('#pickerDrives');
  for (const o of ds.options) { if (path.startsWith(o.value)) { ds.value = o.value; break; } }
  const body = $('#pickerBody');
  body.innerHTML = '<div class="tree-empty">加载中…</div>';
  let d;
  try { d = await api('GET', '/api/list?path=' + encodeURIComponent(path)); }
  catch (e) { body.innerHTML = '<div class="tree-empty">读取失败：' + e.message + '</div>'; return; }
  if (d.children === null) { body.innerHTML = '<div class="tree-empty">目录不存在</div>'; return; }
  const children = d.children || [];
  body.innerHTML = '';
  if (!children.length) { body.innerHTML = '<div class="tree-empty">空文件夹</div>'; return; }
  children.forEach(c => {
    if (c.type !== 'dir') {
      if (picker.mode === 'folder') return;
      if (picker.mode === 'file' && c.kind !== 'text') return;
      if (picker.mode === 'images' && c.kind !== 'image') return;
    }
    const row = document.createElement('div');
    row.className = 'pk-row';
    const isImg = c.kind === 'image';
    row.innerHTML = `<span class="pk-ico">${c.type === 'dir' ? '📁' : (isImg ? '🖼️' : '📄')}</span>`
      + `<span class="pk-name"></span>`
      + (picker.mode === 'images' && isImg ? `<input type="checkbox" class="pk-chk">` : '');
    row.querySelector('.pk-name').textContent = c.name;
    const chk = row.querySelector('.pk-chk');
    if (chk) {
      chk.addEventListener('click', ev => ev.stopPropagation());
      chk.addEventListener('change', () => {
        if (chk.checked) picker.checked.add(c.path); else picker.checked.delete(c.path);
        row.classList.toggle('sel', chk.checked);
        updatePickerCount();
      });
    }
    row.addEventListener('click', () => {
      if (c.type === 'dir') {
        if (picker.mode === 'images') { navigate(c.path); return; }
        document.querySelectorAll('.pk-row').forEach(x => x.classList.remove('sel'));
        row.classList.add('sel'); picker.selected = c.path; return;
      }
      if (picker.mode === 'images') {
        const on = !picker.checked.has(c.path);
        if (on) picker.checked.add(c.path); else picker.checked.delete(c.path);
        chk.checked = on; row.classList.toggle('sel', on); updatePickerCount(); return;
      }
      document.querySelectorAll('.pk-row').forEach(x => x.classList.remove('sel'));
      row.classList.add('sel'); picker.selected = c.path;
    });
    row.addEventListener('dblclick', () => { if (c.type === 'dir') navigate(c.path); });
    body.appendChild(row);
  });
}

function updatePickerCount() {
  if (picker.mode === 'images') $('#pickerFoot').textContent = `已选 ${picker.checked.size} 张`;
}

function closePicker() { $('#pickerModal').classList.add('hidden'); }

$('#pickerCancel').addEventListener('click', closePicker);
$('#pickerUp').addEventListener('click', () => {
  const p = parentDir(picker.current);
  if (p) navigate(p);
  else showRoot();
});
$('#pickerDrives').addEventListener('change', () => navigate($('#pickerDrives').value));
$('#pickerOk').addEventListener('click', () => {
  const m = picker.mode;
  if (m === 'folder') {
    // 未单独选中子文件夹时，默认导入当前所在文件夹
    const target = picker.selected || picker.current;
    if (!target) { toast('请选择文件夹'); return; }
    localStorage.setItem('pm_picker_last_dir', target);
    picker.onPick && picker.onPick(target, 'folder');
  } else if (m === 'file') {
    if (!picker.selected) { toast('请选择文件'); return; }
    localStorage.setItem('pm_picker_last_dir', parentDir(picker.selected) || picker.selected);
    picker.onPick && picker.onPick(picker.selected, 'file');
  } else {
    if (!picker.checked.size) { toast('请勾选图片'); return; }
    localStorage.setItem('pm_picker_last_dir', picker.current);
    picker.onPick && picker.onPick(Array.from(picker.checked), 'images');
  }
  closePicker();
});

$('#btnAddFolder').addEventListener('click', () => openPicker('folder', (p) => addRoot(p, 'folder')));
$('#btnAddFile').addEventListener('click', () => openPicker('file', (p) => addRoot(p, 'file')));

// ---------------------------------------------------------------- 打开文件 / 分镜
async function applyFileData(d) {
  state.shots = d.shots || [];
  state.assetNames = d.asset_names || [];
  state.nameToImage = d.name_to_image || {};
  state.shotRefs = d.shot_refs || {};
  state.shotInstances = {};
  applyNameImage();
  renderShots();
  renderMatchList();
}

async function openFile(path) {
  if (hasUnsaved() && !confirm('当前文件有未保存的修改，切换后将丢失。\n确定放弃修改并切换文件？')) return;
  state.currentFile = path;
  $('#midTitle').textContent = path.split(/[\\/]/).pop();
  const box = $('#shots');
  box.innerHTML = '<div class="center-msg">解析中…</div>';
  try {
    const d = await api('GET', '/api/file?path=' + encodeURIComponent(path));
    await applyFileData(d);
  } catch (e) {
    box.innerHTML = '<div class="center-msg">读取失败：' + e.message + '</div>';
  }
}

// 用「当前」资产库重新计算匹配（先加资产后开提示词、或想刷新时）
async function refreshMatch() {
  if (!state.currentFile) { toast('请先打开提示词文件'); return; }
  if (hasUnsaved() && !confirm('当前文件有未保存的修改，重新匹配会丢弃这些修改。\n确定继续？')) return;
  try {
    const d = await api('GET', '/api/file?path=' + encodeURIComponent(state.currentFile));
    await applyFileData(d);
    toast('已按当前资产库重新匹配');
  } catch (e) { toast('重新匹配失败：' + e.message); }
}
$('#btnRematch').addEventListener('click', refreshMatch);

function applyNameImage() {
  state.mapping = {};
  for (const s of state.shots) {
    const refs = state.shotRefs[s.index] || [];
    const imgs = [];
    for (const n of refs) { const p = state.nameToImage[n]; if (p && !imgs.includes(p)) imgs.push(p); }
    state.mapping[s.index] = imgs;
  }
}

function renderShots() {
  const box = $('#shots');
  box.innerHTML = '';
  if (!state.shots.length) { box.innerHTML = '<div class="center-msg">未识别到分镜。</div>'; return; }
  state.shots.forEach(s => {
    const el = document.createElement('div');
    el.className = 'shot';
    el.dataset.idx = s.index;
    const assetChips = (state.mapping[s.index] || []).map(p =>
      `<span class="chip">${esc(p.split(/[\\/]/).pop())}</span>`).join('');
    el.innerHTML = `
      <div class="shot-head">
        <span class="idx">#${s.index}</span>
        <span class="ttl"></span>
        <span class="spacer"></span>
        <label class="inst-lbl">实例</label>
        <select class="shot-inst"></select>
        <button class="ghost copyBtn">复制</button>
        <button class="primary pushBtn">推送</button>
      </div>
      <div class="shot-body" contenteditable="false"></div>
      <div class="shot-foot">
        <span class="hint">资产：</span>
        <span class="shot-assets">${assetChips}</span>
        <span class="spacer"></span>
        <button class="ghost saveBtn" title="把修改后的提示词写回原文件（只覆盖本分镜）">保存</button>
        <button class="ghost editBtn">编辑</button>
      </div>`;
    el.querySelector('.ttl').textContent = s.title || (`分镜 ${s.index}`);
    el.querySelector('.shot-body').textContent = s.body || s.text;
    const instSel = el.querySelector('.shot-inst');
    populateInstanceSelect(instSel, state.shotInstances[s.index] || state.instance);
    instSel.addEventListener('change', () => { state.shotInstances[s.index] = instSel.value; });
    el.querySelector('.copyBtn').addEventListener('click', () => copyText(s.text));
    el.querySelector('.pushBtn').addEventListener('click', () => pushShot(s));
    const body = el.querySelector('.shot-body');
    el.querySelector('.editBtn').addEventListener('click', (ev) => {
      const b = ev.target;
      const on = body.getAttribute('contenteditable') === 'true';
      body.setAttribute('contenteditable', on ? 'false' : 'true');
      b.textContent = on ? '编辑' : '完成';
      if (!on) body.focus();
    });
    // 编辑即时生效：一边改一边同步到 state，推送/推送全部用的就是最新文本
    body.addEventListener('input', () => {
      const t = (body.innerText || '').replace(/\n+$/, '');
      s.body = t;
      s.text = (s.title ? s.title + '\n' : '') + t;
      setDirty(s, true);
    });
    // 粘贴按纯文本处理，避免把网页/文档的样式带进提示词
    body.addEventListener('paste', (ev) => {
      ev.preventDefault();
      const t = (ev.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, t);
    });
    // 编辑中 Ctrl+S / Cmd+S 直接保存本分镜
    body.addEventListener('keydown', (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && (ev.key === 's' || ev.key === 'S')) {
        ev.preventDefault();
        saveShot(s, el);
      }
    });
    el.querySelector('.saveBtn').addEventListener('click', () => saveShot(s, el));
    box.appendChild(el);
  });
}

// ---------------------------------------------------------------- 编辑保存
function hasUnsaved() {
  return state.shots.some(s => s._dirty);
}

function setDirty(s, on) {
  s._dirty = !!on;
  const el = document.querySelector('.shot[data-idx="' + s.index + '"]');
  if (el) el.classList.toggle('dirty', !!on);
}

async function saveShot(s, el) {
  if (!state.currentFile) { toast('请先打开提示词文件'); return; }
  const body = el.querySelector('.shot-body');
  const bodyText = (body.innerText || '').replace(/\n+$/, '');
  const text = (s.title ? s.title + '\n' : '') + bodyText;
  if (!text.trim()) { toast('内容为空，未保存'); return; }
  const btn = el.querySelector('.saveBtn');
  const old = btn.textContent;
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    await api('POST', '/api/file/save', { path: state.currentFile, index: s.index, text });
    s.body = bodyText; s.text = text;
    setDirty(s, false);
    toast('已保存到文件：' + state.currentFile.split(/[\\/]/).pop());
  } catch (e) {
    toast('保存失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = old;
  }
}

// 关闭/刷新页面前，有未保存修改时提醒
window.addEventListener('beforeunload', (ev) => {
  if (hasUnsaved()) { ev.preventDefault(); ev.returnValue = ''; }
});

function refreshShotAssets() {
  document.querySelectorAll('.shot').forEach(el => {
    const idx = +el.dataset.idx;
    const box = el.querySelector('.shot-assets');
    if (!box) return;
    box.innerHTML = (state.mapping[idx] || []).map(p =>
      `<span class="chip">${esc(p.split(/[\\/]/).pop())}</span>`).join('');
  });
}

function copyText(txt) {
  navigator.clipboard.writeText(txt).then(
    () => toast('已复制'),
    () => toast('复制失败，请手动选择')
  );
}

async function pushShot(s) {
  const inst = state.shotInstances[s.index] || state.instance;
  if (!inst) { toast('请先选择豆啦啦实例'); return; }
  const assets = state.mapping[s.index] || [];
  const btn = event && event.target;
  const old = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '推送中…'; }
  try {
    const r = await api('POST', '/api/push', {
      instance: inst, text: s.text, assets, send: $('#autoSend').checked,
    });
    toast(r.sent ? '已填入并发送' : '已填入聊天框');
  } catch (e) {
    toast('推送失败：' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

// ---------------------------------------------------------------- 推送全部（按可用实例顺序轮询）
async function pushAll() {
  if (!state.shots.length) { toast('没有可推送的分镜'); return; }
  // 可用实例 = 正在运行的实例（按列表顺序）
  const available = (state.instances || []).filter(i => i.running);
  if (!available.length) { openInstanceDialog(0); return; }
  await pushAllFrom(0, available);
}

async function pushAllFrom(startIdx, available) {
  const send = $('#autoSend').checked;
  for (let i = startIdx; i < state.shots.length; i++) {
    const s = state.shots[i];
    // 按顺序轮询：分镜 i -> 第 (i mod N) 个可用实例
    const inst = available[i % available.length];
    try {
      await api('POST', '/api/push', {
        instance: inst.id, text: s.text,
        assets: state.mapping[s.index] || [], send,
      });
    } catch (e) {
      // 推送失败（输入框未聚焦 / 实例不可用 / 豆啦啦未连接）→ 弹窗让用户决定
      const msg = (e && e.message) || String(e);
      if (msg.includes('输入框') || msg.includes('前台') || msg.includes('聚焦')) {
        openInstanceDialog(i,
          `豆啦啦输入框未聚焦，${s ? '分镜 #' + s.index : '该分镜'} 推送失败。` +
          `请切到豆啦啦窗口、点一下聊天输入框，然后点下方"我已增加实例后继续"从此分镜重试。`);
      } else {
        openInstanceDialog(i);
      }
      return;
    }
  }
  toast('全部推送完成');
}

// 无可用实例 / 推送失败 时的对话框：暂停 或 我已增加实例后继续
function openInstanceDialog(resumeIdx, customMsg) {
  const s = state.shots[resumeIdx];
  const label = s ? `#${s.index}（${s.title || '分镜' + s.index}）` : '剩余分镜';
  $('#instDialogMsg').textContent = customMsg ||
    `无可用的豆啦啦实例，或 ${label} 推送失败。请选择操作：`;
  $('#instDialog').classList.remove('hidden');
  $('#instPause').onclick = () => {
    $('#instDialog').classList.add('hidden');
    toast('已暂停推送（项目未停止，可稍后重试）');
  };
  $('#instResume').onclick = async () => {
    $('#instDialog').classList.add('hidden');
    await loadInstances();
    const avail = (state.instances || []).filter(i => i.running);
    if (!avail.length) { toast('仍未检测到可用实例'); openInstanceDialog(resumeIdx); return; }
    await pushAllFrom(resumeIdx, avail);
  };
}
$('#btnPushAll').addEventListener('click', pushAll);

// ---------------------------------------------------------------- 资产库（渐进懒加载）
let _assetObserver = null;

async function loadAssets() {
  const d = await api('GET', '/api/assets');
  state.assets = d.assets || [];
  const grid = $('#assetGrid');
  grid.innerHTML = '';
  if (_assetObserver) { _assetObserver.disconnect(); _assetObserver = null; }
  if (!state.assets.length) { grid.innerHTML = '<div class="hint">尚未导入资产。点上方「导入图片」或「导入文件夹」。</div>'; return; }

  // 先放占位，进入视口后才赋值 src —— 避免一次性导入大量图片时卡顿
  _assetObserver = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        const img = e.target.querySelector('img');
        if (img && !img.getAttribute('src')) img.src = img.dataset.path;
        _assetObserver.unobserve(e.target);
      }
    });
  }, { root: grid, rootMargin: '160px' });

  state.assets.forEach(a => {
    const item = document.createElement('div');
    item.className = 'asset-item loading';
    item.innerHTML = `<div class="ph">图</div>`
      + `<img data-path="/api/asset?path=${encodeURIComponent(a.path)}" alt="${esc(a.name)}" style="opacity:0">`
      + `<span class="nm"></span>`
      + `<button class="del" title="移除">×</button>`;
    item.querySelector('.nm').textContent = a.name;
    const img = item.querySelector('img');
    img.addEventListener('load', () => {
      img.style.opacity = '1';
      item.classList.remove('loading');
      const ph = item.querySelector('.ph'); if (ph) ph.remove();
    });
    img.addEventListener('error', () => {
      item.classList.add('broken');
      img.style.opacity = '1';
      const ph = item.querySelector('.ph'); if (ph) ph.remove();
    });
    item.querySelector('.del').addEventListener('click', async () => {
      await api('DELETE', '/api/assets?path=' + encodeURIComponent(a.path));
      loadAssets(); renderMatchList();
    });
    grid.appendChild(item);
    _assetObserver.observe(item);
  });
}

async function importAssetPaths(paths) {
  try {
    const r = await api('POST', '/api/assets', { paths });
    const n = (r && r.imported) || 0;
    if (!n) toast('该文件夹内未找到图片（仅识别 png/jpg/webp 等图片格式）');
    else toast(`已导入 ${n} 张资产（共 ${r.assets.length}）`);
    await loadAssets();
    // 若已打开提示词，则按新资产库重新算匹配（解决"先加资产后开提示词"匹配不全）
    if (state.currentFile) await refreshMatch();
    else renderMatchList();
  } catch (e) { toast('导入失败：' + e.message); }
}

// 清空全部已选资产
$('#btnClearAssets').addEventListener('click', async () => {
  if (!state.assets.length) { toast('资产库已为空'); return; }
  if (!confirm('确定清空全部已选资产？')) return;
  try {
    await api('DELETE', '/api/assets');
    await loadAssets();
    if (state.currentFile) await refreshMatch();
    else renderMatchList();
    toast('已清空资产库');
  } catch (e) { toast('清空失败：' + e.message); }
});

$('#btnImportImages').addEventListener('click', () => openPicker('images', (paths) => importAssetPaths(paths)));
$('#btnImportFolder').addEventListener('click', () => openPicker('folder', (p) => importAssetPaths([p])));

// ---------------------------------------------------------------- 资产匹配（资产名 -> 图）
function renderMatchList() {
  const box = $('#matchList');
  box.innerHTML = '';
  if (!state.shots.length) {
    box.innerHTML = '<div class="hint">打开提示词文件后，此处按资产名列出匹配。</div>';
    return;
  }
  if (!state.assetNames.length) {
    box.innerHTML = '<div class="hint">未从提示词中识别到资产名。请确认提示词含「图一：角色名」这类写法（仅「图N」开头的行纳入资产，其余由 AI 生成），或在资产库导入图片后点「重新匹配」。</div>';
    return;
  }
  state.assetNames.forEach(name => {
    const row = document.createElement('div');
    row.className = 'match-row';
    const cur = state.nameToImage[name] || '';
    const opts = ['<option value="">— 未匹配 —</option>'].concat(
      state.assets.map(a => `<option value="${esc(a.path)}" ${a.path === cur ? 'selected' : ''}>${esc(a.name)}</option>`)
    );
    row.innerHTML = `<div class="mr-name"></div><div class="mr-arrow">→</div><select class="mr-select">${opts.join('')}</select>`;
    row.querySelector('.mr-name').textContent = name;
    const sel = row.querySelector('.mr-select');
    sel.addEventListener('change', () => {
      state.nameToImage[name] = sel.value || null;
      applyNameImage();
      refreshShotAssets();
    });
    box.appendChild(row);
  });
}

async function submitMatch() {
  if (!state.currentFile) { toast('请先打开提示词文件'); return; }
  try {
    const r = await api('POST', '/api/match', { path: state.currentFile, name_to_image: state.nameToImage });
    state.mapping = r.mapping || state.mapping;
    refreshShotAssets();
    toast('匹配已保存');
  } catch (e) { toast('保存失败：' + e.message); }
}
$('#btnSubmitMatch').addEventListener('click', submitMatch);

// ---------------------------------------------------------------- 启动
loadInstances();
loadRoots();
loadAssets();
renderMatchList();

// 显示服务端版本，方便确认是否跑到了新代码
(async () => {
  try {
    const d = await api('GET', '/api/version');
    const t = document.getElementById('verTag');
    if (t && d && d.version) t.textContent = 'v' + d.version.split('.').pop();
  } catch (e) { /* ignore */ }
})();
