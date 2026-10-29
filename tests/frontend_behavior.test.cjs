// 本文件由 codex 辅助生成（前端行为回归测试）
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "frontend", "app.js"), "utf8");

function storySession({ id = "story-1", finished = false, history = [] } = {}) {
  return {
    session_id: id,
    mode: "offline",
    state: {
      session_id: id,
      player_name: "清岚",
      scene_id: finished ? "scene_08" : "scene_01",
      turn_count: finished ? 8 : 0,
      trust: 50,
      compassion: 50,
      responsibility: 50,
      history,
      is_finished: finished,
      ending_id: finished ? "evidence_keeper" : null,
    },
    last_response: {
      reply: "沿着这条线索继续查。",
      emotion: "guarded",
      state_delta: {},
      next_scene: { scene_id: "scene_01", options: [{ id: "listen", text: "继续调查" }] },
      is_ending: finished,
      ending_id: finished ? "evidence_keeper" : null,
    },
    ending: finished ? { ending_id: "evidence_keeper", title: "见证者", summary: "你让真相留在众人面前。" } : null,
  };
}

function makeBrowser({ hash = "#home", storage = {}, providerError = false, deferRegenerate = false, regenerateError = false, deleteChatError = false, deferDeleteChat = false, deferChat = false, deferChatDespiteAbort = false, deferChatCancel = false, chatCancelFailures = 0, chatCancelCommitted = false, chatHistory = [], deferStoryTurn = false, finishStoryTurn = false, deferVoice = false, deferVoiceAfter = 0, deferVoiceStatus = false, deferAudioReady = false, deferAudioStart = false, deferAudioEnd = false, deferStreamReads = false, suppressAudioPlaying = false, audioRequiresGesture = false, voiceEnabled = false, voiceReadyAfter = 0, voiceError = false, streamChat = false, chatStreamChunks = ["第一句。", "第二句！"], chatReply = "我听见了。" } = {}) {
  const listeners = {};
  const calls = [];
  const events = [];
  const audioPlayback = [];
  const audioInstances = [];
  const timerDelays = [];
  const values = new Map(Object.entries(storage));
  let markup = "";
  let errorMarkup = "";
  let resolveRegenerate;
  let resolveChat;
  let resolveChatCancel;
  let chatPostRequestCount = 0;
  let chatCancelRequestCount = 0;
  let resolveDeleteChat;
  let resolveStoryTurn;
  let resolveVoice;
  let resolveVoiceStatus;
  const pendingAudioReady = [];
  let resolveAudioStart;
  let resolveStreamRead;
  let audioUnlocked = false;
  let voiceSynthesisCalls = 0;
  let voiceStatusChecks = 0;
  let streamReaderCancelled = false;
  let serverChatMessages = chatHistory.map((message) => ({ ...message }));
  const timers = [];
  let nextTimerId = 0;
  const root = {
    get innerHTML() { return markup; },
    set innerHTML(value) { markup = value; events.push({ type: "render", html: value }); },
    addEventListener(type, listener) { listeners[`root:${type}`] = listener; },
    querySelectorAll() {
      return [chatInputControl, deleteChatControl];
    },
    querySelector(selector) {
      if (selector === "[data-player-name]") return null;
      if (selector === "[data-streaming-reply]" && markup.includes("data-streaming-reply")) {
        return {
          set textContent(value) {
            const escaped = String(value).replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[char]);
            markup = markup.replace(/(<p data-streaming-reply>)[\s\S]*?(<\/p>)/, `$1${escaped}$2`);
            events.push({ type: "stream-text", text: String(value) });
          },
        };
      }
      if (selector.includes("data-error") || selector.includes("data-chat-error")) {
        return { set innerHTML(value) { errorMarkup = value; }, get innerHTML() { return errorMarkup; } };
      }
      return null;
    },
  };
  const toggleState = new Set();
  const modeControl = { classList: { toggle(name, enabled) { enabled ? toggleState.add(name) : toggleState.delete(name); } } };
  const toast = { textContent: "", hidden: true };
  const localStorage = {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
  const window = {
    location: { hash },
    addEventListener(type, listener) { listeners[`window:${type}`] = listener; },
    setTimeout(callback, delay = 0) {
      const id = ++nextTimerId;
      timers.push({ id, callback, delay });
      timerDelays.push(delay);
      return id;
    },
    clearTimeout(id) {
      const timerIndex = timers.findIndex((timer) => timer.id === id);
      if (timerIndex >= 0) timers.splice(timerIndex, 1);
    },
    requestAnimationFrame(callback) {
      Promise.resolve().then(() => {
        events.push({ type: "animation-frame" });
        callback(0);
      });
    },
    confirm() { return true; },
  };
  const document = {
    querySelector(selector) {
      return ({ "#app": root, ".topbar-right": modeControl, "#toast": toast })[selector] || null;
    },
  };
  const streamReply = chatStreamChunks.join("");
  const streamEvents = [
    ...chatStreamChunks.map((delta, index) => ({ type: "text", index, delta })),
    {
      type: "done",
      response: { reply: streamReply, title: "围绕问题展开的对话", emotion: "calm", state_delta: {}, next_scene: null, is_ending: false, ending_id: null },
      messages: [{ message: "你好", reply: streamReply, emotion: "calm" }],
      title: "围绕问题展开的对话",
    },
  ];
  const streamBytes = new TextEncoder().encode(streamEvents.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
  const streamFrames = streamEvents.map((event) => new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  const completedChatResult = (options) => {
    const message = JSON.parse(options.body).message;
    serverChatMessages = [...serverChatMessages, { message, reply: chatReply, emotion: "calm" }];
    return {
      data: {
        response: { reply: chatReply, title: "围绕问题展开的对话", emotion: "calm", state_delta: {}, next_scene: null, is_ending: false, ending_id: null },
        messages: serverChatMessages,
      },
    };
  };
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/api/voice/stream" && options.method === "POST") events.push({ type: "voice-request" });
    if (url === "/api/voice/status") {
      voiceStatusChecks += 1;
      const enabled = voiceReadyAfter ? voiceStatusChecks >= voiceReadyAfter : voiceEnabled;
      const configured = voiceReadyAfter ? true : voiceEnabled;
      if (deferVoiceStatus && voiceStatusChecks === 1) {
        return await new Promise((resolve) => {
          resolveVoiceStatus = () => resolve({ ok: true, json: async () => ({ data: { enabled, configured } }) });
        });
      }
      return { ok: true, json: async () => ({ data: { enabled, configured } }) };
    }
    if (url === "/api/voice/stream" && options.method === "POST") {
      if (voiceError) throw new Error("Voice service unavailable");
      voiceSynthesisCalls += 1;
      if (deferVoice && voiceSynthesisCalls > deferVoiceAfter) {
        return await new Promise((resolve) => {
          resolveVoice = () => resolve({ ok: true, blob: async () => ({ type: "audio/wav" }) });
        });
      }
      return { ok: true, blob: async () => ({ type: "audio/wav" }) };
    }
    if (url === "/api/sessions" && options.method === "POST") {
      return { ok: true, json: async () => ({ data: storySession() }) };
    }
    if (url === "/api/sessions/saved-story") {
      return { ok: true, json: async () => ({ data: storySession({ id: "saved-story" }) }) };
    }
    if (url === "/api/sessions/completed-story") {
      return { ok: true, json: async () => ({ data: storySession({ id: "completed-story", finished: true }) }) };
    }
    if (url === "/api/sessions/story-1/turn" && options.method === "POST") {
      const nextState = storySession({
        finished: finishStoryTurn,
        history: [{ scene_id: "scene_01", player_input: "先听听他的判断", response_summary: "沿着这条线索继续查。" }],
      }).state;
      const response = {
        ok: true,
        json: async () => ({
          data: {
            state: nextState,
            response: {
              reply: "沿着这条线索继续查。",
              emotion: "guarded",
              state_delta: {},
              next_scene: finishStoryTurn ? null : { scene_id: "scene_02", options: [{ id: "inspect_records", text: "查阅旧档案" }] },
              is_ending: finishStoryTurn,
              ending_id: finishStoryTurn ? "evidence_keeper" : null,
            },
            ending: finishStoryTurn ? { ending_id: "evidence_keeper", title: "见证者", summary: "你让真相留在众人面前。" } : null,
          },
        }),
      };
      if (deferStoryTurn) {
        return await new Promise((resolve) => { resolveStoryTurn = () => resolve(response); });
      }
      return response;
    }
    if (url === "/api/chat/sessions" && options.method === "POST") {
      return { ok: true, json: async () => ({ data: { chat_session_id: "chat-1", player_name: "清岚", mode: "live", messages: [] } }) };
    }
    if (url === "/api/chat/sessions/chat-1/cancel" && options.method === "POST") {
      chatCancelRequestCount += 1;
      if (deferChatCancel) {
        return await new Promise((resolve) => {
          resolveChatCancel = () => resolve({ ok: true, json: async () => ({ data: { cancelled: true } }) });
        });
      }
      if (chatCancelRequestCount <= chatCancelFailures) {
        return { ok: false, json: async () => ({ error: { message: "暂停确认失败，请重试。" } }) };
      }
      if (chatCancelCommitted) {
        const priorPost = calls.find((call) => call.url === "/api/chat/sessions/chat-1/messages" && call.options.method === "POST");
        const message = priorPost ? JSON.parse(priorPost.options.body).message : "已提交的问题";
        serverChatMessages = [...serverChatMessages, { message, reply: "服务端已提交的旧回答。", emotion: "calm" }];
        return { ok: true, json: async () => ({ data: { cancelled: false } }) };
      }
      return { ok: true, json: async () => ({ data: { cancelled: true } }) };
    }
    if (url === "/api/chat/sessions/chat-1" && options.method !== "DELETE") {
      return { ok: true, json: async () => ({ data: { chat_session_id: "chat-1", player_name: "清岚", title: "恢复的对话", messages: serverChatMessages } }) };
    }
    if (url === "/api/chat/sessions/chat-1/regenerate" && options.method === "POST") {
      if (deferRegenerate) {
        await new Promise((resolve) => { resolveRegenerate = resolve; });
      }
      if (regenerateError) {
        return { ok: false, json: async () => ({ error: { message: "重新生成失败，请稍后重试。" } }) };
      }
      return {
        ok: true,
        json: async () => ({
          data: {
            response: { reply: "换一个说法。", title: "围绕问题展开的对话", emotion: "guarded", state_delta: {}, next_scene: null, is_ending: false, ending_id: null },
            messages: [{ message: "你好", reply: "换一个说法。", emotion: "guarded" }],
          },
        }),
      };
    }
    if (url === "/api/chat/sessions/chat-1/messages" && providerError) {
      return {
        ok: false,
        json: async () => ({
          error: {
            message: "模型服务禁止访问（HTTP 403）。",
            details: {
              provider_status: 403,
              model: "example-model",
              endpoint: "https://provider.example/v1/chat/completions",
              provider_request_id: "provider-safe-456",
            },
          },
          request_id: "request-safe-123",
        }),
      };
    }
    if (url === "/api/chat/sessions/chat-1/messages" && options.method === "POST") {
      const requestNumber = chatPostRequestCount++;
      if (streamChat) {
        let delivered = false;
        return {
          ok: true,
          headers: { get: (name) => name.toLowerCase() === "content-type" ? "text/event-stream; charset=utf-8" : null },
          body: {
            getReader() {
              let frameIndex = 0;
              return {
                async read() {
                  if (deferStreamReads) {
                    if (frameIndex >= streamFrames.length) return { done: true, value: undefined };
                    return await new Promise((resolve) => {
                      resolveStreamRead = () => resolve({ done: false, value: streamFrames[frameIndex++] });
                    });
                  }
                  if (delivered) return { done: true, value: undefined };
                  delivered = true;
                  return { done: false, value: streamBytes };
                },
                async cancel() { delivered = true; streamReaderCancelled = true; },
              };
            },
          },
        };
      }
      if (deferChat && requestNumber === 0) {
        return await new Promise((resolve, reject) => {
          resolveChat = resolve;
          if (!deferChatDespiteAbort) {
            options.signal?.addEventListener("abort", () => {
              const error = new Error("aborted");
              error.name = "AbortError";
              reject(error);
            });
          }
        });
      }
      return {
        ok: true,
        json: async () => completedChatResult(options),
      };
    }
    if (url === "/api/chat/sessions/chat-1" && options.method === "DELETE") {
      if (deferDeleteChat) await new Promise((resolve) => { resolveDeleteChat = resolve; });
      if (deleteChatError) {
        return { ok: false, json: async () => ({ error: { message: "删除失败，请稍后重试。" } }) };
      }
      return { ok: true, json: async () => ({ data: { deleted: true } }) };
    }
    throw new Error(`Unexpected request: ${options.method || "GET"} ${url}`);
  };
  const chatInputControl = {
    dataset: { chatInput: "true" },
    disabled: false,
    matches(selector) { return selector === "[data-chat-input]"; },
  };
  const deleteChatControl = {
    dataset: { action: "delete-chat", chatSession: "chat-1" },
    disabled: false,
    matches() { return false; },
  };
  const clipboardWrites = [];
  const navigator = { clipboard: { async writeText(text) { clipboardWrites.push(text); } } };
  class FakeAbortController {
    constructor() {
      const listeners = [];
      this.signal = {
        aborted: false,
        addEventListener(type, listener) {
          if (type === "abort") listeners.push(listener);
        },
      };
      this.abort = () => {
        this.signal.aborted = true;
        listeners.forEach((listener) => listener());
      };
    }
  }
  class FakeAudio {
    constructor(source) {
      this.src = source || "";
      this.muted = false;
      this.paused = true;
      this.ended = false;
      this.readyState = 0;
      this.readyPromise = Promise.resolve();
      this.listeners = new Map();
      audioInstances.push(this);
    }
    addEventListener(type, listener) {
      const handlers = this.listeners.get(type) || new Set();
      handlers.add(listener);
      this.listeners.set(type, handlers);
      if (type === "ended" && !deferAudioEnd) Promise.resolve().then(() => this.finish());
    }
    removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
    dispatch(type) { [...(this.listeners.get(type) || [])].forEach((listener) => listener()); }
    load() {
      if (!this.src.startsWith("/api/voice/stream")) return;
      events.push({ type: "voice-prepare" });
      if (deferAudioReady) {
        this.readyPromise = new Promise((resolve) => {
          pendingAudioReady.push(() => {
            this.readyState = 3;
            this.dispatch("canplay");
            resolve();
          });
        });
      } else {
        this.readyState = 3;
        this.dispatch("canplay");
      }
    }
    finish() {
      if (this.ended || this.paused) return;
      this.ended = true;
      this.paused = true;
      [...(this.listeners.get("ended") || [])].forEach((listener) => listener());
      this.onended?.();
    }
    async play() {
      if (audioRequiresGesture && !audioUnlocked && !this.muted && !this.src.startsWith("data:")) {
        const error = new Error("Autoplay is not allowed");
        error.name = "NotAllowedError";
        throw error;
      }
      const silentUnlock = this.muted || this.src.startsWith("data:");
      if (silentUnlock) {
        audioUnlocked = true;
        this.paused = false;
        return;
      }
      if (this.src.startsWith("/api/voice/stream")) {
        if (voiceError) throw new Error("Voice service unavailable");
        voiceSynthesisCalls += 1;
        calls.push({ url: "/api/voice/stream", requestUrl: this.src, options: { method: "GET" } });
        events.push({ type: "voice-request" });
        if (deferVoice && voiceSynthesisCalls > deferVoiceAfter) {
          await new Promise((resolve) => { resolveVoice = resolve; });
          if (!this.src) return;
        }
        await this.readyPromise;
        if (!this.src) return;
      }
      if (deferAudioStart) {
        await new Promise((resolve) => { resolveAudioStart = resolve; });
        if (this.paused) return;
      }
      this.ended = false;
      this.paused = false;
      audioPlayback.push(this.src.startsWith("/api/voice/stream") ? "blob:voice-response" : this.src);
      events.push({ type: "audio-play" });
      if (!suppressAudioPlaying) {
        events.push({ type: "audio-playing" });
        this.dispatch("playing");
      }
    }
    pause() { this.paused = true; }
  }
  const context = {
    document,
    window,
    localStorage,
    fetch,
    console,
    navigator,
    Audio: FakeAudio,
    TextDecoder,
    URL: { createObjectURL: () => "blob:voice-response", revokeObjectURL() {} },
    AbortController: FakeAbortController,
  };
  vm.runInNewContext(source, context, { filename: "frontend/app.js" });

  return {
    calls,
    events,
    root,
    values,
    clipboardWrites,
    audioPlayback,
    audioInstances,
    timerDelays,
    get chatInputDisabled() { return chatInputControl.disabled; },
    get currentChatDeleteDisabled() { return deleteChatControl.disabled; },
    get streamReaderCancelled() { return streamReaderCancelled; },
    get serverChatMessages() { return serverChatMessages.map((message) => ({ ...message })); },
    async runNextTimer() {
      const timer = timers.shift();
      if (timer) timer.callback();
      await settle();
    },
    async runTimer(delay) {
      const timerIndex = timers.findIndex((timer) => timer.delay === delay);
      const [timer] = timerIndex >= 0 ? timers.splice(timerIndex, 1) : [];
      if (timer) timer.callback();
      await settle();
    },
    modeControlHidden: () => toggleState.has("is-hidden"),
    async click(action, dataset = {}) {
      if (action === "delete-chat" && deleteChatControl.disabled) return;
      listeners["root:click"]({ target: { closest: () => ({ dataset: { action, ...dataset } }) } });
      await settle();
    },
    async submitChat(message) {
      const listener = listeners["root:submit"];
      listener({
        target: {
          matches: (selector) => selector === '[data-form="chat"]',
          querySelector: () => ({ value: message }),
        },
        preventDefault() {},
      });
      await settle();
    },
    submitChatPending(message) {
      const listener = listeners["root:submit"];
      listener({
        target: {
          matches: (selector) => selector === '[data-form="chat"]',
          querySelector: () => ({ value: message }),
        },
        preventDefault() {},
      });
    },
    inputChat(value) {
      listeners["root:input"]({ target: { matches: (selector) => selector === "[data-chat-input]", value } });
    },
    async submitName(name, { target = "story", replayId = "demo_guarded_path" } = {}) {
      listeners["root:submit"]({
        target: {
          matches: (selector) => selector === '[data-form="player-name"]',
          dataset: { startTarget: target, replayId },
          querySelector: () => ({ value: name }),
        },
        preventDefault() {},
      });
      await settle();
    },
    async setRoute(route) {
      window.location.hash = route;
      listeners["window:hashchange"]();
      await settle();
    },
    get errorMarkup() { return errorMarkup; },
    get hash() { return window.location.hash; },
    resolveRegenerate() {
      if (resolveRegenerate) resolveRegenerate();
    },
    resolveChat({ message = "修订后的问题", reply = chatReply, messages = null } = {}) {
      if (resolveChat) resolveChat({
        ok: true,
        json: async () => ({
          data: {
            response: { reply, title: "围绕问题展开的对话", emotion: "calm", state_delta: {}, next_scene: null, is_ending: false, ending_id: null },
            messages: messages || [{ message, reply, emotion: "calm" }],
          },
        }),
      });
    },
    resolveChatCancel() {
      if (resolveChatCancel) resolveChatCancel();
    },
    resolveDeleteChat() {
      if (resolveDeleteChat) resolveDeleteChat();
    },
    resolveStoryTurn() {
      if (resolveStoryTurn) resolveStoryTurn();
    },
    resolveVoice() {
      if (resolveVoice) resolveVoice();
    },
    resolveVoiceStatus() {
      if (resolveVoiceStatus) resolveVoiceStatus();
    },
    resolveAudioReady() {
      while (pendingAudioReady.length) {
        const resolve = pendingAudioReady.shift();
        resolve();
        const audio = [...audioInstances].reverse().find((candidate) => candidate.readyState >= 3 && candidate.src.startsWith("/api/voice/stream"));
        if (audio) break;
      }
    },
    signalAudioLoadedData() {
      const audio = [...audioInstances].reverse().find((candidate) => candidate.src.startsWith("/api/voice/stream"));
      if (audio) {
        audio.readyState = 2;
        audio.dispatch("loadeddata");
      }
    },
    resolveAudioStart() {
      if (resolveAudioStart) resolveAudioStart();
    },
    resolveAudioEnd() {
      [...audioInstances].reverse().find((audio) => !audio.paused && !audio.ended)?.finish();
    },
    releaseNextStreamEvent() {
      const release = resolveStreamRead;
      resolveStreamRead = undefined;
      if (release) release();
    },
  };
}

async function settle() {
  for (let index = 0; index < 6; index += 1) await new Promise((resolve) => setImmediate(resolve));
}

test("story catalog selection creates a fixed replay, hides mode controls, and renders no emotion", async () => {
  const browser = makeBrowser({ hash: "#/stories", storage: { "wanderer-player-name": "清岚" } });
  assert.match(browser.root.innerHTML, /选择一段旅途/);
  assert.equal((browser.root.innerHTML.match(/class="story-row"/g) || []).length, 2);
  assert.equal(browser.modeControlHidden(), false);

  await browser.click("select-story", { replayId: "demo_guarded_path" });

  const create = browser.calls.find((call) => call.url === "/api/sessions");
  assert.deepEqual(JSON.parse(create.options.body), { mode: "offline", replay_id: "demo_guarded_path", player_name: "清岚" });
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
  assert.doesNotMatch(browser.root.innerHTML, /回到首页/);
  assert.doesNotMatch(browser.root.innerHTML, /class="emotion"|class="mode-pill"|实时接口|固定回放/);
  await browser.setRoute("#home");
  assert.doesNotMatch(browser.root.innerHTML, /resume-dialog/);
});

test("story voice starts preparing before the initial reply is rendered", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
  });

  await browser.click("select-story", { replayId: "demo_guarded_path" });

  const replyRenderIndex = browser.events.findIndex((event) => event.type === "render" && event.html.includes("沿着这条线索继续查"));
  const voicePrepareIndex = browser.events.findIndex((event) => event.type === "voice-prepare");
  assert.ok(voicePrepareIndex >= 0);
  assert.ok(voicePrepareIndex < replyRenderIndex);
});

