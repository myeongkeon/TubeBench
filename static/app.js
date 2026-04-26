/* ── Globals ─────────────────────────────────── */
mermaid.initialize({ startOnLoad: false, theme: 'default' });
marked.setOptions({ breaks: true });

const MODELS = [
  { id: 'gemini-2.0-flash',  label: 'Gemini 2.0 Flash',  gemini: true  },
  { id: 'gemini-2.5-flash',  label: 'Gemini 2.5 Flash',  gemini: true  },
  { id: 'gemini-2.5-pro',    label: 'Gemini 2.5 Pro',    gemini: true  },
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', gemini: false },
];
const selectedModels = { planner: 'gemini-2.0-flash', trend: 'gemini-2.0-flash', kw: 'gemini-2.0-flash', copy: 'gemini-2.0-flash' };

/* ── Local storage API keys ──────────────────── */
function getKeys() {
  return {
    yt:         document.getElementById('yt-key').value.trim()        || localStorage.getItem('yt_key') || '',
    gemini:     document.getElementById('gemini-key').value.trim()    || localStorage.getItem('gemini_key') || '',
    anthropic:  document.getElementById('anthropic-key').value.trim() || localStorage.getItem('anthropic_key') || '',
  };
}

function initKeys() {
  const yt = localStorage.getItem('yt_key') || '';
  const gm = localStorage.getItem('gemini_key') || '';
  const an = localStorage.getItem('anthropic_key') || '';
  document.getElementById('yt-key').value       = yt;
  document.getElementById('gemini-key').value   = gm;
  document.getElementById('anthropic-key').value= an;
  updateKeyStatus();
}

['yt-key','gemini-key','anthropic-key'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => {
    const keys = getKeys();
    localStorage.setItem('yt_key',       document.getElementById('yt-key').value.trim());
    localStorage.setItem('gemini_key',   document.getElementById('gemini-key').value.trim());
    localStorage.setItem('anthropic_key',document.getElementById('anthropic-key').value.trim());
    updateKeyStatus();
  });
});

function updateKeyStatus() {
  const k = getKeys();
  const set = (dotId, lblId, ok, label) => {
    document.getElementById(dotId).className = 'dot ' + (ok ? 'dot-ok' : 'dot-err');
    document.getElementById(lblId).textContent = label;
  };
  set('dot-yt',       'lbl-yt',       !!k.yt,       k.yt       ? '✅ YouTube API 키 설정됨' : '❌ YouTube API 키 없음');
  set('dot-gemini',   'lbl-gemini',   !!k.gemini,   k.gemini   ? '✅ Gemini API 키 설정됨'  : '⚠️ Gemini API 키 없음');
  set('dot-anthropic','lbl-anthropic',!!k.anthropic, k.anthropic? '✅ Anthropic API 키 설정됨': '— Anthropic 미설정');
}

/* ── Tab navigation ──────────────────────────── */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

/* ── Model selector builder ──────────────────── */
function buildModelSelector(containerId, key) {
  const c = document.getElementById(containerId);
  c.innerHTML = '';
  MODELS.forEach(m => {
    const btn = document.createElement('button');
    btn.className = 'model-btn' + (selectedModels[key] === m.id ? ' active' : '');
    btn.textContent = m.label;
    btn.onclick = () => {
      selectedModels[key] = m.id;
      buildModelSelector(containerId, key);
    };
    c.appendChild(btn);
  });
}

