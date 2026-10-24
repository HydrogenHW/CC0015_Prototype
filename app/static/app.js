/**
 * 前端：采集麦克风 → PCM → WebSocket；接收字幕 → 渲染。
 *
 * 几个必须守住的点：
 *   - 只在 127.0.0.1 / localhost 下跑，否则浏览器不给麦克风
 *   - 采样率由后端决定（OpenAI 要 24 kHz，Deepgram 要 16 kHz），
 *     启动时从 /health 读，别写死
 *   - 重采样先降采样再取平均，不能直接抽样，否则混叠成噪声
 *   - 写字幕一律用 textContent，外部数据不能当 HTML 解析
 */
(() => {
  "use strict";

  // 默认值只是兜底，真正用哪个由后端 /health 给
  let TARGET_RATE = 24000;
  let FRAME_SAMPLES = 2400;    // 100 ms

  // 浏览器自带的降噪/回声消除是为通话设计的，会削掉语音里的弱成分，
  // 对识别不一定是好事。做成 URL 开关，方便同一句话反复对比：
  //   ?ns=0    关降噪      ?aec=0  关回声消除      ?agc=0  关自动增益
  const params = new URLSearchParams(location.search);
  const audioOpts = {
    channelCount: 1,
    echoCancellation: params.get("aec") !== "0",
    noiseSuppression: params.get("ns") !== "0",
    autoGainControl: params.get("agc") !== "0",
  };

  const el = {
    toggle: document.getElementById("toggle"),
    status: document.getElementById("status"),
    scroll: document.getElementById("scroll"),
    interim: document.getElementById("interim"),
    level: document.getElementById("level"),
    dirs: Array.from(document.querySelectorAll(".dir")),
  };

  const state = {
    running: false,
    dir: "zh",
    ws: null,
    ctx: null,
    mic: null,
    node: null,
    pending: new Float32Array(0),
    ratio: 1,
    retryTimer: null,
    retries: 0,
    firstRow: true,
  };

  // ------------------------------------------------------------ 文案
  //
  // 界面语言跟着翻译方向走：中文课就用中文界面，英文课就用英文界面。
  // 有些值是函数，用来拼带变量的提示。
  const I18N = {
    zh: {
      title: "实时字幕",
      brand: "实时字幕",
      dir_zh: "中文 → EN",
      dir_en: "EN → 中文",
      preset: "预设",
      start: "开始",
      stop: "停止",
      assistant: "术语助手",
      clear: "清空",
      send: "发送",
      cancel: "取消",
      empty: "点「开始」，允许麦克风权限，字幕会从下一句开始出现。",
      chat_tip: "可以问译法、术语含义，也能说「把某某加进热词」。",
      chat_placeholder: "问术语或译法…",
      foot: "空格 开始 / 停止　　字幕保留在本页，刷新即清空",
      // 状态
      st_idle: "未连接",
      st_check: "检查服务…",
      st_mic: "请求麦克风…",
      st_mic_fail: "麦克风不可用",
      st_audio_fail: "音频初始化失败",
      st_no_backend: "连不上后端",
      st_connecting: "连接中…",
      st_rec: "录音中",
      st_stopped: "已停止",
      st_switch: "切换中…",
      st_switch_ok: "已切换热词组，下次开始时生效",
      st_reconnect: (c) => `断开(${c})，重连中…`,
      st_switched_preset: (n) => `已新建「${n}」`,
      st_no_mic_api: "当前环境拿不到麦克风",
      delete_fail: "删除失败",
      // 弹窗
      new_preset: "新建热词组",
      new_preset_desc: "取一个一眼能看懂的名字，比如「计算机」「法律」「药理」。",
      new_preset_ph: "热词组名称",
      create: "创建",
      manage_title: "管理热词组",
      manage_desc: "预设两个方向共用，切换语言不影响这里。",
      rename: "改名",
      delete: "删除",
      rename_title: "重命名热词组",
      rename_ph: "新名称",
      save: "保存",
      done: "完成",
      words_unit: "词",
      thinking: "思考中…",
      no_reply: "（没有回复）",
      backend_down: "连不上后端服务，确认 run.bat 窗口还开着。",
      hotword_updated: (s) => `热词已更新：${s}\n下一次点「开始」时生效`,
      read_preset_fail: "读取预设失败",
      switch_fail: "切换失败",
      create_fail: "新建失败",
      disconnect_msg: "后端连接反复断开",
    },
    en: {
      title: "Live Captions",
      brand: "Live Captions",
      dir_zh: "Chinese → EN",
      dir_en: "EN → Chinese",
      preset: "Presets",
      start: "Start",
      stop: "Stop",
      assistant: "Terminology",
      clear: "Clear",
      send: "Send",
      cancel: "Cancel",
      empty: "Press Start, allow microphone access, and captions will appear from the next sentence.",
      chat_tip: "Ask about a translation or a term — or say “add X to the hotwords”.",
      chat_placeholder: "Ask about a term…",
      foot: "Space to start / stop　　 Captions stay on this page; refresh clears them",
      st_idle: "Disconnected",
      st_check: "Checking…",
      st_mic: "Requesting mic…",
      st_mic_fail: "Microphone unavailable",
      st_audio_fail: "Audio init failed",
      st_no_backend: "No backend",
      st_connecting: "Connecting…",
      st_rec: "Listening",
      st_stopped: "Stopped",
      st_switch: "Switching…",
      st_switch_ok: "Hotword set switched — applies next time you press Start",
      st_reconnect: (c) => `Dropped (${c}), reconnecting…`,
      st_switched_preset: (n) => `Created “${n}”`,
      st_no_mic_api: "Microphone API unavailable",
      delete_fail: "Delete failed",
      new_preset: "New hotword set",
      new_preset_desc: "Give it a name you'll recognise, e.g. “Computer Science”, “Law”.",
      new_preset_ph: "Set name",
      create: "Create",
      manage_title: "Manage hotword sets",
      manage_desc: "Sets are shared by both directions — switching language doesn't change this list.",
      rename: "Rename",
      delete: "Delete",
      rename_title: "Rename hotword set",
      rename_ph: "New name",
      save: "Save",
      done: "Done",
      words_unit: "words",
      thinking: "Thinking…",
      no_reply: "(no reply)",
      backend_down: "Can't reach the backend — check that run.bat is still open.",
      hotword_updated: (s) => `Hotwords updated: ${s}\nTakes effect next time you press Start`,
      read_preset_fail: "Failed to load presets",
      switch_fail: "Switch failed",
      create_fail: "Create failed",
      disconnect_msg: "Backend keeps disconnecting",
    },
  };

  let T = I18N.zh;

  function t(key, ...args) {
    const v = T[key];
    if (typeof v === "function") return v(...args);
    return v !== undefined ? v : key;
  }

  function applyLang(dir) {
    T = I18N[dir === "en" ? "en" : "zh"];
    document.documentElement.lang = dir === "en" ? "en" : "zh-CN";
    document.title = t("title");
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      node.textContent = t(node.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((node) => {
      node.title = t(node.dataset.i18nTitle);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    if (!state.running) el.toggle.textContent = t("start");
  }

  // ---------------------------------------------------------------- 工具

  function setStatus(text, kind = "") {
    el.status.textContent = text;
    el.status.className = "status" + (kind ? " " + kind : "");
  }

  function setDir(dir) {
    state.dir = dir;
    el.dirs.forEach((b) => b.classList.toggle("active", b.dataset.dir === dir));
  }

  function setInterim(text) {
    el.interim.textContent = text || "";
    el.interim.classList.toggle("live", Boolean(text));
  }

  function addRow(src, dst) {
    if (state.firstRow) {
      const empty = el.scroll.querySelector(".empty");
      if (empty) empty.remove();
      state.firstRow = false;
    }
    const row = document.createElement("div");
    row.className = "row";

    const a = document.createElement("div");
    a.className = "src";
    a.textContent = src;

    const b = document.createElement("div");
    b.className = "dst";
    b.textContent = dst || "…";
    if (!dst) b.classList.add("pending");

    // 原文在左、译文在右，保持原样
    row.append(a, b);
    el.scroll.appendChild(row);
    el.scroll.scrollTop = el.scroll.scrollHeight;
  }

  /** 把失败原因直接写在字幕区，别只丢在控制台里。 */
  function showError(title, detail) {
    if (state.firstRow) {
      const empty = el.scroll.querySelector(".empty");
      if (empty) empty.remove();
      state.firstRow = false;
    }
    const row = document.createElement("div");
    row.className = "row error";
    const t = document.createElement("div");
    t.className = "err-title";
    t.textContent = title;
    row.appendChild(t);
    if (detail) {
      const d = document.createElement("div");
      d.className = "err-detail";
      d.textContent = detail;
      row.appendChild(d);
    }
    el.scroll.appendChild(row);
    el.scroll.scrollTop = el.scroll.scrollHeight;
  }

  /** 降采样：按块取平均。直接抽样会产生混叠，听起来像沙沙声。 */
  function downsample(input, ratio) {
    if (ratio <= 1) return Float32Array.from(input);
    const outLen = Math.floor(input.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.min(input.length, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end; j++) sum += input[j];
      out[i] = end > start ? sum / (end - start) : 0;
    }
    return out;
  }

  function toInt16(float32) {
    const out = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  function append(f32, chunk) {
    const merged = new Float32Array(f32.length + chunk.length);
    merged.set(f32, 0);
    merged.set(chunk, f32.length);
    return merged;
  }

  // ------------------------------------------------------------ WebSocket

  function connectWs() {
    return new Promise((resolve, reject) => {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${scheme}://${location.host}/ws?lang=${state.dir}`);
      ws.binaryType = "arraybuffer";
      state.ws = ws;

      ws.onopen = () => {
        state.retryTimer = null;
        state.retries = 0;
        setStatus(t("st_rec"), "ok");
        resolve(ws);
      };

      ws.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg.type === "interim") {
          setInterim(msg.text);
        } else if (msg.type === "final") {
          setInterim("");
          addRow(msg.src, msg.dst);
        } else if (msg.type === "error") {
          setStatus(msg.message || "出错", "err");
        }
      };

      ws.onerror = () => {
        setStatus(t("st_no_backend"), "err");
        reject(new Error("websocket error"));
      };

      ws.onclose = (ev) => {
        if (!state.running) return;
        state.retries += 1;
        setStatus(t("st_reconnect", ev.code), "warn");
        if (state.retries === 3) {
          showError(
            "后端连接反复断开",
            "1) 确认 run.bat 的窗口还开着、没被关掉；" +
            "2) 看那个窗口里有没有红色报错，贴给开发者；" +
            "3) 如果它显示端口被占用，说明已经有一个在跑了。"
          );
        }
        if (state.retryTimer) return;
        state.retryTimer = setTimeout(() => {
          state.retryTimer = null;
          if (state.running) connectWs().catch(() => {});
        }, 1000);
      };
    });
  }

  // -------------------------------------------------------------- 生命周期

  async function start() {
    if (state.running) return;
    el.toggle.disabled = true;
    setStatus(t("st_check"));

    // 问后端要采样率：换识别引擎时这里不用改
    try {
      const cfg = await fetch("/health", { cache: "no-store" }).then((r) => r.json());
      if (cfg && Number(cfg.sampleRate) > 0) {
        TARGET_RATE = Number(cfg.sampleRate);
        FRAME_SAMPLES = Math.round(TARGET_RATE * 0.1);
      }
    } catch {
      /* 读不到就用默认值，连接失败时下面会提示 */
    }

    setStatus(t("st_mic"));

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus(t("st_no_mic_api"), "err");
      showError(
        "当前环境拿不到麦克风接口",
        "请用 Chrome / Edge 打开，地址必须是 http://127.0.0.1:8000。" +
        "用局域网 IP 或直接双击 html 文件打开时，浏览器不给麦克风。"
      );
      el.toggle.disabled = false;
      return;
    }

    try {
      state.mic = await navigator.mediaDevices.getUserMedia({ audio: audioOpts });
    } catch (err) {
      const name = err.name || "Error";
      const tips = {
        NotAllowedError:
          "麦克风权限被拒绝。检查两处：① 地址栏左侧图标里把「麦克风」设为允许；" +
          "② Windows 设置 → 隐私和安全性 → 麦克风 → 允许应用访问麦克风。" +
          "改完刷新本页。",
        NotFoundError:
          "系统里没找到麦克风设备。确认电脑接了麦克风，或系统声音设置里没禁用输入设备。",
        NotReadableError:
          "麦克风被别的程序占用（会议、录音软件）。关掉它们再试。",
        SecurityError:
          "非安全上下文。必须用 http://127.0.0.1:8000 打开，不能用局域网 IP。",
        OverconstrainedError:
          "麦克风不支持请求的参数。",
      };
      setStatus(t("st_mic_fail"), "err");
      showError(`无法获取麦克风（${name}）`, tips[name] || err.message || "");
      console.error(err);
      el.toggle.disabled = false;
      return;
    }

    try {
      state.ctx = new AudioContext();
      if (state.ctx.state === "suspended") await state.ctx.resume();
      state.ratio = state.ctx.sampleRate / TARGET_RATE;

      await state.ctx.audioWorklet.addModule("/static/pcm-worklet.js");
      state.node = new AudioWorkletNode(state.ctx, "pcm-capture");

      // 80 Hz 高通：切掉空调、投影仪这类低频轰鸣。人声基频最低约 85 Hz，
      // 这一刀基本不伤语音，却能去掉噪声里能量最集中的一段。
      const hp = state.ctx.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.value = 80;
      hp.Q.value = 0.7;

      state.ctx.createMediaStreamSource(state.mic).connect(hp).connect(state.node);
      // 接一个 0 增益的出口：没有下游节点的 worklet 在部分浏览器里
      // 可能不被渲染，process() 就不会被调用。
      const sink = state.ctx.createGain();
      sink.gain.value = 0;
      state.node.connect(sink).connect(state.ctx.destination);
    } catch (err) {
      setStatus(t("st_audio_fail"), "err");
      showError(
        "音频处理初始化失败",
        `${err.name || ""} ${err.message || err}`.trim()
      );
      console.error(err);
      cleanupAudio();
      el.toggle.disabled = false;
      return;
    }

    try {
      await connectWs();
    } catch {
      setStatus(t("st_no_backend"), "err");
      showError(
        "无法连接后端服务",
        "确认 run.bat 的窗口还开着，且地址是 http://127.0.0.1:8000。"
      );
      cleanupAudio();
      el.toggle.disabled = false;
      return;
    }

    state.pending = new Float32Array(0);
    state.node.port.onmessage = (event) => {
      const chunk0 = event.data;

      // 先更新电平——不管连接状态如何，它只反映麦克风有没有声音。
      // 电平不动 = 采集没拿到声音；电平在动却没字幕 = 识别或网络的问题。
      if (el.level && chunk0 && chunk0.length) {
        let sum = 0;
        for (let i = 0; i < chunk0.length; i++) sum += chunk0[i] * chunk0[i];
        const rms = Math.sqrt(sum / chunk0.length);
        el.level.style.setProperty("--v", Math.min(1, rms * 12).toFixed(3));
      }

      const ws = state.ws;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;

      const chunk = downsample(chunk0, state.ratio);
      state.pending = append(state.pending, chunk);

      while (state.pending.length >= FRAME_SAMPLES) {
        const frame = state.pending.slice(0, FRAME_SAMPLES);
        state.pending = state.pending.slice(FRAME_SAMPLES);
        ws.send(toInt16(frame).buffer);
      }
    };

    state.running = true;
    el.toggle.textContent = t("stop");
    el.toggle.classList.add("running");
    setStatus(t("st_rec"), "ok");
    el.toggle.disabled = false;
  }

  function stop() {
    state.running = false;
    el.toggle.textContent = t("start");
    el.toggle.classList.remove("running");

    if (state.retryTimer) {
      clearTimeout(state.retryTimer);
      state.retryTimer = null;
    }

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      try {
        state.ws.send(JSON.stringify({ type: "stop" }));
      } catch { /* 忽略 */ }
    }
    if (state.ws) {
      state.ws.onclose = null;
      try { state.ws.close(); } catch { /* 忽略 */ }
      state.ws = null;
    }

    cleanupAudio();
    setInterim("");
    setStatus(t("st_stopped"));
  }

  function cleanupAudio() {
    if (state.node) {
      try { state.node.port.onmessage = null; state.node.disconnect(); } catch { /* 忽略 */ }
      state.node = null;
    }
    if (state.mic) {
      state.mic.getTracks().forEach((t) => t.stop());
      state.mic = null;
    }
    if (state.ctx) {
      state.ctx.close().catch(() => {});
      state.ctx = null;
    }
    state.pending = new Float32Array(0);
    if (el.level) el.level.style.setProperty("--v", "0");
  }

  // ---------------------------------------------------------------- 事件

  el.toggle.addEventListener("click", () => {
    if (state.running) stop();
    else start();
  });

  el.dirs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = btn.dataset.dir;
      if (dir === state.dir) return;
      setDir(dir);
      applyLang(dir);            // 界面语言跟着方向走
      loadPresets(dir);          // 只更新标签，列表是双向共用的
      // 后端会重建会话，前端连接保持不变
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: "lang", value: dir }));
        setStatus(t("st_switch"), "warn");
      }
    });
  });

  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space") return;
    // 在输入框里敲空格是打字，不是开始/停止录制的快捷键
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
    e.preventDefault();
    if (state.running) stop();
    else start();
  });

  window.addEventListener("beforeunload", () => {
    if (state.ws) state.ws.close();
  });

  // ------------------------------------------------------------ 术语助手

  const chat = {
    panel: document.getElementById("chat"),
    log: document.getElementById("chat-log"),
    form: document.getElementById("chat-form"),
    input: document.getElementById("chat-input"),
    send: document.getElementById("chat-send"),
    clear: document.getElementById("chat-clear"),
    resizer: document.getElementById("resizer"),
  };

  function addMsg(role, text, extra = "") {
    const tip = chat.log.querySelector(".chat-tip");
    if (tip) tip.remove();
    const div = document.createElement("div");
    div.className = `msg ${role}${extra ? " " + extra : ""}`;
    div.textContent = text;          // 助手回复来自外部模型，绝不走 innerHTML
    chat.log.appendChild(div);
    chat.log.scrollTop = chat.log.scrollHeight;
    return div;
  }

  chat.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chat.input.value.trim();
    if (!text) return;
    chat.input.value = "";
    addMsg("user", text);
    const pending = addMsg("bot", t("thinking"), "pending");
    chat.send.disabled = true;
    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, direction: pairOf(state.dir) }),
      });
      const data = await res.json();
      pending.remove();
      addMsg("bot", data.reply || t("no_reply"));
      const c = data.changed;
      if (c && (c.added?.length || c.removed?.length)) {
        const bits = [];
        if (c.added?.length) bits.push("+" + c.added.join("、"));
        if (c.removed?.length) bits.push("−" + c.removed.join("、"));
        addMsg("sys", t("hotword_updated", bits.join("  ")));
      }
    } catch {
      pending.remove();
      addMsg("bot", t("backend_down"));
    } finally {
      chat.send.disabled = false;
      chat.input.focus();
    }
  });

  chat.clear.addEventListener("click", () => {
    chat.log.innerHTML = "";
    fetch("/chat/reset", { method: "POST" }).catch(() => {});
  });

  // 拖动分隔条调整助手宽度，宽度记在本地
  let dragging = false;
  const savedW = Number(localStorage.getItem("chatW") || 0);
  if (savedW >= 240) chat.panel.style.setProperty("--chat-w", savedW + "px");

  chat.resizer.addEventListener("mousedown", (e) => {
    dragging = true;
    chat.resizer.classList.add("active");
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = Math.max(240, Math.min(720, window.innerWidth - e.clientX));
    chat.panel.style.setProperty("--chat-w", w + "px");
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    chat.resizer.classList.remove("active");
    document.body.style.cursor = "";
    const w = parseInt(chat.panel.style.getPropertyValue("--chat-w") || "0", 10);
    if (w) localStorage.setItem("chatW", String(w));
  });

  // ------------------------------------------------------- 预设（热词组）

  const presetUI = {
    select: document.getElementById("preset-select"),
    label: document.getElementById("preset-label"),
    add: document.getElementById("preset-add"),
    manage: document.getElementById("preset-manage"),
  };

  const modalUI = {
    root: document.getElementById("modal"),
    title: document.getElementById("modal-title"),
    desc: document.getElementById("modal-desc"),
    input: document.getElementById("modal-input"),
    body: document.getElementById("modal-body"),
    ok: document.getElementById("modal-ok"),
    cancel: document.getElementById("modal-cancel"),
  };

  const pairOf = (dir) => (dir === "zh" ? "zh2en" : "en2zh");

  /** 通用弹窗，返回 Promise：确认拿到输入值（或 true），取消拿到 null。 */
  function showModal({ title, desc = "", withInput = true, value = "", placeholder = "", okText = "确定", renderBody = null }) {
    return new Promise((resolve) => {
      modalUI.title.textContent = title;
      modalUI.desc.textContent = desc;
      modalUI.desc.hidden = !desc;
      modalUI.input.hidden = !withInput;
      modalUI.input.value = value;
      modalUI.input.placeholder = placeholder;
      modalUI.body.hidden = !renderBody;
      modalUI.body.innerHTML = "";
      if (renderBody) renderBody(modalUI.body);
      modalUI.ok.textContent = okText;
      modalUI.root.hidden = false;
      if (withInput) setTimeout(() => modalUI.input.focus(), 30);

      const finish = (val) => {
        modalUI.root.hidden = true;
        modalUI.ok.onclick = null;
        modalUI.cancel.onclick = null;
        modalUI.input.onkeydown = null;
        modalUI.root.onclick = null;
        resolve(val);
      };

      modalUI.ok.onclick = () => finish(withInput ? modalUI.input.value.trim() : true);
      modalUI.cancel.onclick = () => finish(null);
      modalUI.input.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); modalUI.ok.click(); }
        if (e.key === "Escape") { e.preventDefault(); finish(null); }
      };
      modalUI.root.onclick = (e) => { if (e.target === modalUI.root) finish(null); };
    });
  }

  async function fetchPresets() {
    const res = await fetch("/presets");
    return res.json();
  }

  async function loadPresets(dir = state.dir) {
    // 预设是双向共用的：切换语言只换标签，列表不变
    presetUI.label.textContent = t("preset");
    try {
      const data = await fetchPresets();
      presetUI.select.innerHTML = "";
      for (const p of data.items) {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.name}（${p.count}）`;
        if (p.id === data.active) opt.selected = true;
        presetUI.select.appendChild(opt);
      }
    } catch {
      presetUI.select.innerHTML = "<option>未连接</option>";
    }
  }

  presetUI.select.addEventListener("change", async () => {
    try {
      await fetch(`/presets/${presetUI.select.value}/activate`, { method: "POST" });
      setStatus(t("st_switch_ok"), "warn");
    } catch {
      setStatus(t("switch_fail"), "err");
    }
  });

  presetUI.add.addEventListener("click", async () => {
    const name = await showModal({
      title: t("new_preset"),
      desc: t("new_preset_desc"),
      placeholder: t("new_preset_ph"),
      okText: t("create"),
    });
    if (!name) return;
    try {
      await fetch("/presets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      await loadPresets();
      setStatus(t("st_switched_preset", name), "ok");
    } catch {
      setStatus(t("create_fail"), "err");
    }
  });

  presetUI.manage.addEventListener("click", async () => {
    const dir = state.dir;
    let data;
    try {
      data = await fetchPresets();
    } catch {
      setStatus(t("read_preset_fail"), "err");
      return;
    }

    await showModal({
      title: t("manage_title"),
      desc: t("manage_desc"),
      withInput: false,
      okText: t("done"),
      renderBody: (box) => {
        data.items.forEach((p) => {
          const row = document.createElement("div");
          row.className = "preset-row" + (p.id === data.active ? " current" : "");

          const name = document.createElement("span");
          name.className = "name";
          name.textContent = p.name;

          const count = document.createElement("span");
          count.className = "count";
          count.textContent = `${p.count} ${t("words_unit")}`;

          const ren = document.createElement("button");
          ren.className = "ghost";
          ren.textContent = t("rename");
          ren.onclick = async () => {
            const v = await showModal({
              title: t("rename_title"),
              value: p.name,
              placeholder: t("rename_ph"),
              okText: t("save"),
            });
            if (!v) return;
            await fetch(`/presets/${p.id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ name: v }),
            }).catch(() => {});
            await loadPresets(dir);
            presetUI.manage.click();
          };

          const del = document.createElement("button");
          del.className = "ghost";
          del.textContent = t("delete");
          del.onclick = async () => {
            const r = await fetch(`/presets/${p.id}`, { method: "DELETE" }).catch(() => null);
            const j = r ? await r.json().catch(() => ({})) : {};
            if (j && j.ok === false) setStatus(j.reason || t("delete_fail"), "err");
            await loadPresets(dir);
            presetUI.manage.click();
          };

          row.append(name, count, ren, del);
          box.appendChild(row);
        });
      },
    });
  });

  applyLang("zh");
  loadPresets();
  setStatus(t("st_idle"));
})();