test("selected route is retained while the player enters a name", async () => {
  const browser = makeBrowser({ hash: "#/stories" });
  assert.equal((browser.root.innerHTML.match(/class="story-row"/g) || []).length, 2);
  await browser.click("select-story", { replayId: "demo_guarded_path" });
  assert.match(browser.root.innerHTML, /先取一个称呼/);

  await browser.submitName("清岚", { replayId: "demo_guarded_path" });

  const create = browser.calls.find((call) => call.url === "/api/sessions");
  assert.deepEqual(JSON.parse(create.options.body), { mode: "offline", replay_id: "demo_guarded_path", player_name: "清岚" });
});

test("the submitted option is rendered in the same turn as its response", async () => {
  const browser = makeBrowser({ hash: "#/stories", storage: { "wanderer-player-name": "清岚" } });

  await browser.click("select-story", { replayId: "demo_guarded_path" });
  await browser.click("option", { option: "listen" });

  assert.match(browser.root.innerHTML, /继续调查/);
  assert.match(browser.root.innerHTML, /<p>……<\/p>/);
  await browser.runNextTimer();
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
});

test("story turn immediately shows a single ellipsis placeholder and reveals the reply after the response delay", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    deferStoryTurn: true,
    voiceEnabled: true,
  });

  await browser.click("select-story", { replayId: "demo_guarded_path" });
  browser.click("option", { option: "listen" });
  await settle();

  assert.match(browser.root.innerHTML, /继续调查/);
  assert.match(browser.root.innerHTML, /<p>……<\/p>/);
  assert.doesNotMatch(browser.root.innerHTML, /正在整理这段回应/);
  assert.doesNotMatch(browser.root.innerHTML, /沿着这条线索继续查/);
  assert.equal(browser.audioPlayback.length, 1);

  browser.resolveStoryTurn();
  await settle();
  assert.match(browser.root.innerHTML, /<p>……<\/p>/);

  await browser.runNextTimer();
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
  assert.doesNotMatch(browser.root.innerHTML, /正在整理这段回应/);
  assert.equal(browser.audioPlayback.length, 2);
});

