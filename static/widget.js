(function () {
  "use strict";

  var script = document.currentScript;
  var apiBase = (
    (script && script.getAttribute("data-api-base")) ||
    window.TOWARDS_AI_HELPER_API_BASE ||
    ""
  ).replace(/\/+$/, "");
  if (!apiBase && script && script.src) {
    try {
      apiBase = new URL(script.src).origin;
    } catch (_error) {
      apiBase = "";
    }
  }
  if (!apiBase) return;

  var state = {
    config: null,
    visible: false,
    open: false,
    streaming: false,
    threadId: "",
    messages: [],
    firstMessageSent: false,
    visitorId: visitorId(),
  };

  var root = document.createElement("div");
  root.id = "towards-ai-helper-widget";
  var shadow = root.attachShadow({ mode: "open" });
  document.documentElement.appendChild(root);

  shadow.innerHTML = [
    "<style>",
    ":host{all:initial;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#182235}",
    ".wrap{position:fixed;right:20px;bottom:20px;z-index:2147483000}",
    ".bubble{height:46px;min-width:146px;border:0;border-radius:999px;background:#182235;color:#fff;box-shadow:0 14px 34px rgba(24,34,53,.28);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:9px;padding:0 16px 0 13px;font:750 14px/1 system-ui;letter-spacing:0}",
    ".bubble:hover{background:#24324b;transform:translateY(-1px)}",
    ".bubble-mark{width:24px;height:24px;border-radius:999px;background:#11b7ba;color:#082c33;display:flex;align-items:center;justify-content:center;font:800 15px/1 system-ui}",
    ".panel{width:min(414px,calc(100vw - 32px));height:min(650px,calc(100vh - 96px));background:#fff;border:1px solid #d7e0ea;border-radius:14px;box-shadow:0 20px 70px rgba(24,34,53,.24);display:flex;flex-direction:column;overflow:hidden}",
    ".head{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 14px 0 16px;border-bottom:1px solid #e7edf4;background:#fbfcfe}",
    ".brand{min-width:0;display:flex;align-items:center;gap:10px}",
    ".brand-mark{width:32px;height:32px;border-radius:8px;background:#182235;color:#fff;display:flex;align-items:center;justify-content:center;font:800 12px/1 system-ui}",
    ".title{font:750 15px/1.2 system-ui;color:#182235;letter-spacing:0}",
    ".subtitle{font:600 12px/1.25 system-ui;color:#64748b;max-width:285px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}",
    ".iconbtn{width:34px;height:34px;flex:0 0 auto;border:0;border-radius:9px;background:#eef3f8;color:#475569;cursor:pointer;font:800 20px/1 system-ui}",
    ".iconbtn:hover{background:#e2eaf3;color:#182235}",
    ".msgs{flex:1;overflow:auto;padding:16px;background:#fff;display:flex;flex-direction:column;gap:12px}",
    ".msg{max-width:88%;padding:11px 13px;border-radius:11px;font:400 14px/1.48 system-ui;overflow-wrap:anywhere}",
    ".user{align-self:flex-end;background:#182235;color:#fff;border-bottom-right-radius:4px}",
    ".assistant{align-self:flex-start;background:#f3f7fb;color:#182235;border:1px solid #e7edf4;border-bottom-left-radius:4px}",
    ".assistant.empty{color:#64748b;font-style:italic}",
    ".meta{align-self:flex-start;color:#64748b;font:600 12px/1.35 system-ui;background:#f8fafc;border:1px solid #edf2f7;border-radius:999px;padding:6px 10px}",
    ".prompts{display:flex;flex-direction:column;gap:8px;align-self:stretch}",
    ".prompt{border:1px solid #d7e0ea;border-radius:10px;background:#fff;color:#182235;text-align:left;padding:10px 11px;font:700 13px/1.35 system-ui;cursor:pointer}",
    ".prompt:hover{border-color:#11a7b0;background:#f2fbfc}",
    ".prompt:disabled{opacity:.55;cursor:not-allowed}",
    ".sources{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}",
    ".source{font:700 11px/1.2 system-ui;color:#087e8b;background:#e8f8f9;border-radius:999px;padding:5px 8px;text-decoration:none}",
    ".md{white-space:normal}",
    ".md p{margin:0 0 10px}",
    ".md p:last-child{margin-bottom:0}",
    ".md ol,.md ul{margin:8px 0 10px 20px;padding:0}",
    ".md li{margin:5px 0;padding-left:2px}",
    ".md a{color:#087e8b;text-decoration:underline;text-underline-offset:2px;font-weight:650}",
    ".md code{background:#e8eef5;border:1px solid #d9e3ee;border-radius:5px;padding:1px 4px;font:500 12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}",
    ".md strong{font-weight:760}",
    ".form{display:flex;gap:9px;padding:12px;border-top:1px solid #e7edf4;background:#fbfcfe}",
    ".input{flex:1;resize:none;min-height:44px;max-height:116px;border:1px solid #c8d3df;border-radius:11px;padding:11px 12px;font:400 14px/1.35 system-ui;outline:none;background:#fff;color:#182235}",
    ".input:focus{border-color:#11a7b0;box-shadow:0 0 0 3px rgba(17,167,176,.16)}",
    ".send{width:46px;flex:0 0 46px;border:0;border-radius:11px;background:#182235;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center}",
    ".send:hover{background:#24324b}",
    ".send:disabled{opacity:.45;cursor:not-allowed}",
    ".send svg{width:18px;height:18px;display:block}",
    ".hidden{display:none!important}",
    "@media(max-width:520px){.wrap{right:12px;bottom:12px}.panel{width:calc(100vw - 24px);height:calc(100vh - 86px)}.subtitle{max-width:220px}.bubble{min-width:136px}}",
    "</style>",
    "<div class='wrap hidden' data-wrap>",
    "  <button class='bubble' data-bubble aria-label='Ask the helper'><span class='bubble-mark'>?</span><span>Ask the helper</span></button>",
    "  <section class='panel hidden' data-panel aria-label='Towards AI helper chat'>",
    "    <header class='head'>",
    "      <div class='brand'><div class='brand-mark'>TA</div><div><div class='title'>Towards AI Helper</div><div class='subtitle' data-subtitle></div></div></div>",
    "      <button class='iconbtn' data-close aria-label='Minimize helper' title='Minimize'>&minus;</button>",
    "    </header>",
    "    <div class='msgs' data-msgs><div class='meta'>Choose a starter prompt.</div><div class='prompts' data-prompts></div></div>",
    "    <form class='form hidden' data-form>",
    "      <textarea class='input' data-input rows='1' placeholder='Ask a follow-up' data-gramm='false' data-gramm_editor='false' data-enable-grammarly='false'></textarea>",
    "      <button class='send' data-send type='submit' aria-label='Send message'><svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 12h14M13 6l6 6-6 6' fill='none' stroke='currentColor' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/></svg></button>",
    "    </form>",
    "  </section>",
    "</div>",
  ].join("");

  var wrap = shadow.querySelector("[data-wrap]");
  var bubble = shadow.querySelector("[data-bubble]");
  var panel = shadow.querySelector("[data-panel]");
  var closeBtn = shadow.querySelector("[data-close]");
  var form = shadow.querySelector("[data-form]");
  var input = shadow.querySelector("[data-input]");
  var sendBtn = shadow.querySelector("[data-send]");
  var msgs = shadow.querySelector("[data-msgs]");
  var prompts = shadow.querySelector("[data-prompts]");
  var subtitle = shadow.querySelector("[data-subtitle]");

  function safeString(value) {
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function escapeHtml(value) {
    return safeString(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeHref(value) {
    try {
      var candidate = safeString(value).trim();
      if (/^www\./i.test(candidate)) candidate = "https://" + candidate;
      var url = new URL(candidate, window.location.href);
      if (url.protocol === "http:" || url.protocol === "https:") return url.href;
    } catch (_error) {}
    return "";
  }

  function displayUrl(value) {
    return safeString(value).replace(/^https?:\/\//i, "").replace(/\/$/, "");
  }

  function splitTrailingUrlPunctuation(value) {
    var url = safeString(value);
    var suffix = "";
    while (/[.,;:!?]$/.test(url)) {
      suffix = url.slice(-1) + suffix;
      url = url.slice(0, -1);
    }
    while (
      url.slice(-1) === ")" &&
      (url.match(/\)/g) || []).length > (url.match(/\(/g) || []).length
    ) {
      suffix = ")" + suffix;
      url = url.slice(0, -1);
    }
    return { url: url, suffix: suffix };
  }

  function renderBasicMarkdown(text) {
    return escapeHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function renderInlineMarkdown(text) {
    var output = "";
    var lastIndex = 0;
    var linkPattern =
      /\[([^\]]{1,180})\]\(((?:https?:\/\/|www\.)[^)\s]+)\)|\[((?:https?:\/\/|www\.)[^\]\s]+)\]|((?:https?:\/\/|www\.)[^\s<]+)/g;
    var match;
    while ((match = linkPattern.exec(text)) !== null) {
      output += renderBasicMarkdown(text.slice(lastIndex, match.index));
      var rawUrl = match[2] || match[3] || match[4] || "";
      var suffix = "";
      if (!match[2]) {
        var splitUrl = splitTrailingUrlPunctuation(rawUrl);
        rawUrl = splitUrl.url;
        suffix = splitUrl.suffix;
      }
      var href = safeHref(rawUrl);
      if (href) {
        output +=
          "<a href='" +
          escapeHtml(href) +
          "' target='_blank' rel='noopener noreferrer'>" +
          (match[1] ? renderBasicMarkdown(match[1]) : escapeHtml(displayUrl(rawUrl))) +
          "</a>";
        if (suffix) output += renderBasicMarkdown(suffix);
      } else {
        output += renderBasicMarkdown(match[0]);
      }
      lastIndex = match.index + match[0].length;
    }
    output += renderBasicMarkdown(text.slice(lastIndex));
    return output;
  }

  function isListLine(line) {
    return /^\s*(?:[-*]\s+|\d+\.\s+)/.test(line);
  }

  function renderMarkdown(markdown) {
    var lines = safeString(markdown).replace(/\r\n/g, "\n").split("\n");
    var html = [];
    var index = 0;
    while (index < lines.length) {
      var line = lines[index];
      var trimmed = line.trim();
      if (!trimmed) {
        index += 1;
        continue;
      }
      if (isListLine(line)) {
        var ordered = /^\s*\d+\.\s+/.test(line);
        var tag = ordered ? "ol" : "ul";
        var items = [];
        while (index < lines.length && isListLine(lines[index])) {
          items.push(
            "<li>" +
              renderInlineMarkdown(lines[index].replace(/^\s*(?:[-*]\s+|\d+\.\s+)/, "")) +
              "</li>",
          );
          index += 1;
        }
        html.push("<" + tag + ">" + items.join("") + "</" + tag + ">");
        continue;
      }
      var paragraph = [trimmed];
      index += 1;
      while (index < lines.length && lines[index].trim() && !isListLine(lines[index])) {
        paragraph.push(lines[index].trim());
        index += 1;
      }
      html.push("<p>" + renderInlineMarkdown(paragraph.join(" ")) + "</p>");
    }
    return "<div class='md'>" + html.join("") + "</div>";
  }

  function visitorId() {
    try {
      var key = "towards_ai_helper_visitor";
      var existing = window.localStorage.getItem(key);
      if (existing) return existing;
      var id =
        Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
      window.localStorage.setItem(key, id);
      return id;
    } catch (_error) {
      return "";
    }
  }

  function normalizePath(pathname) {
    var path = pathname || "/";
    path = path.replace(/\/+$/, "");
    return path || "/";
  }

  function isSignedIn() {
    try {
      if (window.Thinkific && window.Thinkific.current_user) return true;
      if (document.body && document.body.classList.contains("logged-in")) return true;
      if (document.getElementById("wpadminbar")) return true;
      if (/wordpress_logged_in|thinkific_user|signed_in/i.test(document.cookie || "")) {
        return true;
      }
      var signOutLink = document.querySelector(
        "a[href*='sign_out'],a[href*='logout'],a[href*='/account']",
      );
      return Boolean(signOutLink && /sign out|logout|account/i.test(signOutLink.textContent || ""));
    } catch (_error) {
      return false;
    }
  }

  function isBlockedPath() {
    var path = normalizePath(window.location.pathname);
    return /^(courses\/take|enroll|order|checkout|cart|users|account|admin)/.test(
      path.replace(/^\//, ""),
    );
  }

  function pageAllowed(config) {
    if (!config || isSignedIn() || isBlockedPath()) return false;
    var host = window.location.hostname.toLowerCase();
    var path = normalizePath(window.location.pathname);
    var paths = config.allowedPathsByHost && config.allowedPathsByHost[host];
    if (!paths && host.indexOf("www.") === 0) {
      paths = config.allowedPathsByHost && config.allowedPathsByHost[host.slice(4)];
    }
    return Array.isArray(paths) && paths.indexOf(path) !== -1;
  }

  function setVisible(visible) {
    state.visible = visible;
    wrap.classList.toggle("hidden", !visible);
    if (!visible) {
      state.open = false;
      panel.classList.add("hidden");
      bubble.classList.remove("hidden");
    }
  }

  function setOpen(open) {
    state.open = open;
    panel.classList.toggle("hidden", !open);
    bubble.classList.toggle("hidden", open);
    if (open) setTimeout(function () { input.focus(); }, 50);
  }

  function contextPayload() {
    return {
      url: window.location.href.split("#", 1)[0],
      pageTitle: document.title || "",
      referrer: document.referrer || "",
      signedIn: isSignedIn(),
    };
  }

  function appendMessage(role, text, sources) {
    var node = document.createElement("div");
    node.className = "msg " + (role === "user" ? "user" : "assistant");
    node.innerHTML = role === "assistant" ? renderMarkdown(text) : escapeHtml(text);
    if (role === "assistant" && sources && sources.length) {
      var sourceWrap = document.createElement("div");
      sourceWrap.className = "sources";
      sources.slice(0, 3).forEach(function (source) {
        var a = document.createElement("a");
        a.className = "source";
        a.href = source.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = source.title || source.kind || "Source";
        sourceWrap.appendChild(a);
      });
      node.appendChild(sourceWrap);
    }
    msgs.appendChild(node);
    msgs.scrollTop = msgs.scrollHeight;
    return node;
  }

  function setBusy(busy) {
    state.streaming = busy;
    sendBtn.disabled = busy;
    input.disabled = busy;
    Array.prototype.forEach.call(prompts.querySelectorAll("button"), function (button) {
      button.disabled = busy || state.firstMessageSent;
    });
  }

  function showInput() {
    form.classList.toggle("hidden", !state.firstMessageSent);
  }

  function send(text, selectedPrompt) {
    text = safeString(text).trim();
    if (!text || state.streaming) return;
    appendMessage("user", text);
    state.messages.push({ role: "user", content: text });
    setBusy(true);
    var loading = appendMessage("assistant", "Thinking...");
    loading.classList.add("empty");

    fetch(apiBase + "/api/helper/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: text,
        selectedPrompt: selectedPrompt || "",
        visitorId: state.visitorId,
        threadId: state.threadId,
        history: state.messages.slice(0, -1).slice(-8),
        context: contextPayload(),
      }),
    })
      .then(function (response) {
        if (!response.ok) {
          if (response.status === 429) {
            throw new Error("The helper is rate limited right now. Please try again later.");
          }
          throw new Error("The helper is unavailable on this page.");
        }
        return response.json();
      })
      .then(function (payload) {
        state.threadId = payload.threadId || state.threadId;
        loading.classList.remove("empty");
        loading.innerHTML = renderMarkdown(payload.answer || "I could not answer that.");
        if (payload.sources && payload.sources.length) {
          var sourceWrap = document.createElement("div");
          sourceWrap.className = "sources";
          payload.sources.slice(0, 3).forEach(function (source) {
            var a = document.createElement("a");
            a.className = "source";
            a.href = source.url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = source.title || source.kind || "Source";
            sourceWrap.appendChild(a);
          });
          loading.appendChild(sourceWrap);
        }
        state.messages.push({ role: "assistant", content: payload.answer || "" });
        state.firstMessageSent = true;
        prompts.classList.add("hidden");
        showInput();
      })
      .catch(function (error) {
        loading.classList.remove("empty");
        loading.innerHTML = renderMarkdown(error.message || "Something went wrong.");
      })
      .finally(function () {
        setBusy(false);
        input.value = "";
        input.style.height = "auto";
        msgs.scrollTop = msgs.scrollHeight;
      });
  }

  function renderPrompts() {
    prompts.innerHTML = "";
    (state.config.forcedPrompts || []).forEach(function (text) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "prompt";
      button.textContent = text;
      button.addEventListener("click", function () {
        send(text, text);
      });
      prompts.appendChild(button);
    });
  }

  bubble.addEventListener("click", function () {
    setOpen(true);
  });
  closeBtn.addEventListener("click", function () {
    setOpen(false);
  });
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    send(input.value, "");
  });
  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 116) + "px";
  });

  function refreshVisibility() {
    if (!state.config) return;
    setVisible(pageAllowed(state.config));
  }

  function init() {
    fetch(apiBase + "/api/helper/config")
      .then(function (response) { return response.json(); })
      .then(function (config) {
        state.config = config;
        subtitle.textContent = document.title || "Course and training guidance";
        renderPrompts();
        showInput();
        refreshVisibility();
      })
      .catch(function () {
        setVisible(false);
      });
  }

  window.addEventListener("thnc.current_user-initialized", refreshVisibility);
  setTimeout(refreshVisibility, 1000);
  init();
})();