/* ── Utilities ───────────────────────────────── */
function showAlert(el, type, msg) {
  el.innerHTML = `<div class="alert alert-${type}">${escHtml(msg)}</div>`;
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmt(n) { return Number(n).toLocaleString('ko-KR'); }

function renderMarkdown(el, md) {
  el.innerHTML = marked.parse(md || '');
}

function apiBody(extra = {}) {
  const k = getKeys();
  return {
    youtube_api_key:   k.yt,
    gemini_api_key:    k.gemini || null,
    anthropic_api_key: k.anthropic || null,
    ...extra,
  };
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

function loading(el, msg = '분석 중...') {
  el.innerHTML = `<div class="loading-row"><span class="spinner"></span>${escHtml(msg)}</div>`;
}

/* ══════════════════════════════════════════════
   채널 분석
══════════════════════════════════════════════ */
async function analyzeChannel() {
  const input = document.getElementById('ch-input').value.trim();
  const result = document.getElementById('ch-result');
  if (!input) { showAlert(result, 'error', '채널 ID 또는 핸들을 입력하세요.'); return; }
  const k = getKeys();
  if (!k.yt) { showAlert(result, 'error', 'YouTube API 키를 먼저 설정하세요.'); return; }

  loading(result, '채널 분석 중...');
  try {
    const data = await post('/api/channel/analyze', { youtube_api_key: k.yt, channel_input: input });
    if (data.error) { showAlert(result, 'error', data.error); return; }
    renderChannelResult(result, data);
  } catch (e) {
    showAlert(result, 'error', '오류: ' + e.message);
  }
}

function renderChannelResult(el, d) {
  const g = d.stats.grade;
  const gradeBg = { S: '#FFD700', A: '#C0C0C0', B: '#CD7F32' }[g] || '#eee';
  const gradeLabel = { S: 'S등급 — 최상위 채널', A: 'A등급 — 성장형 채널', B: 'B등급 — 초기/정체 채널' }[g];
  const thr = d.mcn_thresholds.S;
  const vrPct  = Math.min(d.stats.view_rate  / thr.view_rate, 1) * 100;
  const egPct  = Math.min(d.stats.avg_engagement / thr.engagement, 1) * 100;

  el.innerHTML = `
    <div class="card">
      <div class="channel-header">
        ${d.channel.thumbnail ? `<img src="${d.channel.thumbnail}" alt="thumb" />` : ''}
        <div class="ch-info">
          <h2>${escHtml(d.channel.title)}</h2>
          <div class="sub">채널 ID: ${escHtml(d.channel.id)} | 개설: ${d.channel.published_at} | 총 영상: ${fmt(d.channel.video_count)}개</div>
        </div>
      </div>
    </div>

    <div class="metrics-row">
      <div class="metric"><div class="label">👥 구독자</div><div class="value">${fmt(d.channel.subscriber_count)}명</div></div>
      <div class="metric"><div class="label">▶️ 평균 조회수</div><div class="value">${fmt(d.stats.avg_views)}회</div></div>
      <div class="metric"><div class="label">📊 구독자 대비 조회율</div><div class="value">${d.stats.view_rate}%</div></div>
      <div class="metric"><div class="label">💬 평균 참여도</div><div class="value">${d.stats.avg_engagement}%</div></div>
    </div>

    <div class="card">
      <span class="grade-badge" style="background:${gradeBg};color:#111;">🏆 MCN ${gradeLabel}</span>
      <p style="margin:8px 0;font-size:.87rem;color:var(--muted);">${escHtml(d.diagnosis.summary)}</p>
      <div class="progress-wrap">
        <div class="progress-label">조회율 ${d.stats.view_rate}% / S기준 ${thr.view_rate}%</div>
        <div class="progress-bar"><div class="progress-fill" style="width:${vrPct}%"></div></div>
      </div>
      <div class="progress-wrap">
        <div class="progress-label">참여도 ${d.stats.avg_engagement}% / S기준 ${thr.engagement}%</div>
        <div class="progress-bar"><div class="progress-fill" style="width:${egPct}%"></div></div>
      </div>
    </div>

    <div class="chart-row">
      <div class="chart-box"><div id="ch-chart-trend"></div></div>
      <div class="chart-box"><div id="ch-chart-eng"></div></div>
    </div>

    <div class="card">
      <h3 style="margin-bottom:12px;font-size:.95rem;">📋 MCN 진단 리포트</h3>
      <div class="row">
        <div style="flex:1;">
          <strong>✅ 강점</strong>
          <ul style="margin-top:6px;padding-left:18px;font-size:.85rem;">
            ${d.diagnosis.strengths.map(s => `<li>${escHtml(s)}</li>`).join('')}
          </ul>
        </div>
        <div style="flex:1;">
          <strong>🎯 개선 제안</strong>
          <ul style="margin-top:6px;padding-left:18px;font-size:.85rem;">
            ${d.diagnosis.improvements.map(s => `<li>${escHtml(s)}</li>`).join('')}
          </ul>
        </div>
      </div>
    </div>

    <div class="card">
      <details>
        <summary>📄 영상별 원시 데이터 (${d.raw_videos.length}개)</summary>
        <div class="table-wrap" style="margin-top:10px;">
          <table class="data-table">
            <thead><tr><th>제목</th><th>업로드일</th><th>조회수</th><th>좋아요</th><th>댓글</th><th>참여도(%)</th></tr></thead>
            <tbody>${d.raw_videos.map(v => `
              <tr>
                <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(v.title)}">${escHtml(v.title)}</td>
                <td>${v.published_at}</td>
                <td>${fmt(v.view_count)}</td>
                <td>${fmt(v.like_count)}</td>
                <td>${fmt(v.comment_count)}</td>
                <td>${v.engagement_rate}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  `;

  // Trend chart
  Plotly.newPlot('ch-chart-trend', [{
    x: d.chart_trend.map(r => r.published_at),
    y: d.chart_trend.map(r => r.view_count),
    text: d.chart_trend.map(r => r.title),
    mode: 'lines+markers',
    line: { color: '#FF4B4B' },
    hovertemplate: '%{text}<br>조회수: %{y:,}<extra></extra>',
  }, {
    x: [d.chart_trend[0]?.published_at, d.chart_trend[d.chart_trend.length-1]?.published_at],
    y: [d.stats.avg_views, d.stats.avg_views],
    mode: 'lines',
    line: { color: 'gray', dash: 'dot' },
    name: `평균 ${fmt(d.stats.avg_views)}`,
    hoverinfo: 'none',
  }], {
    title: '📈 조회수 추이',
    height: 320,
    margin: { l: 50, r: 10, t: 40, b: 40 },
    xaxis: { title: '업로드일' },
    yaxis: { title: '조회수' },
    showlegend: true,
  }, { responsive: true });

  // Engagement bar chart
  Plotly.newPlot('ch-chart-eng', [{
    x: d.chart_engagement.map(r => r.engagement_rate),
    y: d.chart_engagement.map(r => r.short_title),
    text: d.chart_engagement.map(r => r.title),
    type: 'bar',
    orientation: 'h',
    marker: { color: d.chart_engagement.map(r => r.engagement_rate), colorscale: 'Reds' },
    hovertemplate: '%{text}<br>참여도: %{x:.2f}%<extra></extra>',
  }], {
    title: '💬 참여도 상위 영상 Top 10',
    height: 320,
    margin: { l: 180, r: 10, t: 40, b: 40 },
    yaxis: { autorange: 'reversed' },
    xaxis: { title: '참여도 (%)' },
  }, { responsive: true });
}

/* ══════════════════════════════════════════════
   경쟁사 벤치마킹
══════════════════════════════════════════════ */
async function analyzeCompetitor() {
  const result = document.getElementById('comp-result');
  const k = getKeys();
  if (!k.yt) { showAlert(result, 'error', 'YouTube API 키를 먼저 설정하세요.'); return; }

  const competitor_ids = ['comp-c1','comp-c2','comp-c3']
    .map(id => document.getElementById(id).value.trim()).filter(Boolean);
  if (!competitor_ids.length) { showAlert(result, 'error', '경쟁 채널을 1개 이상 입력하세요.'); return; }

  loading(result, '경쟁사 데이터 수집 중...');
  try {
    const data = await post('/api/competitor/analyze', {
      youtube_api_key: k.yt,
      my_channel:      document.getElementById('comp-my').value.trim() || null,
      competitor_ids,
      outlier_mult:    parseFloat(document.getElementById('outlier-mult').value),
    });
    if (data.error) { showAlert(result, 'error', data.error); return; }
    renderCompetitorResult(result, data);
  } catch (e) {
    showAlert(result, 'error', '오류: ' + e.message);
  }
}

function renderCompetitorResult(el, d) {
  const errorHtml = d.errors?.length
    ? d.errors.map(e => `<div class="alert alert-warning">${escHtml(e)}</div>`).join('') : '';

  const tableRows = d.channel_table.map(r => `
    <tr style="${r.is_mine ? 'background:#f0f9ff;font-weight:700;' : ''}">
      <td>${escHtml(r['채널명'])}${r.is_mine ? ' <span style="color:var(--accent);font-size:.72rem;">[내 채널]</span>' : ''}</td>
      <td>${r['구독자']}</td><td>${r['평균 조회수']}</td>
      <td>${r['조회율(%)']}</td><td>${r['Engagement']}</td>
      <td>${r['아웃라이어 수']}</td>
    </tr>`).join('');

  const outlierHtml = d.outliers.map(v => `
    <div class="outlier-card">
      ${v.thumbnail ? `<img src="${v.thumbnail}" alt="thumb" />` : ''}
      <div class="info">
        <div class="title">${escHtml(v.title)}</div>
        <div class="meta">${escHtml(v.channel)} | 조회수 ${fmt(v.view_count)} | 패턴: ${v.patterns.join(', ')}</div>
        <a href="https://www.youtube.com/watch?v=${v.video_id}" target="_blank" style="font-size:.75rem;color:var(--accent);">▶ YouTube에서 보기</a>
      </div>
      <div class="outlier-ratio">×${v.outlier_ratio}</div>
    </div>`).join('') || '<p style="color:var(--muted);font-size:.85rem;">아웃라이어 영상이 없습니다.</p>';

  const gapHtml = d.gap_keywords.length
    ? `<div class="tag-list">${d.gap_keywords.slice(0,20).map(([k,c]) => `<span class="tag">${escHtml(k)} (${c})</span>`).join('')}</div>`
    : '<p style="color:var(--muted);font-size:.85rem;">내 채널을 입력하면 Content Gap을 볼 수 있습니다.</p>';

  el.innerHTML = `
    ${errorHtml}
    <div class="card">
      <h3 style="margin-bottom:12px;font-size:.95rem;">📊 채널 지표 비교</h3>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>채널명</th><th>구독자</th><th>평균 조회수</th><th>조회율(%)</th><th>Engagement</th><th>아웃라이어 수</th></tr></thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
    </div>
    <div class="chart-row">
      <div class="chart-box"><div id="comp-quad-chart"></div></div>
      <div class="chart-box">
        <h4 style="margin-bottom:10px;font-size:.9rem;">🔑 Content Gap 키워드 (경쟁사만 사용 중)</h4>
        ${gapHtml}
      </div>
    </div>
    <div class="card">
      <h3 style="margin-bottom:12px;font-size:.95rem;">⚡ 급상승 영상 (아웃라이어)</h3>
      ${outlierHtml}
    </div>
  `;

  // Quadrant scatter chart
  const pts = d.quadrant_points;
  Plotly.newPlot('comp-quad-chart', [{
    x: pts.map(p => p.x * 20),
    y: pts.map(p => p.y * 0.5),
    text: pts.map(p => p.label),
    mode: 'markers+text',
    textposition: 'top center',
    marker: {
      size: 14,
      color: pts.map(p => p.is_mine ? '#FF4B4B' : '#4B9DFF'),
    },
    hovertemplate: '%{text}<extra></extra>',
  }], {
    title: '채널 포지션 (조회율 vs Engagement)',
    height: 320,
    margin: { l: 50, r: 10, t: 40, b: 40 },
    xaxis: { title: '구독자 대비 조회율 (%)', range: [0, 20] },
    yaxis: { title: 'Engagement Score (%)', range: [0, 0.5] },
    shapes: [
      { type: 'line', x0: 10, x1: 10, y0: 0, y1: 0.5, line: { dash: 'dot', color: '#aaa' } },
      { type: 'line', x0: 0,  x1: 20, y0: 0.25, y1: 0.25, line: { dash: 'dot', color: '#aaa' } },
    ],
  }, { responsive: true });
}

/* ══════════════════════════════════════════════
   AI 영상 기획
══════════════════════════════════════════════ */
async function streamPlanner() {
  const topic = document.getElementById('plan-topic').value.trim();
  const wrap  = document.getElementById('plan-output-wrap');
  const out   = document.getElementById('plan-output');
  if (!topic) { alert('영상 주제를 입력하세요.'); return; }

  const k = getKeys();
  const modelId = selectedModels.planner;
  const isGemini = !modelId.startsWith('claude');
  if (isGemini && !k.gemini) { alert('Gemini API 키를 설정하세요.'); return; }
  if (!isGemini && !k.anthropic) { alert('Anthropic API 키를 설정하세요.'); return; }

  wrap.style.display = 'block';
  out.innerHTML = '<div class="loading-row"><span class="spinner"></span>AI 기획 생성 중...</div>';

  const body = apiBody({
    model_id:      modelId,
    topic,
    channel_info:  document.getElementById('plan-ch-info').value.trim() || null,
    target_length: document.getElementById('plan-length').value,
    outlier_data:  document.getElementById('plan-outlier').value.trim() || null,
    gap_keywords:  document.getElementById('plan-gap').value.trim() || null,
  });

  await streamSSE('/api/planner/stream', body, out);
}

/* ══════════════════════════════════════════════
   트렌드 기획
══════════════════════════════════════════════ */
let trendAnalysisData = null;

async function analyzeTrend() {
  const result = document.getElementById('trend-result');
  const k = getKeys();
  if (!k.yt) { showAlert(result, 'error', 'YouTube API 키를 먼저 설정하세요.'); return; }

  const my_channel = document.getElementById('trend-my').value.trim();
  if (!my_channel) { showAlert(result, 'error', '내 채널을 입력하세요.'); return; }

  const competitor_ids = Array.from(document.querySelectorAll('.trend-comp'))
    .map(inp => inp.value.trim()).filter(Boolean);
  if (!competitor_ids.length) { showAlert(result, 'error', '경쟁 채널을 1개 이상 입력하세요.'); return; }

  loading(result, '경쟁채널 최근 3일 영상 수집 중...');
  try {
    const data = await post('/api/trend/analyze', {
      youtube_api_key: k.yt,
      my_channel_id:   my_channel,
      competitor_ids,
    });
    if (data.error) { showAlert(result, 'error', data.error); return; }
    trendAnalysisData = data;
    renderTrendResult(result, data);
  } catch (e) {
    showAlert(result, 'error', '오류: ' + e.message);
  }
}

function renderTrendResult(el, d) {
  const rows = d.video_rows.map(v => `
    <tr>
      <td>${escHtml(v.channel)}</td>
      <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(v.title)}">${escHtml(v.title)}</td>
      <td>${v.published_at}</td>
      <td>${fmt(v.view_count)}</td>
      <td>${v.velocity}</td>
      <td>${escHtml(v.patterns)}</td>
    </tr>`).join('');

  el.innerHTML = `
    <div class="card">
      <h3 style="margin-bottom:10px;font-size:.95rem;">📡 최근 3일 경쟁채널 영상</h3>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>채널</th><th>제목</th><th>업로드일</th><th>조회수</th><th>속도(회/h)</th><th>패턴</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6" style="color:var(--muted);text-align:center;">최근 3일 영상 없음</td></tr>'}</tbody>
        </table>
      </div>
      <div style="margin-top:14px;">
        <div style="margin-bottom:10px;">
          <label style="font-size:.82rem;font-weight:600;">🤖 AI 모델 선택</label>
          <div class="model-select-row" id="trend-models2" style="margin-top:6px;"></div>
        </div>
        <button class="btn btn-primary" onclick="streamTrendAI()">🚀 AI 트렌드 기획 생성</button>
      </div>
    </div>
    <div id="trend-ai-wrap" style="display:none;">
      <div class="card">
        <h3 style="margin-bottom:12px;font-size:.95rem;">📄 AI 트렌드 기획</h3>
        <div class="ai-output" id="trend-ai-out"></div>
      </div>
    </div>
    <div id="trend-comment-section" class="card" style="margin-top:0;">
      <h3 style="margin-bottom:12px;font-size:.95rem;">💬 댓글분석 및 기획</h3>
      <div class="form-group">
        <label>댓글 분석할 영상 선택</label>
        <select id="trend-video-sel">
          ${d.video_rows.filter(v => v.comment_count > 0).map(v =>
            `<option value="${v.video_id}" data-title="${escHtml(v.title)}">[${escHtml(v.channel)}] ${escHtml(v.title.slice(0,50))} (${fmt(v.view_count)}회)</option>`
          ).join('') || '<option value="">댓글이 있는 영상 없음</option>'}
        </select>
      </div>
      <div class="form-group">
        <label>키워드 (선택)</label>
        <input type="text" id="trend-comment-kw" placeholder="분석 키워드" />
      </div>
      <button class="btn btn-secondary" onclick="streamTrendComment()">💬 댓글 수집 & 기획 분석</button>
      <div id="trend-comment-out-wrap" style="display:none;margin-top:12px;">
        <div class="ai-output" id="trend-comment-out"></div>
      </div>
    </div>
  `;
  buildModelSelector('trend-models2', 'trend');
}

async function streamTrendAI() {
  if (!trendAnalysisData) return;
  const wrap = document.getElementById('trend-ai-wrap');
  const out  = document.getElementById('trend-ai-out');
  wrap.style.display = 'block';
  out.innerHTML = '<div class="loading-row"><span class="spinner"></span>AI 분석 중...</div>';

  const k = getKeys();
  await streamSSE('/api/trend/stream', {
    gemini_api_key:    k.gemini || null,
    anthropic_api_key: k.anthropic || null,
    model_id:          selectedModels.trend,
    my_channel_title:  trendAnalysisData.my_channel_title,
    summary_text:      trendAnalysisData.summary_text,
  }, out);
}

async function streamTrendComment() {
  const sel = document.getElementById('trend-video-sel');
  const videoId = sel.value;
  if (!videoId) { alert('영상을 선택하세요.'); return; }
  const videoTitle = sel.selectedOptions[0]?.dataset.title || '';
  const kw = document.getElementById('trend-comment-kw').value.trim();
  const k  = getKeys();
  if (!k.yt) { alert('YouTube API 키를 설정하세요.'); return; }

  const wrap = document.getElementById('trend-comment-out-wrap');
  const out  = document.getElementById('trend-comment-out');
  wrap.style.display = 'block';
  out.innerHTML = '<div class="loading-row"><span class="spinner"></span>댓글 수집 중...</div>';

  try {
    const res  = await fetch(`/api/trend/comments?youtube_api_key=${encodeURIComponent(k.yt)}&video_id=${videoId}`);
    const data = await res.json();
    if (!data.comments?.length) { out.innerHTML = '<p>댓글이 없거나 비활성화된 영상입니다.</p>'; return; }

    out.innerHTML = '<div class="loading-row"><span class="spinner"></span>AI 분석 중...</div>';
    await streamSSE('/api/trend/comment-stream', {
      gemini_api_key:    k.gemini || null,
      anthropic_api_key: k.anthropic || null,
      model_id:          selectedModels.trend,
      video_title:       videoTitle,
      keyword:           kw || videoTitle,
      comments:          data.comments,
    }, out);
  } catch (e) {
    out.innerHTML = `<div class="alert alert-error">${escHtml(e.message)}</div>`;
  }
}

/* ══════════════════════════════════════════════
   키워드 분석
══════════════════════════════════════════════ */
let kwAnalysisData = null;

async function analyzeKeyword() {
  const kw = document.getElementById('kw-input').value.trim();
  const result = document.getElementById('kw-result');
  if (!kw) { showAlert(result, 'error', '키워드를 입력하세요.'); return; }
  const k = getKeys();
  if (!k.yt) { showAlert(result, 'error', 'YouTube API 키를 먼저 설정하세요.'); return; }

  loading(result, `"${kw}" 키워드 분석 중...`);
  try {
    const data = await post('/api/keyword/analyze', { youtube_api_key: k.yt, keyword: kw, max_results: 20 });
    if (data.error) { showAlert(result, 'error', data.error); return; }
    kwAnalysisData = data;
    renderKeywordResult(result, data);
  } catch (e) {
    showAlert(result, 'error', '오류: ' + e.message);
  }
}

function renderKeywordResult(el, d) {
  const sc = d.score;
  const { label, color } = kwScoreLabel(sc.total);
  const r = 45;
  const circ = 2 * Math.PI * r;
  const dash = circ * (sc.total / 100);

  const videoRows = d.videos.map(v => `
    <tr>
      <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(v.title)}">${escHtml(v.title)}</td>
      <td style="font-size:.75rem;">${escHtml(v.channel_title)}</td>
      <td>${fmt(v.view_count)}</td><td>${fmt(v.like_count)}</td><td>${fmt(v.comment_count)}</td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="loadKwComments('${v.video_id}','${escHtml(v.title).replace(/'/g,"\\'")}')" style="font-size:.72rem;">💬 댓글분석</button>
      </td>
    </tr>`).join('');

  el.innerHTML = `
    <div class="card">
      <h3 style="margin-bottom:14px;font-size:.95rem;">🔎 "${escHtml(d.keyword)}" 키워드 점수</h3>
      <div class="score-container">
        <div class="score-ring">
          <svg width="110" height="110" viewBox="0 0 110 110">
            <circle class="ring-bg" cx="55" cy="55" r="${r}" />
            <circle class="ring-fill" cx="55" cy="55" r="${r}"
              stroke="${color}"
              stroke-dasharray="${dash} ${circ}"
              stroke-dashoffset="0" />
          </svg>
          <div class="ring-text" style="color:${color};">${sc.total}<br/><small style="font-size:.6rem;font-weight:400;">/100</small></div>
        </div>
        <div class="score-breakdown">
          <div style="font-size:1.1rem;font-weight:700;color:${color};margin-bottom:10px;">${label}</div>
          ${scoreBar('바이럴 잠재력', sc.viral, 30, '#FF4B4B')}
          ${scoreBar('참여도', sc.engagement, 20, '#FF8C00')}
          ${scoreBar('트렌드 현황', sc.trend, 25, '#4B9DFF')}
          ${scoreBar('진입 기회', sc.opportunity, 25, '#28a745')}
        </div>
        <div style="font-size:.8rem;color:var(--muted);line-height:1.7;">
          평균 조회수: <strong>${fmt(sc.avg_views)}</strong>회<br>
          평균 참여율: <strong>${sc.avg_eng_rate}%</strong><br>
          평균 조회속도: <strong>${sc.avg_velocity}</strong>회/h
        </div>
      </div>
    </div>

    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <h4 style="font-size:.9rem;">🤖 AI 전략 분석</h4>
        <div class="model-select-row" id="kw-models2"></div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="streamKwAI()">AI 전략 생성</button>
      <div id="kw-ai-wrap" style="display:none;margin-top:12px;">
        <div class="ai-output" id="kw-ai-out"></div>
      </div>
    </div>

    <div class="card">
      <h4 style="margin-bottom:10px;font-size:.9rem;">📋 상위 검색 결과 영상</h4>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>제목</th><th>채널</th><th>조회수</th><th>좋아요</th><th>댓글</th><th></th></tr></thead>
          <tbody>${videoRows}</tbody>
        </table>
      </div>
    </div>

    <div id="kw-comment-wrap" style="display:none;">
      <div class="card">
        <h4 style="margin-bottom:10px;font-size:.9rem;">💬 댓글 기반 기획 분석</h4>
        <div class="ai-output" id="kw-comment-out"></div>
      </div>
    </div>
  `;
  buildModelSelector('kw-models2', 'kw');
}

function scoreBar(label, val, max, color) {
  const pct = (val / max * 100).toFixed(0);
  return `<div class="score-row">
    <span style="min-width:80px;">${label}</span>
    <div class="score-bar"><div class="score-bar-fill" style="width:${pct}%;background:${color};height:100%;border-radius:3px;"></div></div>
    <span style="min-width:50px;text-align:right;">${val}/${max}</span>
  </div>`;
}

function kwScoreLabel(total) {
  if (total >= 80) return { label: '🔥 매우 강력', color: '#FF4B4B' };
  if (total >= 65) return { label: '⭐ 강력',       color: '#FF8C00' };
  if (total >= 50) return { label: '✅ 보통',        color: '#FFC107' };
  if (total >= 35) return { label: '⚠️ 낮음',        color: '#9E9E9E' };
  return               { label: '❌ 매우 낮음',   color: '#607D8B' };
}

async function streamKwAI() {
  if (!kwAnalysisData) return;
  const wrap = document.getElementById('kw-ai-wrap');
  const out  = document.getElementById('kw-ai-out');
  wrap.style.display = 'block';
  out.innerHTML = '<div class="loading-row"><span class="spinner"></span>AI 분석 중...</div>';
  const k = getKeys();
  await streamSSE('/api/keyword/ai-stream', {
    gemini_api_key:    k.gemini || null,
    anthropic_api_key: k.anthropic || null,
    model_id:          selectedModels.kw,
    keyword:           kwAnalysisData.keyword,
    score:             kwAnalysisData.score,
    videos:            kwAnalysisData.videos,
    stats:             kwAnalysisData.stats,
  }, out);
}

async function loadKwComments(videoId, videoTitle) {
  const wrap = document.getElementById('kw-comment-wrap');
  const out  = document.getElementById('kw-comment-out');
  wrap.style.display = 'block';
  out.innerHTML = '<div class="loading-row"><span class="spinner"></span>댓글 수집 중...</div>';

  const k = getKeys();
  try {
    const res  = await fetch(`/api/keyword/comments?youtube_api_key=${encodeURIComponent(k.yt)}&video_id=${videoId}`);
    const data = await res.json();
    if (!data.comments?.length) { out.innerHTML = '<p>댓글이 없거나 비활성화된 영상입니다.</p>'; return; }
    out.innerHTML = '<div class="loading-row"><span class="spinner"></span>AI 분석 중...</div>';
    await streamSSE('/api/keyword/comment-stream', {
      gemini_api_key:    k.gemini || null,
      anthropic_api_key: k.anthropic || null,
      model_id:          selectedModels.kw,
      video_title:       videoTitle,
      keyword:           kwAnalysisData?.keyword || videoTitle,
      comments:          data.comments,
    }, out);
  } catch (e) {
    out.innerHTML = `<div class="alert alert-error">${escHtml(e.message)}</div>`;
  }
}

/* ══════════════════════════════════════════════
   카피라이팅
══════════════════════════════════════════════ */
async function initCopywriterOptions() {
  try {
    const res  = await fetch('/api/copywriter/options');
    const data = await res.json();
    const sel  = document.getElementById('copy-style');
    data.styles.forEach(s => {
      const opt = document.createElement('option');
      opt.value = opt.textContent = s;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

async function streamCopywriter() {
  const kw      = document.getElementById('copy-kw').value.trim();
  const content = document.getElementById('copy-content').value.trim();
  const wrap    = document.getElementById('copy-output-wrap');
  const out     = document.getElementById('copy-output');
  if (!kw || !content) { alert('키워드와 영상 내용을 모두 입력하세요.'); return; }

  const k = getKeys();
  const modelId = selectedModels.copy;
  const isGemini = !modelId.startsWith('claude');
  if (isGemini && !k.gemini) { alert('Gemini API 키를 설정하세요.'); return; }
  if (!isGemini && !k.anthropic) { alert('Anthropic API 키를 설정하세요.'); return; }

  wrap.style.display = 'block';
  out.innerHTML = '<div class="loading-row"><span class="spinner"></span>카피 생성 중...</div>';

  await streamSSE('/api/copywriter/stream', {
    gemini_api_key:    k.gemini || null,
    anthropic_api_key: k.anthropic || null,
    model_id:          modelId,
    keyword:           kw,
    content,
    style_key:         document.getElementById('copy-style').value,
    emotion_key:       document.getElementById('copy-emotion').value,
    length_key:        document.getElementById('copy-length').value,
  }, out);
}

/* ══════════════════════════════════════════════
   캐시 삭제
══════════════════════════════════════════════ */
async function clearCache() {
  const msg = document.getElementById('cache-msg');
  const k = getKeys();
  if (!k.yt) { showAlert(msg, 'error', 'YouTube API 키를 먼저 설정하세요.'); return; }
  msg.innerHTML = '<div class="loading-row"><span class="spinner"></span>캐시 삭제 중...</div>';
  try {
    const data = await post('/api/system/cache/clear', { youtube_api_key: k.yt });
    showAlert(msg, 'success', `만료된 캐시 ${data.deleted}개 삭제 완료`);
  } catch (e) {
    showAlert(msg, 'error', e.message);
  }
}

/* ══════════════════════════════════════════════
   SSE 스트리밍 공통
══════════════════════════════════════════════ */
async function streamSSE(url, body, outEl) {
  let full = '';
  outEl.innerHTML = '<div class="loading-row"><span class="spinner"></span>생성 중...</div>';

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const ev = JSON.parse(line.slice(6));
          if (ev.error) { outEl.innerHTML = `<div class="alert alert-error">${escHtml(ev.error)}</div>`; return; }
          if (ev.done)  { renderMarkdown(outEl, full); return; }
          if (ev.text)  { full += ev.text; outEl.innerHTML = marked.parse(full) + '<span class="spinner" style="display:inline-block;width:12px;height:12px;margin-left:4px;vertical-align:middle;"></span>'; }
        } catch (_) {}
      }
    }
    renderMarkdown(outEl, full);
  } catch (e) {
    outEl.innerHTML = `<div class="alert alert-error">${escHtml(e.message)}</div>`;
  }
}

/* ══════════════════════════════════════════════
   History Modal
══════════════════════════════════════════════ */
let histCurrentTab = '';

async function openHistory(tab, title) {
  histCurrentTab = tab;
  document.getElementById('hist-modal-title').textContent = title;
  document.getElementById('hist-modal-body').innerHTML = '<div class="loading-row"><span class="spinner"></span>불러오는 중...</div>';
  document.getElementById('hist-modal').style.display = 'flex';

  try {
    const res  = await fetch(`/api/history/${tab}`);
    const data = await res.json();
    renderHistoryList(data.records || []);
  } catch (e) {
    document.getElementById('hist-modal-body').innerHTML = `<div class="alert alert-error">${escHtml(e.message)}</div>`;
  }
}

function renderHistoryList(records) {
  const body = document.getElementById('hist-modal-body');
  if (!records.length) { body.innerHTML = '<p style="color:var(--muted);">저장된 기록이 없습니다.</p>'; return; }
  body.innerHTML = `
    <select id="hist-sel" style="width:100%;margin-bottom:14px;border:1px solid var(--border);border-radius:7px;padding:8px;">
      ${records.map((r, i) => `<option value="${i}">${r.timestamp} — ${escHtml(r.label)}</option>`).join('')}
    </select>
    <button class="btn btn-primary btn-sm" onclick="loadHistoryEntry(${JSON.stringify(records).replace(/</g,'&lt;')})">불러오기</button>
    <div id="hist-entry" style="margin-top:14px;"></div>
  `;
}

async function loadHistoryEntry(records) {
  const idx      = parseInt(document.getElementById('hist-sel').value);
  const rec      = records[idx];
  const entryDiv = document.getElementById('hist-entry');
  entryDiv.innerHTML = '<div class="loading-row"><span class="spinner"></span>불러오는 중...</div>';

  try {
    const res  = await fetch(`/api/history/${histCurrentTab}/${rec.filename}`);
    const data = await res.json();
    const d    = data.data || {};
    let html   = `<div class="alert alert-info">저장 시각: ${data.timestamp || '-'} | 레이블: ${escHtml(data.label || '-')}</div>`;

    if (d.output) html += `<div class="ai-output">${marked.parse(d.output)}</div>`;
    else          html += `<pre style="background:#f5f5f5;padding:12px;border-radius:7px;font-size:.78rem;overflow-x:auto;">${escHtml(JSON.stringify(d, null, 2))}</pre>`;
    entryDiv.innerHTML = html;
  } catch (e) {
    entryDiv.innerHTML = `<div class="alert alert-error">${escHtml(e.message)}</div>`;
  }
}

function closeHistory()           { document.getElementById('hist-modal').style.display = 'none'; }
function closeHistoryOnBackdrop(e){ if (e.target.id === 'hist-modal') closeHistory(); }

/* ══════════════════════════════════════════════
   Profile Manager Modal
══════════════════════════════════════════════ */
async function openProfileManager() {
  document.getElementById('profile-modal').style.display = 'flex';
  await refreshProfileModal();
}

async function refreshProfileModal() {
  const body = document.getElementById('profile-modal-body');
  body.innerHTML = '<div class="loading-row"><span class="spinner"></span>프로필 불러오는 중...</div>';
  try {
    const res  = await fetch('/api/trend/profiles');
    const data = await res.json();
    renderProfileModal(data.profiles || []);
  } catch (e) {
    body.innerHTML = `<div class="alert alert-error">${escHtml(e.message)}</div>`;
  }
}

function renderProfileModal(profiles) {
  const body = document.getElementById('profile-modal-body');
  const profilesHtml = profiles.length ? profiles.map(p => `
    <div class="profile-item">
      ${p.thumbnail ? `<img src="${p.thumbnail}" alt="" />` : '<div style="width:36px;height:36px;border-radius:50%;background:#eee;"></div>'}
      <span class="pname">${escHtml(p.title)}</span>
      <button class="btn btn-sm btn-secondary" onclick="selectProfile('${p.channel_id}','${escHtml(p.title)}')">선택</button>
      <button class="btn btn-sm" style="background:#fee2e2;color:#991b1b;" onclick="deleteProfile('${p.channel_id}')">삭제</button>
    </div>`).join('') : '<p style="color:var(--muted);font-size:.85rem;">저장된 프로필이 없습니다.</p>';

  body.innerHTML = `
    ${profilesHtml}
    <hr style="margin:16px 0;border:none;border-top:1px solid var(--border);" />
    <h4 style="margin-bottom:10px;font-size:.9rem;">새 프로필 추가</h4>
    <div class="form-group">
      <label>내 채널 *</label>
      <input type="text" id="pf-my" placeholder="UCxxxxxx 또는 @handle" />
    </div>
    <div class="form-group">
      <label>경쟁채널 (줄바꿈으로 구분, 최대 10개)</label>
      <textarea id="pf-comps" rows="4" placeholder="@channel1&#10;@channel2&#10;@channel3"></textarea>
    </div>
    <button class="btn btn-primary" onclick="saveProfile()">💾 저장</button>
    <div id="pf-msg" style="margin-top:8px;"></div>
  `;
}

async function saveProfile() {
  const k = getKeys();
  if (!k.yt) { showAlert(document.getElementById('pf-msg'), 'error', 'YouTube API 키를 설정하세요.'); return; }
  const my = document.getElementById('pf-my').value.trim();
  if (!my)  { showAlert(document.getElementById('pf-msg'), 'error', '내 채널을 입력하세요.'); return; }
  const competitors = document.getElementById('pf-comps').value.split('\n').map(s => s.trim()).filter(Boolean);
  if (!competitors.length) { showAlert(document.getElementById('pf-msg'), 'error', '경쟁채널을 1개 이상 입력하세요.'); return; }

  document.getElementById('pf-msg').innerHTML = '<div class="loading-row"><span class="spinner"></span>저장 중...</div>';
  try {
    const data = await post('/api/trend/profiles/save', { youtube_api_key: k.yt, my_channel: my, competitors });
    if (data.error) { showAlert(document.getElementById('pf-msg'), 'error', data.error); return; }
    showAlert(document.getElementById('pf-msg'), 'success', `저장 완료: ${data.my_channel?.title} + 경쟁채널 ${data.competitors?.length}개`);
    await refreshProfileModal();
    await refreshTrendProfiles();
  } catch (e) {
    showAlert(document.getElementById('pf-msg'), 'error', e.message);
  }
}

function selectProfile(channelId, title) {
  document.getElementById('trend-my').value = channelId;
  // Load competitors
  fetch(`/api/trend/profiles/${channelId}/competitors`)
    .then(r => r.json())
    .then(data => {
      const inputs = document.querySelectorAll('.trend-comp');
      data.competitors?.forEach((c, i) => {
        if (inputs[i]) inputs[i].value = c.channel_id;
      });
    });
  closeProfileModal();
}

async function deleteProfile(channelId) {
  if (!confirm('프로필을 삭제하시겠습니까?')) return;
  await fetch(`/api/trend/profiles/${channelId}`, { method: 'DELETE' });
  await refreshProfileModal();
  await refreshTrendProfiles();
}

async function refreshTrendProfiles() {
  const sel = document.getElementById('trend-profile-sel');
  try {
    const res  = await fetch('/api/trend/profiles');
    const data = await res.json();
    sel.innerHTML = '<option value="">-- 저장된 프로필 선택 --</option>';
    (data.profiles || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.channel_id;
      opt.textContent = p.title;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

async function loadTrendProfile() {
  const channelId = document.getElementById('trend-profile-sel').value;
  if (!channelId) return;
  document.getElementById('trend-my').value = channelId;
  try {
    const res  = await fetch(`/api/trend/profiles/${channelId}/competitors`);
    const data = await res.json();
    const inputs = document.querySelectorAll('.trend-comp');
    inputs.forEach(inp => inp.value = '');
    data.competitors?.forEach((c, i) => {
      if (inputs[i]) inputs[i].value = c.channel_id;
    });
  } catch (_) {}
}

function closeProfileModal()           { document.getElementById('profile-modal').style.display = 'none'; }
function closeProfileOnBackdrop(e)     { if (e.target.id === 'profile-modal') closeProfileModal(); }

/* ══════════════════════════════════════════════
   Init
══════════════════════════════════════════════ */
(async function init() {
  initKeys();
  buildModelSelector('planner-models', 'planner');
  buildModelSelector('trend-models',   'trend');
  buildModelSelector('kw-models',      'kw');
  buildModelSelector('copy-models',    'copy');
  await initCopywriterOptions();
  await refreshTrendProfiles();
})();