test("story voice starts preparing before the delayed turn reply is rendered", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    deferStoryTurn: true,
    voiceEnabled: true,
  });

  await browser.click("select-story", { replayId: "demo_guarded_path" });
  const eventStart = browser.events.length;
  const turning = browser.click("option", { option: "listen" });
  await settle();
  browser.resolveStoryTurn();
  await settle();
  await browser.runNextTimer();
  await turning;

  const events = browser.events.slice(eventStart);
  const replyRenderIndex = events.findIndex((event) => event.type === "render" && event.html.includes("沿着这条线索继续查"));
  const voicePrepareIndex = events.findIndex((event) => event.type === "voice-prepare");
  assert.ok(voicePrepareIndex >= 0);
  assert.ok(replyRenderIndex >= 0);
  assert.ok(voicePrepareIndex < replyRenderIndex);
});

test("a fast repeated story choice cannot restore the old loading state or duplicate the turn request", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    deferStoryTurn: true,
  });

  await browser.click("select-story", { replayId: "demo_guarded_path" });
  browser.click("option", { option: "listen" });
  browser.click("option", { option: "listen" });
  await settle();

  assert.equal(browser.calls.filter((call) => call.url === "/api/sessions/story-1/turn").length, 1);
  assert.match(browser.root.innerHTML, /<p>……<\/p>/);
  assert.doesNotMatch(browser.root.innerHTML, /正在整理这段回应/);
});

