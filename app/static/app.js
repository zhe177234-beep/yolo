const $ = id => document.getElementById(id);
const state = {file: null, job: null, poll: null, previewUrl: null};
const labels = {queued: '排队中', running: '检测中', completed: '已完成', failed: '失败'};
const classNames = {person:'行人', car:'汽车', bus:'公交车', truck:'卡车', bicycle:'自行车', motorcycle:'摩托车'};
const scenarios = {all:'识别画面中的全部 COCO 目标类别。', traffic:'聚焦行人、自行车、汽车、摩托车、公交车和卡车。', people:'仅识别画面中的行人目标。'};
let toastTimer;
function setBusy(busy) {
  $('run').disabled = busy;
  $('demo').disabled = busy;
  $('run-label').textContent = busy ? '正在检测…' : '开始检测';
}
function toast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').hidden = true, 6000);
}
async function api(path, options = {}) {
  options.headers = {...options.headers, 'X-API-Key': $('api-key').value};
  const response = await fetch(path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `请求失败 (${response.status})`);
  }
  return response;
}
function selectFile(file) {
  if (!file) return;
  state.file = file;
  $('file-label').textContent = file.name;
  $('file-detail').textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · 点击可重新选择`;
}
$('file').addEventListener('change', event => selectFile(event.target.files[0]));
$('preset').addEventListener('change', () => $('preset-description').textContent = scenarios[$('preset').value]);
$('fit').addEventListener('click', () => {
  $('viewer').querySelector('img')?.style.setProperty('object-fit', 'contain');
  toast('画面已完整适应预览区域');
});
$('fullscreen').addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector('.stage').requestFullscreen();
  } catch {toast('当前浏览器不支持全屏，可下载标注文件查看完整画面');}
});
$('demo').addEventListener('click', async () => {
  try {
    const response = await fetch('/sample-bus.jpg');
    if (!response.ok) throw new Error('示例文件加载失败');
    selectFile(new File([await response.blob()], 'sample-bus.jpg', {type:'image/jpeg'}));
    $('preset').value = 'traffic';
    $('preset-description').textContent = scenarios.traffic;
    await startDetection();
  } catch (error) {toast(error.message);}
});
$('dropzone').addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); $('file').click();}
});
['dragenter', 'dragover'].forEach(type => $('dropzone').addEventListener(type, event => {
  event.preventDefault(); $('dropzone').classList.add('drag');
}));
['dragleave', 'drop'].forEach(type => $('dropzone').addEventListener(type, event => {
  event.preventDefault(); $('dropzone').classList.remove('drag');
}));
$('dropzone').addEventListener('drop', event => selectFile(event.dataTransfer.files[0]));
$('confidence').addEventListener('input', () => $('confidence-label').textContent = Number($('confidence').value).toFixed(2));
$('api-key').value = sessionStorage.getItem('yolo-key') || '';
$('api-key').addEventListener('change', () => {
  sessionStorage.setItem('yolo-key', $('api-key').value); history();
});
function stopPoll() {clearTimeout(state.poll); state.poll = null;}
function resetMetrics() {
  ['total', 'classes', 'elapsed', 'resolution'].forEach(id => $(id).textContent = '—');
  $('total-label').textContent = '目标数量';
  $('analysis-note').textContent = '检测完成后实时更新';
  $('counts').replaceChildren(); $('downloads').hidden = true;
}
function revokePreview() {if (state.previewUrl) URL.revokeObjectURL(state.previewUrl); state.previewUrl = null;}
async function showJob(job) {
  if (state.job?.id !== job.id) return;
  state.job = job;
  $('result-state').textContent = labels[job.status];
  $('result-state').dataset.status = job.status;
  $('canvas-filename').textContent = job.name;
  $('canvas-caption').textContent = job.status === 'completed' ? '检测完成 · 标注画面' : labels[job.status];
  $('progress-area').hidden = !['queued', 'running'].includes(job.status);
  $('progress-text').textContent = job.status === 'queued' ? '已加入队列，等待执行' : '正在检测，首次加载模型可能稍慢';
  $('progress-value').textContent = `${job.progress}%`;
  $('progress').value = job.progress;
  if (job.status === 'failed') {toast(job.error); $('viewer').textContent = job.error; setBusy(false); return;}
  if (job.status !== 'completed') return;
  setBusy(false);
  const asset = job.kind === 'image' ? job.artifact : 'preview.jpg';
  const response = await api(`/api/jobs/${job.id}/files/${asset}`);
  const blob = await response.blob();
  if (state.job?.id !== job.id) return;
  revokePreview(); state.previewUrl = URL.createObjectURL(blob);
  const image = document.createElement('img'); image.src = state.previewUrl; image.alt = `${job.name} 的目标检测标注结果`;
  $('viewer').replaceChildren(image);
  $('total').textContent = job.total;
  $('total-label').textContent = job.kind === 'video' ? '各类别峰值之和' : '目标数量';
  $('classes').textContent = Object.keys(job.counts).length;
  $('elapsed').textContent = job.elapsed_seconds;
  $('resolution').textContent = `${job.width}×${job.height}`;
  $('analysis-note').textContent = job.kind === 'video' ? '各类别单帧峰值 · 未跨帧去重' : `${job.total} 个目标 · ${Object.keys(job.counts).length} 个类别`;
  $('counts').replaceChildren();
  for (const [label, count] of Object.entries(job.counts)) {
    const chip = document.createElement('span'); chip.textContent = `${classNames[label] || label} ${count}`;
    $('counts').appendChild(chip);
  }
  if (!Object.keys(job.counts).length) $('counts').textContent = '当前阈值下未发现目标';
  $('downloads').hidden = false;
  if (job.kind === 'video') toast('视频检测完成。预览为首帧，下载标注视频可查看全部画面（不含音轨）。');
}
async function pollJob(id) {
  try {
    const job = await (await api(`/api/jobs/${id}`)).json();
    if (state.job?.id !== id) return;
    await showJob(job);
    if (['queued', 'running'].includes(job.status)) state.poll = setTimeout(() => pollJob(id), 1500);
    else history();
  } catch (error) {toast(error.message); setBusy(false);}
}
async function startDetection() {
  if (!state.file) {toast('请先选择一张图片或一个视频'); return;}
  setBusy(true);
  try {
    const body = new FormData(); body.append('file', state.file);
    body.append('confidence', $('confidence').value); body.append('preset', $('preset').value);
    const job = await (await api('/api/jobs', {method:'POST', body})).json();
    stopPoll(); state.job = job; resetMetrics(); revokePreview();
    $('viewer').textContent = '正在准备画面，请等待检测完成…';
    await showJob(job); history(); pollJob(job.id);
  } catch (error) {toast(error.message); setBusy(false);}
}
$('run').addEventListener('click', startDetection);
async function history() {
  try {
    const jobs = await (await api('/api/jobs')).json();
    $('history-count').textContent = jobs.length;
    $('records-badge').textContent = `${jobs.length} 条记录`;
    $('history-body').replaceChildren();
    if (!jobs.length) {
      const row = document.createElement('tr'), cell = document.createElement('td');
      cell.colSpan = 6; cell.className = 'empty-history'; cell.textContent = '还没有检测记录，上传你的第一个文件吧。';
      row.appendChild(cell); $('history-body').appendChild(row);
    }
    for (const job of jobs) {
      const row = document.createElement('tr');
      const values = [job.name, job.kind === 'image' ? '图片' : '视频', labels[job.status],
        job.total ?? '—', new Date(job.created_at).toLocaleString('zh-CN')];
      values.forEach((value, index) => {
        const cell = document.createElement('td'); cell.textContent = value;
        if (index === 0) {cell.className = 'filename'; cell.title = job.name;}
        if (index === 2) cell.className = `status ${job.status}`;
        row.appendChild(cell);
      });
      const cell = document.createElement('td'), view = document.createElement('button');
      view.className = 'row-action'; view.textContent = '查看';
      view.onclick = () => {
        stopPoll(); state.job = job; resetMetrics(); revokePreview();
        $('viewer').textContent = '正在加载检测记录…';
        pollJob(job.id); $('workspace').scrollIntoView();
      };
      cell.appendChild(view);
      if (!['queued','running'].includes(job.status)) {
        const remove = document.createElement('button'); remove.className = 'row-action delete'; remove.textContent = '删除';
        remove.onclick = async () => {
          try {
            await api(`/api/jobs/${job.id}`, {method:'DELETE'});
            if (state.job?.id === job.id) {
              stopPoll(); state.job = null; revokePreview(); resetMetrics();
              $('viewer').textContent = '记录与结果已删除'; $('result-state').textContent = '等待输入';
              $('result-state').dataset.status = '';
              $('canvas-filename').textContent = '未选择文件';
              $('canvas-caption').textContent = '等待新画面';
            }
            history();
          } catch (error) {toast(error.message);}
        };
        cell.appendChild(remove);
      }
      row.appendChild(cell); $('history-body').appendChild(row);
    }
  } catch (error) {toast(error.message);}
}
$('refresh').onclick = history;
document.querySelectorAll('[data-file]').forEach(button => button.onclick = async () => {
  try {
    if (!state.job) return;
    const filename = button.dataset.file === 'artifact' ? state.job.artifact : button.dataset.file;
    const response = await api(`/api/jobs/${state.job.id}/files/${filename}`);
    const url = URL.createObjectURL(await response.blob()), anchor = document.createElement('a');
    anchor.href = url; anchor.download = `yolo-${state.job.id.slice(0,8)}-${filename}`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {toast(error.message);}
});
async function initialize() {
  try {
    const health = await (await api('/api/health')).json();
    $('connection').textContent = health.model_ready ? `${health.model} · ${health.device.toUpperCase()} 就绪` : '服务在线 · 模型未下载';
    $('connection').classList.add('online');
    $('model-name').textContent = health.model.replace(/\.pt$/i, '');
    $('canvas-caption').textContent = health.model_ready ? '模型已连接 · 等待新画面' : '服务在线 · 请先准备模型';
    $('upload-limit').textContent = `图片 / 视频 · 最大 ${health.max_upload_mb} MB · 视频 ≤ ${health.max_video_seconds} 秒`;
    if (health.auth_required && !$('api-key').value) {document.querySelector('.auth').open = true; toast('此服务需要访问密钥，请先填写');}
    else history();
  } catch { $('connection').textContent = '服务连接失败'; toast('无法连接服务，请检查后端是否启动'); }
}
initialize();
