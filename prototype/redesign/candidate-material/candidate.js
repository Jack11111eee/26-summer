(function () {
  'use strict';

  var root = document.documentElement;
  var page = document.body;
  var toggle = document.querySelector('.theme-toggle');
  var toggleLabel = document.querySelector('.theme-toggle-label');
  var textarea = document.querySelector('#answer');
  var form = document.querySelector('.compose');
  var pointerLight = document.querySelector('.pointer-light');
  var caretLight = document.querySelector('.caret-light');
  var rippleLayer = document.querySelector('.ripple-layer');
  var statusMessage = document.querySelector('.status-message');
  var liveWord = document.querySelector('.live-word');
  var footerState = document.querySelector('.footer-state');
  var currentAnswer = document.querySelector('.answer-current');
  var answerPlaceholder = document.querySelector('.answer-placeholder');
  var answerTime = document.querySelector('.answer-time');
  var composing = false;
  var inputFocused = false;
  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var pointer = { x: 0, y: 0, pending: false };
  var caret = { x: 0, y: 0 };
  var caretPending = false;
  var caretRipplePending = false;
  var rippleCount = 0;
  var lastRipple = 0;
  var lastPointerRipple = { x: 0, y: 0 };
  var rafId = 0;
  var memoryTheme = null;
  var statusTimers = [];

  function readTheme() {
    var stored = null;
    try { stored = window.localStorage.getItem('candidate-material-theme'); } catch (error) { stored = memoryTheme; }
    if (stored === 'dark' || stored === 'light') return stored;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(theme, persist) {
    root.setAttribute('data-theme', theme);
    if (toggle) {
      toggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
      toggle.setAttribute('aria-label', theme === 'dark' ? '切换到日间主题' : '切换到夜间主题');
    }
    if (toggleLabel) toggleLabel.textContent = theme === 'dark' ? '日间' : '夜间';
    if (persist) {
      memoryTheme = theme;
      try { window.localStorage.setItem('candidate-material-theme', theme); } catch (error) { /* file:// or private mode: memory fallback */ }
    }
    hideLight(caretLight);
    if (theme !== 'dark') hideLight(pointerLight);
  }

  function hideLight(element) {
    if (element) element.style.opacity = '0';
  }

  function scheduleFrame() {
    if (!rafId) rafId = window.requestAnimationFrame(flushFrame);
  }

  function flushFrame() {
    rafId = 0;
    if (pointer.pending) {
      pointer.pending = false;
      pointerLight.style.transform = 'translate(' + pointer.x.toFixed(1) + 'px,' + pointer.y.toFixed(1) + 'px) translate(-50%, -50%)';
    }
    if (caretPending) {
      caretPending = false;
      updateCaretLight();
    }
    if (caretRipplePending) {
      caretRipplePending = false;
      makeRipple(caret.x, caret.y, true);
    }
  }

  function showPointerLight(x, y) {
    if (root.getAttribute('data-theme') !== 'dark' || inputFocused || reducedMotion.matches) return;
    pointer.x = x; pointer.y = y; pointer.pending = true;
    pointerLight.style.opacity = '.92';
    scheduleFrame();
  }

  function hidePointerLight() {
    pointerLight.style.opacity = '0';
  }

  function makeRipple(x, y, force) {
    if (root.getAttribute('data-theme') !== 'light' || reducedMotion.matches || rippleCount >= 10) return;
    var now = performance.now();
    var distance = Math.hypot(x - lastPointerRipple.x, y - lastPointerRipple.y);
    if (!force && now - lastRipple < 110 && distance < 26) return;
    lastRipple = now; lastPointerRipple.x = x; lastPointerRipple.y = y;
    var ripple = document.createElement('i');
    ripple.className = 'ripple';
    ripple.style.left = x + 'px'; ripple.style.top = y + 'px';
    rippleLayer.appendChild(ripple); rippleCount += 1;
    ripple.addEventListener('animationend', function () { ripple.remove(); rippleCount -= 1; }, { once: true });
  }

  function pointerMove(event) {
    if (event.pointerType && event.pointerType !== 'mouse') return;
    if (inputFocused) return;
    showPointerLight(event.clientX, event.clientY);
    if (root.getAttribute('data-theme') === 'light') makeRipple(event.clientX, event.clientY);
  }

  function pointerEnter(event) {
    if (!event.pointerType || event.pointerType === 'mouse') showPointerLight(event.clientX, event.clientY);
  }

  function pointerLeave(event) {
    if (!event.pointerType || event.pointerType === 'mouse') hidePointerLight();
  }

  function copyMirrorStyles(mirror, styles, width) {
    var properties = [
      'font-family', 'font-size', 'font-weight', 'font-style', 'font-variant', 'letter-spacing',
      'line-height', 'text-align', 'text-indent', 'text-transform', 'white-space', 'word-break',
      'overflow-wrap', 'tab-size', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
      'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width', 'box-sizing'
    ];
    properties.forEach(function (property) { mirror.style.setProperty(property, styles.getPropertyValue(property)); });
    mirror.style.position = 'fixed'; mirror.style.visibility = 'hidden'; mirror.style.pointerEvents = 'none';
    mirror.style.left = '0'; mirror.style.top = '0'; mirror.style.width = width + 'px';
    mirror.style.height = 'auto'; mirror.style.minHeight = '0'; mirror.style.overflow = 'visible';
    mirror.style.background = 'transparent';
  }

  function updateCaretLight() {
    if (!inputFocused || reducedMotion.matches) {
      hideLight(caretLight); return;
    }
    var styles = window.getComputedStyle(textarea);
    var rect = textarea.getBoundingClientRect();
    var mirror = document.querySelector('.caret-mirror');
    if (!mirror) {
      mirror = document.createElement('div'); mirror.className = 'caret-mirror';
      mirror.setAttribute('aria-hidden', 'true'); document.body.appendChild(mirror);
    }
    copyMirrorStyles(mirror, styles, textarea.clientWidth);
    var before = textarea.value.slice(0, textarea.selectionEnd);
    var after = textarea.value.slice(textarea.selectionEnd);
    mirror.textContent = '';
    mirror.appendChild(document.createTextNode(before));
    var marker = document.createElement('span');
    marker.textContent = '​'; marker.style.display = 'inline-block'; marker.style.width = '1px';
    mirror.appendChild(marker); mirror.appendChild(document.createTextNode(after || '​'));
    mirror.style.left = rect.left + 'px'; mirror.style.top = rect.top + 'px';
    var markerRect = marker.getBoundingClientRect();
    var x = markerRect.left;
    var y = markerRect.top + Math.max(8, markerRect.height / 2);
    caret.x = x; caret.y = y;
    if (root.getAttribute('data-theme') === 'dark') {
      caretLight.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) translate(-50%, -50%)';
      caretLight.style.opacity = '.9';
    } else {
      hideLight(caretLight);
    }
  }

  function scheduleCaret() { caretPending = true; scheduleFrame(); }

  function setStatus(message, word, footer) {
    if (statusMessage) statusMessage.textContent = message;
    if (liveWord) liveWord.textContent = word;
    if (footerState) footerState.textContent = footer;
  }

  function clearStatusTimers() {
    statusTimers.forEach(window.clearTimeout);
    statusTimers = [];
  }

  function nowTime() {
    return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date());
  }

  function submitAnswer() {
    var value = textarea.value.trim();
    if (!value || composing) return;
    clearStatusTimers();
    if (answerPlaceholder) answerPlaceholder.textContent = value;
    if (answerTime) answerTime.textContent = nowTime();
    if (currentAnswer) currentAnswer.style.display = 'block';
    textarea.value = '';
    setStatus('回答已保存。AI 正在理解你的回答。', '正在理解', '回答已保存');
    if (root.getAttribute('data-theme') === 'light') {
      caretRipplePending = true;
      scheduleCaret();
    }
    statusTimers.push(
      window.setTimeout(function () { setStatus('回答已保存。下一问正在准备中。', '准备下一问', '下一问准备中'); }, 1100),
      window.setTimeout(function () { setStatus('可以继续了。', '等待作答', '等待你的回答'); }, 2500)
    );
  }

  applyTheme(readTheme(), false);

  if (toggle) toggle.addEventListener('click', function () {
    applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark', true);
  });
  page.addEventListener('pointermove', pointerMove, { passive: true });
  page.addEventListener('pointerenter', pointerEnter, { passive: true });
  page.addEventListener('pointerleave', pointerLeave, { passive: true });
  window.addEventListener('blur', hidePointerLight);

  textarea.addEventListener('focus', function () {
    clearStatusTimers();
    inputFocused = true; hidePointerLight(); scheduleCaret();
    setStatus('可以开始作答。发送后会保存本次回答。', '等待作答', '发送后保存');
  });
  textarea.addEventListener('blur', function () {
    clearStatusTimers();
    inputFocused = false; hideLight(caretLight);
    if (textarea.value.trim()) {
      setStatus('草稿尚未发送。重新选中输入框可继续作答。', '等待发送', '草稿尚未发送');
    } else {
      setStatus('AI 会顺着你的思路继续追问。', '正在听', '发送后保存');
    }
  });
  textarea.addEventListener('compositionstart', function () { composing = true; scheduleCaret(); });
  textarea.addEventListener('compositionend', function () {
    composing = false;
    caretRipplePending = root.getAttribute('data-theme') === 'light';
    scheduleCaret();
  });
  ['input', 'click', 'select', 'keyup', 'scroll'].forEach(function (eventName) {
    textarea.addEventListener(eventName, function () {
      scheduleCaret();
      if (eventName === 'input') {
        clearStatusTimers();
        setStatus('正在编辑回答，发送后会保存。', '正在输入', '发送后保存');
      }
      if (eventName === 'input' && !composing && root.getAttribute('data-theme') === 'light') {
        caretRipplePending = true;
      }
    });
  });
  textarea.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !composing) {
      event.preventDefault(); submitAnswer();
    }
  });
  form.addEventListener('submit', function (event) { event.preventDefault(); submitAnswer(); });
  window.addEventListener('resize', scheduleCaret);
  var article = document.querySelector('.article');
  if (article) article.addEventListener('scroll', scheduleCaret, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(scheduleCaret).observe(textarea);
  if (reducedMotion.addEventListener) reducedMotion.addEventListener('change', function () { hidePointerLight(); hideLight(caretLight); });
})();