test("restored unfinished journey can be declined without deleting progress, or resumed", async () => {
  const declined = makeBrowser({ storage: { "wanderer-session": "saved-story" } });
  await settle();
  assert.match(declined.root.innerHTML, /要继续上一段旅途吗/);
  await declined.click("dismiss-resume");
  assert.doesNotMatch(declined.root.innerHTML, /resume-dialog/);
  assert.equal(declined.values.get("wanderer-session"), "saved-story");

  const resumed = makeBrowser({ storage: { "wanderer-session": "saved-story" } });
  await settle();
  await resumed.click("resume-journey");
  assert.equal(resumed.hash, "#/game");
  assert.match(resumed.root.innerHTML, /互动故事/);
  assert.equal(resumed.values.get("wanderer-session"), "saved-story");
  await resumed.setRoute("#home");
  assert.doesNotMatch(resumed.root.innerHTML, /resume-dialog/);

  const directory = makeBrowser({ hash: "#/stories", storage: { "wanderer-session": "saved-story" } });
  await settle();
  await directory.click("dismiss-resume");
  assert.equal(directory.hash, "#/stories");
  assert.match(directory.root.innerHTML, /选择一段旅途/);
  assert.equal(directory.values.get("wanderer-session"), "saved-story");

  const refreshedGame = makeBrowser({ hash: "#/game", storage: { "wanderer-session": "saved-story" } });
  await settle();
  assert.match(refreshedGame.root.innerHTML, /要继续上一段旅途吗/);
  await refreshedGame.click("dismiss-resume");
  assert.equal(refreshedGame.hash, "#home");
  assert.match(refreshedGame.root.innerHTML, /风起异途/);
  assert.doesNotMatch(refreshedGame.root.innerHTML, /互动故事/);
  assert.equal(refreshedGame.values.get("wanderer-session"), "saved-story");
});

test("resuming an unfinished journey reads the visible character reply", async () => {
  const browser = makeBrowser({
    storage: { "wanderer-session": "saved-story" },
    voiceEnabled: true,
  });
  await settle();
  const eventStart = browser.events.length;

  await browser.click("resume-journey");
  await settle();

  const events = browser.events.slice(eventStart);
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
  assert.ok(events.some((event) => event.type === "voice-prepare"));
  assert.ok(events.some((event) => event.type === "audio-play"));
});

test("finishing the last story turn does not prepare or play the ending reply", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    finishStoryTurn: true,
  });
  await browser.click("select-story", { replayId: "demo_guarded_path" });
  const eventStart = browser.events.length;

  const turning = browser.click("option", { option: "accept_burden" });
  await settle();
  await browser.runTimer(1000);
  await turning;

  const events = browser.events.slice(eventStart);
  assert.match(browser.root.innerHTML, /旅途暂告一段落/);
  assert.ok(!events.some((event) => event.type === "voice-prepare"));
  assert.ok(!events.some((event) => event.type === "audio-play"));
});

test("completed story opens its ending with a home link and without emotion text", async () => {
  const browser = makeBrowser({ hash: "#/game", storage: { "wanderer-session": "completed-story" } });
  await settle();

  assert.match(browser.root.innerHTML, /见证者/);
  assert.doesNotMatch(browser.root.innerHTML, /回到首页/);
  assert.doesNotMatch(browser.root.innerHTML, /克制|class="emotion"/);
});

test("free chat shows safe upstream 403 diagnostics without losing the error", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-mode": "live", "wanderer-player-name": "清岚" }, providerError: true });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  assert.match(browser.errorMarkup, /HTTP 403/);
  assert.match(browser.errorMarkup, /example-model/);
  assert.match(browser.errorMarkup, /request-safe-123/);
  assert.match(browser.errorMarkup, /provider-safe-456/);
  assert.match(browser.errorMarkup, /provider\.example\/v1\/chat\/completions/);
  assert.doesNotMatch(browser.errorMarkup, /API密钥|secret|query/);
});

test("free chat hides emotion labels and reserves the assistant reply panel", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" } });
  await browser.click("start-chat");
  assert.doesNotMatch(browser.root.innerHTML, /平静|克制|class="emotion"/);
  assert.match(source, /const pending = message\.pending/);
  assert.match(source, /const reveal = message\.reveal/);
});

test("free chat shows the user message and assistant placeholder before the response arrives", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" } });
  await browser.click("start-chat");
  browser.submitChatPending("你好");
  assert.match(browser.root.innerHTML, /你好/);
  assert.match(browser.root.innerHTML, /value=""/);
  assert.match(browser.root.innerHTML, /「浮浪倾客」正在思考……/);
  await settle();
  assert.match(browser.root.innerHTML, /我听见了/);
  assert.match(browser.root.innerHTML, /围绕问题展开的对话/);
  assert.match(browser.root.innerHTML, /reveal/);
  assert.doesNotMatch(browser.root.innerHTML, /平静|class="emotion"/);
});

test("free chat reveals each streamed chunk from its audio playing event and waits for audio end", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioEnd: true,
    chatStreamChunks: ["第一句。", "第二句！", "第三句收尾。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();

  assert.match(browser.root.innerHTML, /第一句。/);
  assert.doesNotMatch(browser.root.innerHTML, /第二句|第三句/);
  const firstRender = browser.events.findIndex((event) => event.type === "render" && event.html.includes("第一句。"));
  const firstVoicePreparation = browser.events.findIndex((event) => event.type === "voice-prepare");
  const firstAudioStart = browser.events.findIndex((event) => event.type === "audio-play");
  const firstAudioPlaying = browser.events.findIndex((event) => event.type === "audio-playing");
  assert.ok(firstVoicePreparation >= 0 && firstAudioStart > firstVoicePreparation && firstAudioPlaying >= firstAudioStart);
  assert.equal(firstRender, firstAudioPlaying + 1);

  browser.resolveAudioEnd();
  await settle();
  assert.match(browser.root.innerHTML, /第一句。第二句！/);
  assert.doesNotMatch(browser.root.innerHTML, /第三句/);

  browser.resolveAudioEnd();
  await settle();
  assert.match(browser.root.innerHTML, /第一句。第二句！第三句收尾。/);

  browser.resolveAudioEnd();
  await settle();
  assert.match(browser.root.innerHTML, /data-action="copy-reply"/);
  assert.equal(browser.streamReaderCancelled, true);
});

