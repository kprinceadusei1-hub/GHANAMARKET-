// Live chat: send without reloading, fetch new messages every few seconds, show "Seen".
(() => {
  const thread = document.querySelector("[data-chat-thread]");
  if (!thread) return;
  const form = document.querySelector("[data-chat-form]");
  const errorBox = document.querySelector("[data-chat-error]");
  const seen = thread.querySelector("[data-chat-seen]");
  const pollUrl = thread.dataset.pollUrl;
  let seenUntil = thread.dataset.seenUntil || "";
  let busy = false;
  let stopped = false;

  const lastId = () => {
    const items = thread.querySelectorAll(".chat-message[data-id]");
    return items.length ? Number(items[items.length - 1].dataset.id) : 0;
  };
  const lastDay = () => {
    const items = thread.querySelectorAll(".chat-message[data-day]");
    return items.length ? items[items.length - 1].dataset.day : "";
  };
  const nearBottom = () => thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
  const toBottom = () => { thread.scrollTop = thread.scrollHeight; };

  function render(message) {
    if (thread.querySelector(`.chat-message[data-id="${message.id}"]`)) return;
    thread.querySelector("[data-chat-empty]")?.remove();
    if (message.day !== lastDay()) {
      const day = document.createElement("p");
      day.className = "chat-day";
      day.textContent = message.day;
      thread.insertBefore(day, seen);
    }
    const article = document.createElement("article");
    article.className = "chat-message" + (message.mine ? " own-message" : "");
    article.dataset.id = message.id;
    article.dataset.day = message.day;
    article.dataset.iso = message.iso;
    const body = document.createElement("p");
    message.body.split("\n").forEach((line, index) => {
      if (index) body.appendChild(document.createElement("br"));
      body.appendChild(document.createTextNode(line));
    });
    const time = document.createElement("time");
    time.dateTime = message.iso;
    time.textContent = message.time;
    article.append(body, time);
    thread.insertBefore(article, seen);
  }

  function updateSeen() {
    const mine = thread.querySelectorAll(".chat-message.own-message[data-iso]");
    const last = mine[mine.length - 1];
    const lastOverall = thread.querySelectorAll(".chat-message");
    const isLast = last && lastOverall[lastOverall.length - 1] === last;
    seen.hidden = !(isLast && seenUntil && new Date(seenUntil) >= new Date(last.dataset.iso));
  }

  function showError(text) {
    errorBox.textContent = text || "";
    errorBox.hidden = !text;
  }

  async function poll() {
    if (busy) return;
    busy = true;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      const response = await fetch(`${pollUrl}?after=${lastId()}`, {
        headers: { "X-Requested-With": "fetch" }, signal: controller.signal,
      });
      clearTimeout(timeout);
      if (response.redirected || !(response.headers.get("Content-Type") || "").includes("application/json")) {
        stopped = true;
        showError("You have been signed out. Refresh the page and sign in to keep chatting.");
        busy = false;
        return;
      }
      if (response.ok) {
        const data = await response.json();
        const stick = nearBottom();
        data.messages.forEach(render);
        seenUntil = data.seen_until || seenUntil;
        updateSeen();
        if (stick && data.messages.length) toBottom();
      }
    } catch (error) { /* offline: try again next tick */ }
    busy = false;
  }

  if (form) {
    const textarea = form.querySelector("textarea");
    const button = form.querySelector('button[type="submit"]');
    textarea?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!textarea.value.trim()) return;
      button.disabled = true;
      showError("");
      try {
        const response = await fetch(form.action || window.location.href, {
          method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" },
        });
        const data = await response.json().catch(() => ({}));
        if (response.ok && data.message) {
          render(data.message);
          textarea.value = "";
          updateSeen();
          toBottom();
        } else {
          showError(data.error || "Your message was not sent. Please try again.");
        }
      } catch (error) {
        showError("No connection. Your message was not sent.");
      }
      button.disabled = false;
      textarea.focus();
    });
  }

  toBottom();
  updateSeen();
  const tick = () => { if (stopped) return; poll(); setTimeout(tick, document.hidden ? 20000 : 4000); };
  setTimeout(tick, 4000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
