/* chat.js — Chat panel logic */
(function() {
  'use strict';

  const panel = document.getElementById('chat-panel');
  const overlay = document.getElementById('chat-overlay');
  const toggleBtn = document.getElementById('btn-chat-toggle');
  const closeBtn = document.getElementById('chat-close');
  const messages = document.getElementById('chat-messages');
  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send');

  let isOpen = false;
  let isSending = false;

  function toggle() {
    isOpen = !isOpen;
    panel.classList.toggle('open', isOpen);
    overlay.classList.toggle('open', isOpen);
    if (isOpen) input.focus();
  }

  toggleBtn.addEventListener('click', toggle);
  closeBtn.addEventListener('click', toggle);
  overlay.addEventListener('click', toggle);

  function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  async function send() {
    const text = input.value.trim();
    if (!text || isSending) return;

    addMessage(text, 'user');
    input.value = '';
    input.style.height = 'auto';
    isSending = true;

    const loading = addMessage('Thinking...', 'loading');

    try {
      const resp = await fetch('/dashboard/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await resp.json();
      loading.remove();

      if (data.reply) {
        addMessage(data.reply, 'assistant');
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