test("free chat keeps speaking when later streamed chunks arrive after the voice queue drained", async () => {
  const chunks = Array.from({ length: 12 }, (_, index) => `第${index + 1}句。`);
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferStreamReads: true,
    deferAudioEnd: true,
    chatStreamChunks: chunks,
  });
  await browser.click("start-chat");

  browser.submitChatPending("请完整回答");
  await settle();

  for (let index = 0; index < chunks.length; index += 1) {
    browser.releaseNextStreamEvent();
    await settle();
    assert.equal(browser.audioPlayback.length, index + 1);
    browser.resolveAudioEnd();
    await settle();
  }
  browser.releaseNextStreamEvent();
  await settle();

  assert.equal(browser.audioPlayback.length, chunks.length);
  assert.match(browser.root.innerHTML, new RegExp(chunks.join("")));
});

test("free chat preloads the next streamed voice while the current chunk is still playing", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioEnd: true,
    chatStreamChunks: ["第一句。", "第二句！", "第三句收尾。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();

  assert.equal(browser.audioPlayback.length, 1);
  assert.equal(browser.events.filter((event) => event.type === "voice-prepare").length, 2);
  assert.doesNotMatch(browser.root.innerHTML, /第二句|第三句/);

  browser.resolveAudioEnd();
  await settle();

  assert.equal(browser.events.filter((event) => event.type === "voice-prepare").length, 3);
});

test("queued streamed voice does not expire while an earlier chunk is still playing", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioReady: true,
    deferAudioEnd: true,
    chatStreamChunks: ["第一段语音。", "第二段语音。", "第三段语音。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("请完整回答");
  await settle();
  browser.resolveAudioReady();
  await settle();
  assert.equal(browser.audioPlayback.length, 1);

  await browser.runTimer(15000);
  assert.equal(browser.audioPlayback.length, 1);
  browser.resolveAudioEnd();
  await settle();
  browser.resolveAudioReady();
  await settle();

  assert.equal(browser.audioPlayback.length, 2);
  assert.match(browser.root.innerHTML, /第一段语音。第二段语音。/);
});

test("streamed chat creates the animated reply bubble once and updates later text in place", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioEnd: true,
    chatStreamChunks: ["第一句。", "第二句！"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();

  const firstChunkRenderCount = browser.events.filter((event) => event.type === "render" && event.html.includes("第一句。")).length;
  const animatedRenderCount = browser.events.filter((event) => event.type === "render" && event.html.includes("chat-message assistant reveal") && event.html.includes("第一句。")).length;
  assert.equal(firstChunkRenderCount, 1);
  assert.equal(animatedRenderCount, 1);

  browser.resolveAudioEnd();
  await settle();

  assert.match(browser.root.innerHTML, /第一句。第二句！/);
  assert.equal(browser.events.filter((event) => event.type === "render" && event.html.includes("第一句。")).length, 1);
  assert.deepEqual(browser.events.filter((event) => event.type === "stream-text").map((event) => event.text), ["第一句。第二句！"]);

  browser.resolveAudioEnd();
  await settle();
});

test("streamed tokens stay cached until their voice actually starts playing", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioReady: true,
    deferAudioEnd: true,
    chatStreamChunks: ["等语音准备好再显示。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();

  assert.equal(browser.events.some((event) => event.type === "voice-prepare"), true);
  assert.doesNotMatch(browser.root.innerHTML, /等语音准备好再显示/);
  assert.equal(browser.events.some((event) => event.type === "audio-play"), false);

  browser.signalAudioLoadedData();
  await settle();
  assert.doesNotMatch(browser.root.innerHTML, /等语音准备好再显示/);
  assert.equal(browser.events.some((event) => event.type === "audio-play"), false);

  browser.resolveAudioReady();
  await settle();

  const textRelease = browser.events.findIndex((event) => event.type === "render" && event.html.includes("等语音准备好再显示。"));
  const audioPlaying = browser.events.findIndex((event) => event.type === "audio-playing");
  assert.ok(audioPlaying >= 0);
  assert.equal(textRelease, audioPlaying + 1);
  assert.match(browser.root.innerHTML, /等语音准备好再显示。/);

  browser.resolveAudioEnd();
  await settle();
});

test("a streamed voice that never becomes playable times out and releases its text", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioReady: true,
    chatStreamChunks: ["语音流卡住时仍能完成回复。", "后续文字也应继续出现。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  assert.doesNotMatch(browser.root.innerHTML, /语音流卡住时仍能完成回复/);

  await browser.runTimer(15000);

  assert.match(browser.root.innerHTML, /语音流卡住时仍能完成回复。后续文字也应继续出现。/);
  assert.equal(browser.audioPlayback.length, 0);
  assert.equal(browser.root.innerHTML.includes("正在思考"), false);
});

test("streamed chat releases cached text when voice preparation fails", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    voiceError: true,
    streamChat: true,
    chatStreamChunks: ["语音失败时仍显示文字。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();

  assert.match(browser.root.innerHTML, /语音失败时仍显示文字。/);
  assert.equal(browser.audioPlayback.length, 0);
  assert.equal(browser.events.filter((event) => event.type === "stream-text").length, 0);
  assert.equal(
    browser.audioInstances.reduce((count, audio) => (
      count
      + (audio.listeners.get("playing")?.size || 0)
      + (audio.listeners.get("ended")?.size || 0)
      + (audio.listeners.get("error")?.size || 0)
    ), 0),
    0,
  );
  assert.doesNotMatch(browser.root.innerHTML, /正在思考/);
});

test("pausing a streamed chat discards buffered later chunks and stops its audio", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioEnd: true,
    chatStreamChunks: ["先显示这一句。", "这一句不应出现！"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  assert.match(browser.root.innerHTML, /先显示这一句。/);
  assert.doesNotMatch(browser.root.innerHTML, /这一句不应出现/);

  await browser.click("pause-chat");
  browser.resolveAudioEnd();
  await settle();

  assert.doesNotMatch(browser.root.innerHTML, /这一句不应出现/);
  assert.equal(browser.audioInstances.every((audio) => audio.paused), true);
  assert.match(browser.root.innerHTML, /话戛然而止，略表腻烦的眼神随清风飘来/);
});

test("pausing before voice readiness discards the cached text without ever rendering it", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioReady: true,
    deferAudioEnd: true,
    chatStreamChunks: ["取消后绝不能闪现。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  assert.doesNotMatch(browser.root.innerHTML, /取消后绝不能闪现/);

  await browser.click("pause-chat");
  browser.resolveAudioReady();
  await settle();

  assert.equal(browser.events.some((event) => event.type === "render" && event.html.includes("取消后绝不能闪现。")), false);
  assert.doesNotMatch(browser.root.innerHTML, /取消后绝不能闪现/);
  assert.match(browser.root.innerHTML, /话戛然而止，略表腻烦的眼神随清风飘来/);
});

test("pausing while streamed audio play is pending settles without releasing cached text", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferVoice: true,
    deferAudioEnd: true,
    chatStreamChunks: ["播放尚未开始时暂停。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  assert.doesNotMatch(browser.root.innerHTML, /播放尚未开始时暂停/);

  await browser.click("pause-chat");
  await settle();

  assert.match(browser.root.innerHTML, /话戛然而止，略表腻烦的眼神随清风飘来/);
  assert.doesNotMatch(browser.root.innerHTML, /播放尚未开始时暂停/);
  assert.equal(browser.events.some((event) => event.type === "audio-playing"), false);
});

test("a resolved play promise without a playing event never releases cached text", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    suppressAudioPlaying: true,
    deferAudioEnd: true,
    chatStreamChunks: ["没有真实播放事件就不能显示。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();

  assert.equal(browser.events.some((event) => event.type === "audio-play"), true);
  assert.equal(browser.events.some((event) => event.type === "audio-playing"), false);
  assert.doesNotMatch(browser.root.innerHTML, /没有真实播放事件就不能显示/);

  await browser.click("pause-chat");
  await settle();
  assert.match(browser.root.innerHTML, /话戛然而止，略表腻烦的眼神随清风飘来/);
});

