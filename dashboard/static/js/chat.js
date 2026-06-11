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

  async function send() {
    var text = input.value.trim();
    if (!text || isSending) return;

    addMessage(text, 'user');
    conversationHistory.push({ role: 'user', content: text });
    input.value = '';
    input.style.height = 'auto';
    isSending = true;

    var loading = addMessage('', 'typing');

    try {
      var resp = await fetch('/dashboard/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: conversationHistory }),
      });
      var data = await resp.json();
      loading.remove();

      if (data.reply) {
        addMessage(data.reply, 'assistant');
        conversationHistory.push({ role: 'assistant', content: data.reply });
        trimHistory();
      } else if (data.error) {
        addMessage(data.error, 'error');
      }
    } catch (e) {
      loading.remove();
      addMessage('Failed to reach chat endpoint', 'error');
    } finally {
      isSending = false;
    }
  }

  sendBtn.addEventListener('click', send);

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
