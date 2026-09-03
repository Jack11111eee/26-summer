/* 01 ChatGPT 式 · 交互脚本
   职责（克制）：
   - 深浅主题切换 + localStorage 记忆 + 跟随系统
   - textarea 自适应高度
   - 演示态：发送后把气泡渲染进对话流、显示 AI 状态行轮换
   - Enter 发送 / Shift+Enter 换行 / IME composition 不误发
*/
(function () {
  'use strict';

  var root = document.documentElement;
  var KEY = 'chat-styles-01-theme';
  var memory = null;

  var toggle = document.querySelector('.btn-theme');
  var ta = document.querySelector('.ta');
  var form = document.querySelector('.composer');
  var thread = document.querySelector('.thread');
  var statusText = document.querySelector('.status-text');
  var statusline = document.querySelector('.statusline');

  /* ---------- 主题 ---------- */
  function readTheme() {
    // ?theme=dark|light 优先（便于直接链接与截图验证）
    try {
      var q = new URLSearchParams(location.search).get('theme');
      if (q === 'dark' || q === 'light') return q;
    } catch (e) { /* old browsers */ }

    var v = null;
    try { v = localStorage.getItem(KEY); } catch (e) { v = memory; }
    if (v === 'dark' || v === 'light') return v;
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(t, persist) {
    root.setAttribute('data-theme', t);
    if (toggle) {
      toggle.setAttribute('aria-pressed', t === 'dark' ? 'true' : 'false');
      var label = toggle.querySelector('.tb-theme-label');
      if (label) label.textContent = t === 'dark' ? '日间' : '夜间';
    }
    if (persist) {
      memory = t;
      try { localStorage.setItem(KEY, t); } catch (e) { /* file:// */ }
    }
  }

  applyTheme(readTheme(), false);

  if (toggle) {
    toggle.addEventListener('click', function () {
      applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark', true);
    });
  }

  /* ---------- textarea 自适应 ---------- */
  function fit() {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }
  ta.addEventListener('input', fit);

  /* ---------- IME ---------- */
  var composing = false;
  ta.addEventListener('compositionstart', function () { composing = true; });
  ta.addEventListener('compositionend', function () { composing = false; });

  /* ---------- 状态行轮换 ---------- */
  var timers = [];
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }

  function setStatus(text) {
    if (statusText) statusText.textContent = text;
  }

  /* ---------- 发送（演示态） ---------- */
  function nowTime() {
    var d = new Date();
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }

  function submit() {
    var v = ta.value.trim();
    if (!v || composing) return;

    var row = document.createElement('div');
    row.className = 'msg me';
    var b = document.createElement('div');
    b.className = 'bubble';
    b.textContent = v;
    row.appendChild(b);
    thread.appendChild(row);

    ta.value = '';
    fit();
    clearTimers();

    setStatus('回答已保存 · AI 正在理解你的回答');
    timers.push(setTimeout(function () {
      setStatus('AI 正在准备下一问');
    }, 1400));
    timers.push(setTimeout(function () {
      setStatus('可以继续了 · 等待你的回答');
    }, 3000));
  }

  ta.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !composing) {
      e.preventDefault();
      submit();
    }
  });

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      submit();
    });
  }
})();