test("deleting before voice readiness discards cached text and never starts its audio", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioReady: true,
    deferAudioEnd: true,
    chatStreamChunks: ["删除后绝不能闪现。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  await browser.click("delete-chat", { chatSession: "chat-1" });
  browser.resolveAudioReady();
  await settle();

  assert.equal(browser.events.some((event) => event.type === "render" && event.html.includes("删除后绝不能闪现。")), false);
  assert.equal(browser.events.some((event) => event.type === "audio-play"), false);
  assert.doesNotMatch(browser.root.innerHTML, /删除后绝不能闪现/);
  assert.equal(browser.values.has("wanderer-chat-session"), false);
});

test("a failed deletion leaves the cancelled streamed turn in a usable paused state", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferAudioEnd: true,
    deleteChatError: true,
    deferDeleteChat: true,
    chatStreamChunks: ["已经显示的第一句。", "缓存中的第二句不能闪现。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  assert.match(browser.root.innerHTML, /已经显示的第一句/);

  await browser.click("delete-chat", { chatSession: "chat-1" });
  browser.inputChat("删除等待期间输入的新草稿");
  browser.resolveDeleteChat();
  await settle();

  assert.match(browser.errorMarkup, /删除失败/);
  assert.match(browser.root.innerHTML, /话戛然而止，略表腻烦的眼神随清风飘来/);
  assert.doesNotMatch(browser.root.innerHTML, /data-action="pause-chat"/);
  assert.doesNotMatch(browser.root.innerHTML, /缓存中的第二句不能闪现/);
  assert.match(browser.root.innerHTML, /value="删除等待期间输入的新草稿"/);
});

test("free chat replaces send with pause and preserves the message when paused", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, deferChat: true });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  assert.match(browser.root.innerHTML, /「浮浪倾客」正在思考……/);
  assert.match(browser.root.innerHTML, /data-action="pause-chat"/);

  await browser.click("pause-chat");

  assert.match(browser.root.innerHTML, /「浮浪倾客」的话戛然而止，略表腻烦的眼神随清风飘来，示意你接上这场被打断的对话。/);
  assert.doesNotMatch(browser.root.innerHTML, /正在思考……/);
  assert.doesNotMatch(browser.root.innerHTML, /data-action="pause-chat"/);
  assert.match(browser.root.innerHTML, /value="你好"/);
  const call = browser.calls.find((item) => item.url === "/api/chat/sessions/chat-1/messages");
  assert.equal(call.options.signal.aborted, true);
});

test("pausing a restored chat gates an edited resend and ignores the abandoned late reply", async () => {
  const previousMessage = { message: "已保存的问题", reply: "已保存的回答。", emotion: "calm" };
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚", "wanderer-chat-session": "chat-1" },
    chatHistory: [previousMessage],
    deferChat: true,
    deferChatDespiteAbort: true,
    deferChatCancel: true,
    chatReply: "改写问题的新回复。",
  });
  await settle();
  assert.match(browser.root.innerHTML, /已保存的问题/);
  assert.match(browser.root.innerHTML, /已保存的回答/);

  browser.submitChatPending("暂停前的问题");
  await settle();
  const firstPost = browser.calls.find((call) => call.url === "/api/chat/sessions/chat-1/messages");
  assert.ok(firstPost);
  const firstStreamId = firstPost.options.headers["X-Chat-Stream-ID"];

  await browser.click("pause-chat");
  assert.equal(firstPost.options.signal.aborted, true);
  const cancelCall = browser.calls.find((call) => call.url === "/api/chat/sessions/chat-1/cancel");
  assert.ok(cancelCall, "pause sends a server cancellation request");
  assert.equal(cancelCall.options.method, "POST");
  assert.equal(cancelCall.options.keepalive, true);
  assert.equal(cancelCall.options.headers["X-Chat-Stream-ID"], firstStreamId);

  browser.inputChat("改写后的问题");
  browser.submitChatPending("改写后的问题");
  await settle();
  assert.equal(browser.calls.filter((call) => call.url === "/api/chat/sessions/chat-1/messages").length, 1,
    "the edited turn waits for the cancellation acknowledgement");

  browser.resolveChatCancel();
  await settle();
  const posts = browser.calls.filter((call) => call.url === "/api/chat/sessions/chat-1/messages");
  assert.equal(posts.length, 2);
  const nextStreamId = posts[1].options.headers["X-Chat-Stream-ID"];
  assert.notEqual(nextStreamId, firstStreamId);
  assert.equal(JSON.parse(posts[1].options.body).message, "改写后的问题");

  browser.resolveChat({
    message: "暂停前的问题",
    reply: "迟到的废弃回答。",
    messages: [previousMessage, { message: "暂停前的问题", reply: "迟到的废弃回答。", emotion: "calm" }],
  });
  await settle();

  assert.match(browser.root.innerHTML, /改写问题的新回复/);
  assert.doesNotMatch(browser.root.innerHTML, /迟到的废弃回答|暂停前的问题/);
  assert.match(browser.root.innerHTML, /已保存的问题/);
  assert.match(browser.root.innerHTML, /改写后的问题/);
  assert.deepEqual(browser.serverChatMessages.map((message) => message.message), ["已保存的问题", "改写后的问题"]);
});

test("paused chat uses the exact interrupted-dialogue copy", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, deferChat: true });
  await browser.click("start-chat");
  browser.submitChatPending("你好");
  await settle();

  await browser.click("pause-chat");

  assert.match(browser.root.innerHTML, /「浮浪倾客」的话戛然而止，略表腻烦的眼神随清风飘来，示意你接上这场被打断的对话。/);
  assert.doesNotMatch(browser.root.innerHTML, /「浮浪倾客」已暂停思考。/);
});

test("a failed server cancellation remains gated and retries before sending the edited turn", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferChat: true,
    chatCancelFailures: 1,
  });
  await browser.click("start-chat");
  browser.submitChatPending("原问题");
  await settle();

  await browser.click("pause-chat");
  await settle();
  assert.match(browser.errorMarkup, /暂停确认失败，请重试/);

  browser.submitChatPending("改写问题");
  await settle();

  assert.equal(browser.calls.filter((call) => call.url === "/api/chat/sessions/chat-1/cancel").length, 2,
    "a later submit retries server cancellation instead of bypassing an unconfirmed pause");
  const posts = browser.calls.filter((call) => call.url === "/api/chat/sessions/chat-1/messages");
  assert.equal(posts.length, 2);
  assert.equal(JSON.parse(posts[1].options.body).message, "改写问题");
});

test("independent tabs assign distinct stream IDs for the same chat session and request number", async () => {
  const makeTab = () => makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚", "wanderer-chat-session": "chat-1" },
    deferChat: true,
    deferChatDespiteAbort: true,
  });
  const first = makeTab();
  const second = makeTab();
  await Promise.all([settle(), settle()]);
  first.submitChatPending("第一标签页");
  second.submitChatPending("第二标签页");
  await Promise.all([settle(), settle()]);

  const firstStreamId = first.calls.find((call) => call.url === "/api/chat/sessions/chat-1/messages").options.headers["X-Chat-Stream-ID"];
  const secondStreamId = second.calls.find((call) => call.url === "/api/chat/sessions/chat-1/messages").options.headers["X-Chat-Stream-ID"];
  assert.match(firstStreamId, /^chat-1-\d+$/);
  assert.match(secondStreamId, /^chat-1-\d+$/);
  assert.notEqual(firstStreamId, secondStreamId);
});

test("pause reconciles a turn that the server already committed before cancellation", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferStreamReads: true,
    deferAudioEnd: true,
    chatCancelCommitted: true,
    chatStreamChunks: ["服务端已完成提交的回答。"],
  });
  await browser.click("start-chat");
  browser.submitChatPending("已提交的问题");
  await settle();
  browser.releaseNextStreamEvent();
  await settle();
  assert.match(browser.root.innerHTML, /data-action="pause-chat"/);

  await browser.click("pause-chat");
  await settle();

  assert.match(browser.root.innerHTML, /已提交的问题/);
  assert.match(browser.root.innerHTML, /服务端已提交的旧回答/);
  assert.doesNotMatch(browser.root.innerHTML, /话戛然而止，略表腻烦的眼神/);
  assert.doesNotMatch(browser.errorMarkup, /暂停确认失败/);
});

