/* chat.js — Chat panel logic with conversation memory */
(function() {
  'use strict';

  const panel = document.getElementById('chat-panel');
  const overlay = document.getElementById('chat-overlay');
  const toggleBtn = document.getElementById('btn-chat-toggle');
  const closeBtn = document.getElementById('chat-close');
  const clearBtn = document.getElementById('chat-clear');
  const messages = document.getElementById('chat-messages');
  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');

  let isOpen = false;
  let isSending = false;

  // Conversation history — persists for the session, sent with every request
  var conversationHistory = [];
  var MAX_HISTORY_TURNS = 20; // max user+assistant pairs kept

  function toggle() {
    isOpen = !isOpen;
    panel.classList.toggle('open', isOpen);
    overlay.classList.toggle('open', isOpen);
    if (isOpen) input.focus();
  }

  function clearConversation() {
    conversationHistory = [];
    messages.innerHTML = '';
    addMessage('Conversation cleared. Ask me anything.', 'assistant');
  }

  toggleBtn.addEventListener('click', toggle);
  closeBtn.addEventListener('click', toggle);
  overlay.addEventListener('click', toggle);
  if (clearBtn) clearBtn.addEventListener('click', clearConversation);

  function addMessage(text, role) {
    var div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    if (role === 'assistant' && typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      div.innerHTML = DOMPurify.sanitize(marked.parse(text));
    } else if (role === 'typing') {
      div.className = 'chat-msg loading';
      div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    } else {
      div.textContent = text;
    }
    messages.appendChild(div);
    messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
    return div;
  }

  function trimHistory() {
    // Keep at most MAX_HISTORY_TURNS pairs (user + assistant = 2 messages per turn)
    var maxMessages = MAX_HISTORY_TURNS * 2;
    if (conversationHistory.length > maxMessages) {
      conversationHistory = conversationHistory.slice(conversationHistory.length - maxMessages);
    }
  }

  // Core send: shared by typed chat and the voice layer (one brain, one thread).
  // Returns the reply text (or null). voiceFlag asks the server for the spoken register.
  async function sendText(text, voiceFlag) {
    if (!text || isSending) return null;

    addMessage(text, 'user');
    conversationHistory.push({ role: 'user', content: text });
    isSending = true;
    try { window.dispatchEvent(new CustomEvent('edith:chat', { detail: { phase: 'sent' } })); } catch (e) {}

    var loading = addMessage('', 'typing');

    try {
      var resp = await fetch('/dashboard/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: conversationHistory, voice: !!voiceFlag }),
      });
      var data = await resp.json();
      loading.remove();

      if (data.reply) {
        addMessage(data.reply, 'assistant');
        conversationHistory.push({ role: 'assistant', content: data.reply });
        trimHistory();
        try { window.dispatchEvent(new CustomEvent('edith:chat', { detail: { phase: 'reply' } })); } catch (e) {}
        return data.reply;
      } else if (data.error) {
        addMessage(data.error, 'error');
        try { window.dispatchEvent(new CustomEvent('edith:chat', { detail: { phase: 'error' } })); } catch (e) {}
      }
      return null;
    } catch (e) {
      loading.remove();
      addMessage('Failed to reach chat endpoint', 'error');
      return null;
    } finally {
      isSending = false;
    }
  }

  // ── sentence chunking for streaming TTS ──
  // Find the end index (inclusive) of the first complete sentence in s, or -1.
  // Guards decimals ("3.6", "$140,007.29") so they never split a number.
  function sentenceEnd(s, allowEnd) {
    var re = /[.!?…]/g, m;
    while ((m = re.exec(s))) {
      var i = m.index, prev = s[i - 1], next = s[i + 1];
      if (/\d/.test(prev) && /\d/.test(next)) continue;     // decimal point — skip
      if (next === undefined) { if (allowEnd) return i; else continue; }
      if (/[\s"')\]]/.test(next)) return i;                 // sentence truly ended
    }
    return -1;
  }
  // First audible word should come fast: if the opening sentence runs long with
  // no end yet, break at an early clause boundary (comma/semicolon/dash).
  function clauseBreak(s, minChars) {
    if (s.length < minChars) return -1;
    var re = /[,;:—–-]/g, m;
    while ((m = re.exec(s))) {
      if (m.index >= minChars && /\s/.test(s[m.index + 1] || ' ')) return m.index;
    }
    return -1;
  }

  // Streaming send: same thread/memory as sendText, but reads the reply as it is
  // generated and calls onChunk(sentence) at each boundary so the voice layer can
  // start speaking the first sentence immediately. Self-contained: on any stream
  // failure it falls back INLINE to the non-streaming /api/chat so history and
  // bubbles stay consistent. Returns { reply, chunked }:
  //   chunked=true  → sentences were emitted via onChunk (voice layer is mid-stream)
  //   chunked=false → reply produced without chunks (caller should speak it normally)
  //   reply=null    → hard failure.
  async function sendTextStream(text, voiceFlag, onChunk) {
    if (!text || isSending) return { reply: null, chunked: false };
    addMessage(text, 'user');
    conversationHistory.push({ role: 'user', content: text });
    isSending = true;
    try { window.dispatchEvent(new CustomEvent('edith:chat', { detail: { phase: 'sent' } })); } catch (e) {}
    var loading = addMessage('', 'typing');

    var full = '';
    var buffer = '';
    var firstDone = false;
    var anyChunk = false;
    function drain(flush) {
      while (true) {
        var idx = sentenceEnd(buffer, flush);
        if (idx < 0 && !firstDone) idx = clauseBreak(buffer, 24);   // fast first word
        if (idx < 0 && flush && buffer.trim()) {
          onChunk(buffer.trim()); buffer = ''; firstDone = true; anyChunk = true; break;
        }
        if (idx < 0) break;
        var chunk = buffer.slice(0, idx + 1).trim();
        buffer = buffer.slice(idx + 1);
        if (chunk) { onChunk(chunk); firstDone = true; anyChunk = true; }
      }
    }

    function renderAssistant(replyText) {
      addMessage(replyText, 'assistant');
      conversationHistory.push({ role: 'assistant', content: replyText });
      trimHistory();
      try { window.dispatchEvent(new CustomEvent('edith:chat', { detail: { phase: 'reply' } })); } catch (e) {}
    }

    // Inline fallback to the proven non-streaming endpoint. History already holds
    // the user turn, so just POST it and render. Returns the reply or null.
    async function fallback() {
      try {
        var fr = await fetch('/dashboard/api/chat', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ history: conversationHistory, voice: !!voiceFlag }),
        });
        var fd = await fr.json();
        if (fd.reply) { renderAssistant(fd.reply); return fd.reply; }
        if (fd.error) {
          addMessage(fd.error, 'error');
          try { window.dispatchEvent(new CustomEvent('edith:chat', { detail: { phase: 'error' } })); } catch (e) {}
        }
      } catch (e2) {}
      return null;
    }

    try {
      var resp = await fetch('/dashboard/api/chat-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: conversationHistory, voice: !!voiceFlag }),
      });
      if (!resp.ok || !resp.body) throw new Error('stream unavailable');

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var sseBuf = '';
      var errored = null;
      while (true) {
        var rd = await reader.read();
        if (rd.done) break;
        sseBuf += decoder.decode(rd.value, { stream: true });
        var parts = sseBuf.split('\n\n');
        sseBuf = parts.pop();                    // keep trailing partial frame
        for (var p = 0; p < parts.length; p++) {
          var ev = (parts[p].match(/^event:\s*(.+)$/m) || [])[1];
          var dataLine = (parts[p].match(/^data:\s*([\s\S]+)$/m) || [])[1];
          if (!ev || !dataLine) continue;
          var payload; try { payload = JSON.parse(dataLine); } catch (e) { continue; }
          if (ev === 'delta' && payload.text) { full += payload.text; buffer += payload.text; drain(false); }
          else if (ev === 'done') { full = payload.reply || full; }
          else if (ev === 'error') { errored = payload.error || 'stream error'; }
        }
      }
      drain(true);                               // flush any trailing partial sentence
      loading.remove();

      if (full) { renderAssistant(full); return { reply: full, chunked: anyChunk }; }
      if (errored) {                             // server-side error, no text → fall back
        var fb = await fallback();
        return { reply: fb, chunked: false };
      }
      return { reply: null, chunked: false };
    } catch (e) {
      loading.remove();
      var fb2 = await fallback();               // transport failed → non-streaming
      return { reply: fb2, chunked: false };
    } finally {
      isSending = false;
    }
  }

  async function send() {
    var text = input.value.trim();
    if (!text || isSending) return;
    input.value = '';
    input.style.height = 'auto';
    await sendText(text, false);
  }

  // Public hook for the voice layer (voice.js): same thread, same memory.
  window.JarvisChat = {
    ask: sendText,
    askStream: sendTextStream,
    addAssistantMessage: function(text) {
      addMessage(text, 'assistant');
      conversationHistory.push({ role: 'assistant', content: text });
      trimHistory();
    },
    openPanel: function() { if (!isOpen) toggle(); },
    isBusy: function() { return isSending; },
  };

  sendBtn.addEventListener('click', send);

  // Suggested-question chips (rendered by dashboard.js, handled here)
  var chipsWrap = document.getElementById('chat-chips');
  if (chipsWrap) {
    chipsWrap.addEventListener('click', function(e) {
      var chip = e.target.closest('.chat-chip');
      if (!chip) return;
      input.value = chip.dataset.q || chip.textContent;
      if (!isOpen) toggle();
      send();
    });
  }

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  input.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

})();
