/* Samy — ApexPayGo's floating AI assistant.
   Self-contained: injects a button + chat panel, talks to /api/assistant.
   Only appears for signed-in users. Bilingual (reads localStorage 'lang'). */
(function () {
  if (!localStorage.getItem('authToken')) return; // only for signed-in users

  function lang() { return localStorage.getItem('lang') === 'en' ? 'en' : 'fr'; }
  var STR = {
    fr: {
      title: 'NICO — Assistant', open: 'Ouvrir l\'assistant NICO',
      placeholder: 'Posez une question sur la paie…', send: 'Envoyer',
      hello: "Bonjour! Je suis NICO, votre assistant paie. Comment puis-je vous aider?",
      thinking: 'NICO écrit…', error: "Désolé, une erreur s'est produite. Réessayez."
    },
    en: {
      title: 'NICO — Assistant', open: 'Open the NICO assistant',
      placeholder: 'Ask a payroll question…', send: 'Send',
      hello: "Hi! I'm NICO, your payroll assistant. How can I help?",
      thinking: 'NICO is typing…', error: 'Sorry, something went wrong. Please try again.'
    }
  };
  function t(k) { return (STR[lang()] || STR.fr)[k]; }

  var convo = [];   // {role, content}
  var openState = false;

  var style = document.createElement('style');
  style.textContent =
    '#samy-btn{position:fixed;bottom:22px;right:22px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);font-size:26px;z-index:4000;display:flex;align-items:center;justify-content:center}' +
    '#samy-panel{position:fixed;bottom:92px;right:22px;width:340px;max-width:calc(100vw - 32px);height:460px;max-height:calc(100vh - 130px);background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.28);z-index:4000;display:none;flex-direction:column;overflow:hidden}' +
    '#samy-panel.open{display:flex}' +
    '#samy-head{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:12px 14px;font-weight:700;display:flex;justify-content:space-between;align-items:center}' +
    '#samy-head button{background:none;border:none;color:#fff;font-size:20px;cursor:pointer}' +
    '#samy-msgs{flex:1;overflow-y:auto;padding:12px;background:#f5f7fa}' +
    '.samy-m{margin-bottom:10px;display:flex}' +
    '.samy-m .b{padding:8px 12px;border-radius:12px;font-size:14px;line-height:1.4;max-width:82%;white-space:pre-wrap;word-wrap:break-word}' +
    '.samy-user{justify-content:flex-end}.samy-user .b{background:#1e40af;color:#fff;border-bottom-right-radius:4px}' +
    '.samy-bot .b{background:#fff;color:#1f2937;border:1px solid #e2e8f0;border-bottom-left-radius:4px}' +
    '#samy-form{display:flex;border-top:1px solid #e2e8f0;padding:8px;gap:6px;background:#fff}' +
    '#samy-input{flex:1;padding:9px 10px;border:2px solid #e2e8f0;border-radius:8px;font-size:14px;outline:none}' +
    '#samy-form button{background:#1e40af;color:#fff;border:none;border-radius:8px;padding:0 14px;font-weight:600;cursor:pointer}' +
    '#samy-form button:disabled{background:#cbd5e1;cursor:not-allowed}';
  document.head.appendChild(style);

  var btn = document.createElement('button');
  btn.id = 'samy-btn'; btn.title = t('open'); btn.textContent = '💬';
  var panel = document.createElement('div');
  panel.id = 'samy-panel';
  panel.innerHTML =
    '<div id="samy-head"><span id="samy-title"></span><button id="samy-close" aria-label="close">×</button></div>' +
    '<div id="samy-msgs"></div>' +
    '<form id="samy-form"><input id="samy-input" autocomplete="off"><button type="submit" id="samy-send"></button></form>';

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  var msgs = panel.querySelector('#samy-msgs');
  var input = panel.querySelector('#samy-input');
  var sendBtn = panel.querySelector('#samy-send');

  function applyLabels() {
    panel.querySelector('#samy-title').textContent = t('title');
    input.placeholder = t('placeholder');
    sendBtn.textContent = t('send');
    btn.title = t('open');
  }
  applyLabels();
  document.addEventListener('langchange', applyLabels);

  function bubble(role, text) {
    var row = document.createElement('div');
    row.className = 'samy-m ' + (role === 'user' ? 'samy-user' : 'samy-bot');
    var b = document.createElement('div');
    b.className = 'b'; b.textContent = text;
    row.appendChild(b); msgs.appendChild(row);
    msgs.scrollTop = msgs.scrollHeight;
    return b;
  }

  function toggle(show) {
    openState = (show === undefined) ? !openState : show;
    panel.classList.toggle('open', openState);
    if (openState) {
      if (!msgs.children.length) bubble('bot', t('hello'));
      input.focus();
    }
  }
  btn.addEventListener('click', function () { toggle(); });
  panel.querySelector('#samy-close').addEventListener('click', function () { toggle(false); });

  panel.querySelector('#samy-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    bubble('user', text);
    convo.push({ role: 'user', content: text });

    sendBtn.disabled = true;
    var typing = bubble('bot', t('thinking'));

    fetch('/api/assistant', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (localStorage.getItem('authToken') || '')
      },
      body: JSON.stringify({ messages: convo, lang: lang() })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var reply = data.reply || data.error || t('error');
        typing.textContent = reply;
        convo.push({ role: 'assistant', content: reply });
      })
      .catch(function () { typing.textContent = t('error'); })
      .finally(function () { sendBtn.disabled = false; input.focus(); });
  });
})();