test("free chat keeps the input enabled and preserves a draft typed while the reply is pending", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, deferChat: true });
  await browser.click("start-chat");

  browser.submitChatPending("第一句话");
  await settle();
  assert.equal(browser.chatInputDisabled, false);

  browser.inputChat("下一次准备发送的话");
  browser.resolveChat();
  await settle();

  assert.match(browser.root.innerHTML, /value="下一次准备发送的话"/);
});

test("story journey renders preset options without any free text input", async () => {
  const browser = makeBrowser({ hash: "#/stories", storage: { "wanderer-player-name": "清岚" } });

  await browser.click("select-story", { replayId: "demo_guarded_path" });

  assert.doesNotMatch(browser.root.innerHTML, /data-form="turn"/);
  assert.doesNotMatch(browser.root.innerHTML, /player-message/);
  assert.doesNotMatch(browser.root.innerHTML, /输入你的回应/);
  assert.match(browser.root.innerHTML, /data-action="option"/);
});

test("free chat reply offers copy and regenerate shortcuts", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" } });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  assert.match(browser.root.innerHTML, /data-action="copy-reply"/);
  assert.match(browser.root.innerHTML, /data-action="regenerate-reply"/);

  await browser.click("copy-reply", { index: "0" });
  assert.deepEqual(browser.clipboardWrites, ["我听见了。"]);
});

test("choosing a story option immediately pauses the previous voice playback", async () => {
  const browser = makeBrowser({ hash: "#/stories", storage: { "wanderer-player-name": "清岚" }, voiceEnabled: true });
  await browser.click("select-story", { replayId: "demo_guarded_path" });

  assert.equal(browser.audioInstances.length, 1);
  assert.equal(browser.audioInstances[0].paused, false);
  await browser.click("option", { option: "listen" });

  assert.equal(browser.audioInstances[0].paused, true);
  assert.doesNotMatch(browser.root.innerHTML, /正在整理这段回应/);
});

test("leaving the story journey stops active voice playback", async () => {
  const browser = makeBrowser({ hash: "#/stories", storage: { "wanderer-player-name": "清岚" }, voiceEnabled: true });
  await browser.click("select-story", { replayId: "demo_guarded_path" });
  await browser.setRoute("#/game");
  assert.equal(browser.audioInstances.some((audio) => !audio.paused), true);

  await browser.setRoute("#home");

  assert.equal(browser.audioInstances.every((audio) => audio.paused), true);
});

test("leaving free chat stops active voice playback", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
  });
  await browser.click("start-chat");
  await browser.submitChat("你好");
  assert.equal(browser.audioInstances.some((audio) => !audio.paused), true);

  await browser.setRoute("#/intro");

  assert.equal(browser.audioInstances.every((audio) => audio.paused), true);
});

test("leaving free chat while a streamed reply is speaking keeps the home route after late chunks", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    streamChat: true,
    deferStreamReads: true,
    deferAudioEnd: true,
    chatStreamChunks: ["第一句。", "第二句。"],
  });
  await browser.click("start-chat");

  browser.submitChatPending("你好");
  await settle();
  browser.releaseNextStreamEvent();
  await settle();
  assert.equal(browser.audioInstances.some((audio) => !audio.paused), true);

  await browser.setRoute("#home");
  assert.match(browser.root.innerHTML, /风起异途/);

  browser.releaseNextStreamEvent();
  await settle();
  browser.releaseNextStreamEvent();
  await settle();
  assert.match(browser.root.innerHTML, /风起异途/);
});

test("story replies auto-play without voice controls, while chat uses a pause button", async () => {
  const story = makeBrowser({ hash: "#/stories", storage: { "wanderer-player-name": "清岚", "wanderer-voice-enabled": "true" }, voiceEnabled: true });
  await story.click("select-story", { replayId: "demo_guarded_path" });

  assert.doesNotMatch(story.root.innerHTML, /data-action="play-voice"/);
  assert.doesNotMatch(story.root.innerHTML, /语音已开|语音已关|语音准备中/);
  assert.deepEqual(story.audioPlayback, ["blob:voice-response"]);

  await story.click("option", { option: "listen" });
  await story.runNextTimer();
  assert.doesNotMatch(story.root.innerHTML, /data-action="play-voice"/);
  assert.doesNotMatch(story.root.innerHTML, /语音已开|语音已关|语音准备中/);
  assert.deepEqual(story.audioPlayback, ["blob:voice-response", "blob:voice-response"]);

  const chat = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚", "wanderer-voice-enabled": "true" }, voiceEnabled: true });
  await chat.click("start-chat");
  await chat.submitChat("你好");

  const voiceRequest = chat.calls.find((call) => call.url === "/api/voice/stream");
  assert.match(voiceRequest.requestUrl, /\/api\/voice\/stream\?text=/);
  assert.equal(decodeURIComponent(voiceRequest.requestUrl.split("?text=")[1]), "我听见了。");
  assert.deepEqual(chat.audioPlayback, ["blob:voice-response"]);
  assert.doesNotMatch(chat.root.innerHTML, /data-action="toggle-voice"|data-action="play-chat-voice"|语音已开|语音已关/);
  assert.match(chat.root.innerHTML, /data-action="pause-voice"/);
  assert.match(chat.root.innerHTML, /<div class="chat-actions">[\s\S]*data-action="pause-voice"/);
  const sceneHead = chat.root.innerHTML.match(/<div class="scene-head">[\s\S]*?<p class="chat-disclaimer">/)?.[0] || "";
  assert.doesNotMatch(sceneHead, /data-action="pause-voice"/);
  await chat.click("pause-voice");
  assert.equal(chat.audioInstances[0].paused, true);
  assert.match(chat.root.innerHTML, /继续朗读/);
  await chat.click("pause-voice");
  assert.equal(chat.audioInstances[0].paused, false);
  assert.deepEqual(chat.audioPlayback, ["blob:voice-response", "blob:voice-response"]);
});

test("free chat reveals the generated reply while starting voice synthesis", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, voiceEnabled: true });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  const voiceRequestIndex = browser.events.findIndex((event) => event.type === "voice-request");
  const replyRenderIndex = browser.events.findIndex((event) => event.type === "render" && event.html.includes("我听见了"));
  assert.ok(voiceRequestIndex >= 0);
  assert.ok(replyRenderIndex >= 0);
  assert.ok(replyRenderIndex >= 0);
});

test("free chat keeps the reply visible while voice playback is pending", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferVoice: true,
    voiceEnabled: true,
  });
  await browser.click("start-chat");
  browser.submitChatPending("你好");
  await settle();

  assert.match(browser.root.innerHTML, /我听见了/);
  assert.equal(browser.events.some((event) => event.type === "audio-play"), false);

  browser.resolveVoice();
  await settle();

  const audioPlayIndex = browser.events.findIndex((event) => event.type === "audio-play");
  assert.ok(audioPlayIndex >= 0);
  assert.match(browser.root.innerHTML, /我听见了/);
});

test("free chat reveals a long reply before its real synthesis request finishes", async () => {
  const longReply = "这是一段需要完整朗读的较长回复。".repeat(20);
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferVoice: true,
    voiceEnabled: true,
    chatReply: longReply,
  });
  await browser.click("start-chat");
  browser.submitChatPending("请详细说明");
  await settle();

  assert.ok(browser.timerDelays.some((delay) => delay >= 60000));
  assert.match(browser.root.innerHTML, new RegExp(longReply));
  browser.resolveVoice();
  await settle();

  assert.match(browser.root.innerHTML, new RegExp(longReply));
  assert.deepEqual(browser.audioPlayback, ["blob:voice-response"]);
});

test("free chat unlocks browser audio from the send gesture before delayed synthesis playback", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    audioRequiresGesture: true,
    voiceEnabled: true,
  });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  assert.deepEqual(browser.audioPlayback, ["blob:voice-response"]);
  assert.match(browser.root.innerHTML, /我听见了/);
});

