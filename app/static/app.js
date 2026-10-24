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
        setStatus("录音中", "ok");
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
        setStatus("连接异常", "err");
        reject(new Error("websocket error"));
      };

      ws.onclose = (ev) => {
        if (!state.running) return;
        state.retries += 1;
        setStatus(`断开(${ev.code})，重连中…`, "warn");
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
    setStatus("检查服务…");

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

    setStatus("请求麦克风…");

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("浏览器不支持", "err");
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
      setStatus("麦克风不可用", "err");
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
      setStatus("音频初始化失败", "err");
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
      setStatus("连不上后端", "err");
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
    el.toggle.textContent = "停止";
    el.toggle.classList.add("running");
    setStatus("录音中", "ok");
    el.toggle.disabled = false;
  }

  function stop() {
    state.running = false;
    el.toggle.textContent = "开始";
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
    setStatus("已停止");
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
      // 后端会重建会话，前端连接保持不变
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: "lang", value: dir }));
        setStatus("切换中…", "warn");
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
    const pending = addMsg("bot", "思考中…", "pending");
    chat.send.disabled = true;
    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      pending.remove();
      addMsg("bot", data.reply || "（没有回复）");
      const c = data.changed;
      if (c && (c.added?.length || c.removed?.length)) {
        const bits = [];
        if (c.added?.length) bits.push("+" + c.added.join("、"));
        if (c.removed?.length) bits.push("−" + c.removed.join("、"));
        addMsg("sys", `热词已更新：${bits.join("　")}\n下一次点「开始」时生效`);
      }
    } catch {
      pending.remove();
      addMsg("bot", "连不上后端服务，确认 run.bat 窗口还开着。");
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

  setStatus("未连接");
})();