test("story journey unlocks browser audio from the choice gesture before delayed synthesis playback", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    audioRequiresGesture: true,
    voiceEnabled: true,
  });
  await browser.click("select-story", { replayId: "demo_guarded_path" });
  assert.deepEqual(browser.audioPlayback, ["blob:voice-response"]);

  await browser.click("option", { option: "listen" });
  await browser.runNextTimer();
  assert.deepEqual(browser.audioPlayback, ["blob:voice-response", "blob:voice-response"]);
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
});

test("free chat waits for the initial voice status without hiding a reply", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferVoiceStatus: true,
    voiceEnabled: true,
  });
  await browser.click("start-chat");
  browser.submitChatPending("你好");
  await settle();

  assert.match(browser.root.innerHTML, /我听见了/);
  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 0);

  browser.resolveVoiceStatus();
  await settle();

  const audioPlayIndex = browser.events.findIndex((event) => event.type === "audio-play");
  assert.ok(audioPlayIndex >= 0);
  assert.match(browser.root.innerHTML, /我听见了/);
});

test("free chat keeps text available if audio playback is delayed", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferAudioStart: true,
    voiceEnabled: true,
  });
  await browser.click("start-chat");
  browser.submitChatPending("你好");
  await settle();

  assert.match(browser.root.innerHTML, /我听见了/);
  assert.equal(browser.audioPlayback.length, 0);
  browser.resolveAudioStart();
  await settle();
  browser.resolveAudioStart();
  await settle();
  assert.equal(browser.audioPlayback.length, 0);
});

test("pausing chat while voice is synthesizing prevents later playback", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferVoice: true,
    voiceEnabled: true,
  });
  await browser.click("start-chat");
  browser.submitChatPending("你好");
  await settle();

  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 1);
  await browser.click("pause-chat");
  browser.resolveVoice();
  await settle();

  assert.equal(browser.audioPlayback.length, 1);
  assert.match(browser.root.innerHTML, /我听见了/);
});

test("story turns reveal the generated reply while voice playback is pending", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    deferVoice: true,
    deferVoiceAfter: 1,
    voiceEnabled: true,
  });
  const starting = browser.click("select-story", { replayId: "demo_guarded_path" });
  await settle();
  browser.resolveVoice();
  await starting;

  const turning = browser.click("option", { option: "listen" });
  await settle();
  await browser.runNextTimer();
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);

  browser.resolveVoice();
  await turning;
  await settle();

  const audioPlayIndex = browser.events.map((event) => event.type).lastIndexOf("audio-play");
  assert.ok(audioPlayIndex >= 0);
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
});

test("initial story reply stays visible while voice status and synthesis are pending", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    deferVoice: true,
    deferVoiceStatus: true,
    voiceEnabled: true,
  });
  const starting = browser.click("select-story", { replayId: "demo_guarded_path" });
  await settle();
  browser.resolveVoiceStatus();
  await settle();

  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 1);
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);

  browser.resolveVoice();
  await starting;
  await settle();

  const audioPlayIndex = browser.events.findIndex((event) => event.type === "audio-play");
  assert.ok(audioPlayIndex >= 0);
  assert.match(browser.root.innerHTML, /沿着这条线索继续查/);
});

test("free chat starts voice automatically without a voice toggle", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, voiceEnabled: true });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  assert.deepEqual(browser.audioPlayback, ["blob:voice-response"]);
  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 1);
  assert.doesNotMatch(browser.root.innerHTML, /data-action="toggle-voice"|语音已开|语音已关/);
});

test("free chat uses the streaming voice endpoint so long replies can start without waiting for the full WAV", async () => {
  const longReply = "这是一段需要尽快开始朗读的较长回复。".repeat(20);
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    chatReply: longReply,
  });
  await browser.click("start-chat");
  await browser.submitChat("请详细说明");

  assert.equal(browser.calls.some((call) => call.url === "/api/voice/stream"), true);
  assert.match(browser.audioInstances[0].src, /^\/api\/voice\/stream\?text=/);
  assert.match(browser.root.innerHTML, new RegExp(longReply));
});

test("deleting the current chat stops active voice playback and aborts an in-flight reply", async () => {
  const playing = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
  });
  await playing.click("start-chat");
  await playing.submitChat("你好");
  assert.equal(playing.audioInstances.some((audio) => !audio.paused), true);

  await playing.click("delete-chat", { chatSession: "chat-1" });
  assert.equal(playing.audioInstances.every((audio) => audio.paused), true);
  assert.equal(playing.values.has("wanderer-chat-session"), false);

  const pending = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    deferChat: true,
  });
  await pending.click("start-chat");
  pending.submitChatPending("你好");
  await settle();
  assert.match(pending.root.innerHTML, /data-action="pause-chat"/);
  assert.equal(pending.currentChatDeleteDisabled, false);

  await pending.click("delete-chat", { chatSession: "chat-1" });
  assert.equal(pending.calls.find((call) => call.url === "/api/chat/sessions/chat-1/messages").options.signal.aborted, true);
});

test("free chat reveals text immediately when synthesis fails", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceEnabled: true,
    voiceError: true,
  });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  assert.match(browser.root.innerHTML, /我听见了/);
  assert.doesNotMatch(browser.root.innerHTML, /正在思考……/);
  assert.equal(browser.audioPlayback.length, 0);
});

test("voice status retries during model loading and speaks the latest reply once ready", async () => {
  const browser = makeBrowser({
    hash: "#/chat",
    storage: { "wanderer-player-name": "清岚" },
    voiceReadyAfter: 2,
  });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 0);
  assert.match(browser.root.innerHTML, /我听见了/);
  assert.doesNotMatch(browser.root.innerHTML, /语音准备中|语音已开|语音已关/);

  await browser.runNextTimer();
  await settle();

  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 1);
  assert.deepEqual(browser.audioPlayback, ["blob:voice-response"]);
  assert.match(browser.root.innerHTML, /我听见了/);
});

test("story hides voice readiness controls while the local service is loading", async () => {
  const browser = makeBrowser({
    hash: "#/stories",
    storage: { "wanderer-player-name": "清岚" },
    voiceReadyAfter: 2,
  });
  await browser.click("select-story", { replayId: "demo_guarded_path" });

  assert.doesNotMatch(browser.root.innerHTML, /语音已开|语音已关|语音准备中|data-action="play-voice"/);
  assert.equal(browser.calls.filter((call) => call.url === "/api/voice/stream").length, 0);
});

test("free chat regenerate replaces the old reply with a pending panel before revealing the new reply", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, deferRegenerate: true });
  await browser.click("start-chat");
  await browser.submitChat("你好");
  assert.match(browser.root.innerHTML, /我听见了/);

  const regenerating = browser.click("regenerate-reply");
  await settle();

  const regenerateCall = browser.calls.find((call) => call.url === "/api/chat/sessions/chat-1/regenerate");
  assert.ok(regenerateCall);
  assert.match(browser.root.innerHTML, /你好/);
  assert.match(browser.root.innerHTML, /「浮浪倾客」正在思考……/);
  assert.doesNotMatch(browser.root.innerHTML, /我听见了/);

  browser.resolveRegenerate();
  await regenerating;
  await settle();

  assert.match(browser.root.innerHTML, /换一个说法/);
  assert.match(browser.root.innerHTML, /chat-message assistant reveal/);
  assert.doesNotMatch(browser.root.innerHTML, /正在思考……/);
  assert.doesNotMatch(browser.root.innerHTML, /我听见了/);
});

test("free chat regenerate restores the old reply when the request fails", async () => {
  const browser = makeBrowser({ hash: "#/chat", storage: { "wanderer-player-name": "清岚" }, regenerateError: true });
  await browser.click("start-chat");
  await browser.submitChat("你好");

  await browser.click("regenerate-reply");

  assert.match(browser.root.innerHTML, /我听见了/);
  assert.doesNotMatch(browser.root.innerHTML, /正在思考……/);
  assert.match(browser.errorMarkup, /重新生成失败，请稍后重试/);
});

