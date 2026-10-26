// 本文件由 codex 辅助生成（外围模块）
const root = document.querySelector("#app");
const toast = document.querySelector("#toast");
const CHARACTER_NAME = "「浮浪倾客」";
const PAUSED_CHAT_COPY = "「浮浪倾客」的话戛然而止，略表腻烦的眼神随清风飘来，示意你接上这场被打断的对话。";
const STORY_REPLY_PLACEHOLDER_MS = 1000;
const VOICE_STATUS_TIMEOUT_MS = 15000;
const VOICE_SYNTHESIS_TIMEOUT_MAX_MS = 240000;
const VOICE_UNLOCK_WAV = "data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA==";

const storyCatalog = [
  {
    id: "archive-wind",
    chapter: "第一篇",
    title: "旧档案里的风声",
    summary: "从一宗遭人改写的旧档案开始，沿着目击者留下的线索，查明真相并决定由谁承担代价。",
    replayId: "demo_guarded_path",
    mark: "風",
  },
  {
    id: "archive-truth",
    chapter: "另一种开端",
    title: "直面委托背后的真相",
    summary: "从开场便追问委托隐瞒的部分；踏入同一条调查主线后，后续场景和结局仍由你的选择决定。",
    replayId: "demo_direct_path",
    mark: "问",
  },
];

const sceneLabels = {
  scene_01: "荒野边缘",
  scene_02: "旧址入口",
  scene_03: "风起之前",
  scene_truth: "被改写的真相",
  scene_task: "委托现场",
  scene_evidence: "证据与代价",
  scene_confrontation: "正面冲突",
  scene_return: "归来的风",
};

const sceneDescriptions = {
  scene_01: "风掠过荒野边缘，委托人的话有几处说不通。「浮浪倾客」停下脚步，等你给出一个理由。",
  scene_02: "旧档案的纸页被潮气卷起，几行关键字迹像是后来才被人补上的。",
  scene_truth: "被撕掉的记录露出半截名字。「浮浪倾客」看着那道裂口，神情比风更冷。",
  scene_03: "你沿着风里残留的气息走向旧址，脚下的砂砾掩着无人愿意提起的代价。",
  scene_witness: "目击者把声音压得很低，仿佛多说一个字，就会让某段过去重新醒来。",
  scene_truth_evidence: "被抹去的痕迹终于连成一线，真相开始显出让人无法回避的形状。",
  scene_confront: "委托人站在风口，仍试图用漂亮话填平记录里的缺口。",
  scene_04: "证据已经足够。现在要决定的不是谁说得更好听，而是谁愿意接住后果。",
  scene_05: "真相摆在两人之间，沉默和坦白都不再是没有代价的选择。",
  scene_06: "风从旧址上方掠过，留下来的脚步声和离开的脚步声一样清楚。",
  scene_07: "最后一段路没有旁观者。你要护住谁，也要承认自己准备失去什么。",
  scene_08: "风停在悬崖边，旅途的答案只剩下最后一个动作。",
};

const endingLabels = {
  evidence_keeper: "见证者",
  burden_bearer: "负重者",
  merciful_wanderer: "留风之人",
  solitary_wanderer: "独行者",
};

const endingEpilogues = {
  evidence_keeper: "你把证据留在众人面前。记住真相不是为了让旧事重演，而是让后来的人不必再替谎言付账。",
  burden_bearer: "你选择接过后果。没有谁因此获得赦免，但至少这一次，责任没有被推给沉默的人。",
  merciful_wanderer: "你没有替任何人宣判，也没有把伤害说成过去。留下的善意很轻，却足够让风继续向前。",
  solitary_wanderer: "你独自离开现场。脚步会渐渐远去，做过的决定却仍属于你。",
};

function sceneLabel(sceneId) {
  return sceneLabels[sceneId] || "旅途片段";
}

function endingLabel(endingId) {
  return endingLabels[endingId] || "未命名结局";
}

function endingEpilogue(endingId, playerName) {
  const closing = endingEpilogues[endingId] || "风会继续吹过这里。你带走的不是答案，而是自己愿意承担的部分。";
  return `${playerName}，${closing}`;
}

const appState = {
  playerName: localStorage.getItem("wanderer-player-name") || "",
  sessionId: localStorage.getItem("wanderer-session"),
  session: null,
  ending: null,
  chatSessionId: localStorage.getItem("wanderer-chat-session"),
  chatSession: null,
  pendingChat: null,
  pausedChat: null,
  chatDraft: "",
  chatAbortController: null,
  chatCancellation: null,
  chatRequestToken: 0,
  regeneratingChat: false,
  revealChatReply: false,
  chatHistory: readChatHistory(),
  chatTitles: readChatTitles(),
  selectedReplayId: "demo_guarded_path",
  resumePromptRequired: false,
  resumePromptDismissed: false,
  busy: false,
  pendingTurn: null,
  voiceAvailable: false,
  voiceConfigured: false,
  voiceStatusChecked: false,
  voiceStatusWaiters: [],
  activeVoiceText: null,
  voiceSequence: 0,
  voiceAbortController: null,
  voiceAudio: null,
  voicePlayer: null,
  voiceUnlocked: false,
  voiceObjectUrl: null,
  preparedVoiceAudios: new Set(),
  voiceStopWaiters: new Set(),
};

function readChatHistory() {
  try {
    const value = JSON.parse(localStorage.getItem("wanderer-chat-history") || "[]");
    return Array.isArray(value) ? value.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function readChatTitles() {
  try {
    const value = JSON.parse(localStorage.getItem("wanderer-chat-titles") || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function rememberChatSession(sessionId) {
  if (!sessionId) return;
  appState.chatHistory = [sessionId, ...appState.chatHistory.filter((id) => id !== sessionId)].slice(0, 8);
  localStorage.setItem("wanderer-chat-history", JSON.stringify(appState.chatHistory));
}

function rememberChatTitle(sessionId, title) {
  if (!sessionId || !title || title === "新对话") return;
  if (appState.chatTitles[sessionId] !== title) {
    appState.chatTitles[sessionId] = title.trim().slice(0, 24);
    localStorage.setItem("wanderer-chat-titles", JSON.stringify(appState.chatTitles));
  }
}

function createChatStreamId(sessionId, requestSequence) {
  const nonce = Math.floor(Math.random() * 10000000000).toString().padStart(10, "0");
  const sequence = `${Date.now()}${nonce}${String(requestSequence).padStart(10, "0")}`;
  return `${sessionId}-${sequence}`;
}

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const normalizePlayerName = (value) => Array.from(String(value ?? "").trim()).slice(0, 20).join("");

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    const details = body.error?.details || {};
    const diagnosticLines = [
      body.request_id ? `本地请求编号：${body.request_id}` : "",
      details.provider_status ? `上游状态：HTTP ${details.provider_status}` : "",
      details.provider_code ? `服务商错误码：${details.provider_code}` : "",
      details.model ? `模型：${details.model}` : "",
      details.endpoint ? `请求地址：${details.endpoint}` : "",
      details.provider_request_id ? `服务商请求编号：${details.provider_request_id}` : "",
    ].filter(Boolean);
    throw new Error([body.error?.message || "请求失败，请稍后重试。", ...diagnosticLines].join("\n"));
  }
  return body.data;
}

async function responseError(response) {
  let body = {};
  try {
    body = await response.json();
  } catch {
    return new Error("请求失败，请稍后重试。");
  }
  const details = body.error?.details || {};
  const diagnosticLines = [
    body.request_id ? `本地请求编号：${body.request_id}` : "",
    details.provider_status ? `上游状态：HTTP ${details.provider_status}` : "",
    details.provider_code ? `服务商错误码：${details.provider_code}` : "",
    details.model ? `模型：${details.model}` : "",
    details.endpoint ? `请求地址：${details.endpoint}` : "",
    details.provider_request_id ? `服务商请求编号：${details.provider_request_id}` : "",
  ].filter(Boolean);
  return new Error([body.error?.message || "请求失败，请稍后重试。", ...diagnosticLines].join("\n"));
}

function parseSseFrame(frame) {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data || data === "[DONE]") return null;
  return JSON.parse(data);
}

async function* readSseEvents(response) {
  if (!response.body?.getReader) throw new Error("浏览器无法读取流式回复，请刷新后重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let boundary = buffer.match(/\r?\n\r?\n/);
      while (boundary?.index !== undefined) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const event = parseSseFrame(frame);
        if (event) yield event;
        boundary = buffer.match(/\r?\n\r?\n/);
      }
      if (done) {
        completed = true;
        break;
      }
    }
    const event = parseSseFrame(buffer);
    if (event) yield event;
  } finally {
    if (!completed) await reader.cancel?.();
    reader.releaseLock?.();
  }
}

async function requestChatReply(path, message, signal, streamId) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
      "X-Chat-Stream-ID": streamId,
    },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  const contentType = response.headers?.get?.("content-type") || "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    const body = await response.json();
    return { result: body.data };
  }
  return { events: readSseEvents(response) };
}

function announce(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.setTimeout(() => { toast.hidden = true; }, 2400);
}

function voicePauseMarkup(text = "") {
  if (!appState.voiceAudio || !appState.activeVoiceText) return "";
  if (text && appState.activeVoiceText !== text) return "";
  const paused = appState.voiceAudio.paused;
  return `<button class="chat-action voice-pause-action" type="button" data-action="pause-voice" aria-pressed="${paused}" title="${paused ? "继续朗读" : "暂停朗读"}">${paused ? "继续朗读" : "暂停朗读"}</button>`;
}

function renderVoiceState() {
  if (appState.pendingChat?.streaming) return;
  if (window.location.hash === "#/chat") renderChat();
  else if (window.location.hash === "#/game" && appState.session) renderRoute();
}

function stopVoice(shouldRender = true) {
  appState.voiceSequence += 1;
  for (const cancel of appState.voiceStopWaiters) cancel();
  appState.voiceStopWaiters.clear();
  appState.voiceAbortController?.abort();
  appState.voiceAbortController = null;
  const audios = new Set(appState.preparedVoiceAudios);
  if (appState.voiceAudio) audios.add(appState.voiceAudio);
  if (appState.voicePlayer?.muted || appState.voicePlayer?.loop) audios.add(appState.voicePlayer);
  for (const audio of audios) {
    audio.pause();
    audio.currentTime = 0;
    audio.src = "";
    audio.load?.();
  }
  appState.preparedVoiceAudios.clear();
  if (appState.voiceObjectUrl && typeof URL?.revokeObjectURL === "function") URL.revokeObjectURL(appState.voiceObjectUrl);
  appState.voiceAudio = null;
  appState.voiceObjectUrl = null;
  appState.activeVoiceText = null;
  resolveVoiceStatusWaiters(false);
  if (shouldRender) renderVoiceState();
}

function voicePlayer() {
  if (typeof Audio !== "function") return null;
  if (!appState.voicePlayer) appState.voicePlayer = new Audio();
  return appState.voicePlayer;
}

function unlockVoiceFromGesture() {
  const audio = voicePlayer();
  if (!audio || appState.voiceUnlocked) return;
  audio.muted = true;
  audio.volume = 0;
  audio.loop = true;
  audio.src = VOICE_UNLOCK_WAV;
  const playback = audio.play();
  if (playback && typeof playback.then === "function") {
    playback.then(() => { appState.voiceUnlocked = true; }).catch(() => {});
  } else {
    appState.voiceUnlocked = true;
  }
}

function resolveVoiceStatusWaiters(available) {
  const waiters = appState.voiceStatusWaiters.splice(0);
  waiters.forEach((resolve) => resolve(available));
}

function waitForVoiceAvailability(timeoutMs = VOICE_STATUS_TIMEOUT_MS) {
  if (appState.voiceAvailable) return Promise.resolve(true);
  if (appState.voiceStatusChecked && !appState.voiceConfigured) return Promise.resolve(false);
  return new Promise((resolve) => {
    let settled = false;
    let waiter;
    let timeoutId;
    const finish = (available) => {
      if (settled) return;
      settled = true;
      appState.voiceStatusWaiters = appState.voiceStatusWaiters.filter((pending) => pending !== waiter);
      window.clearTimeout?.(timeoutId);
      resolve(available);
    };
    waiter = finish;
    appState.voiceStatusWaiters.push(waiter);
    timeoutId = window.setTimeout(() => finish(false), timeoutMs);
  });
}

function voiceSynthesisTimeout(text) {
  const extraTime = Math.max(0, String(text || "").length - 80) * 500;
  return Math.min(VOICE_SYNTHESIS_TIMEOUT_MAX_MS, VOICE_STATUS_TIMEOUT_MS + extraTime);
}

function waitForVoicePlayable(audio, signal, timeoutMs = 0) {
  if (audio.readyState >= 3) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    let timeoutId;
    const finish = (ready) => {
      if (settled) return;
      settled = true;
      window.clearTimeout?.(timeoutId);
      audio.removeEventListener?.("canplay", onReady);
      audio.removeEventListener?.("error", onError);
      signal?.removeEventListener?.("abort", onAbort);
      resolve(ready);
    };
    const onReady = () => finish(true);
    const onError = () => finish(false);
    const onAbort = () => finish(false);
    audio.addEventListener?.("canplay", onReady, { once: true });
    audio.addEventListener?.("error", onError, { once: true });
    signal?.addEventListener?.("abort", onAbort, { once: true });
    if (timeoutMs > 0) timeoutId = window.setTimeout(() => finish(false), timeoutMs);
    if (audio.readyState >= 3) finish(true);
    else if (signal?.aborted) finish(false);
  });
}

async function playVoice(text, { automatic = false, waitUntilPlayable = false, beforePlay = null, shouldRender = true, signal = null } = {}) {
  if (!text || typeof Audio !== "function") return false;
  if (appState.activeVoiceText === text && appState.voiceAudio) {
    appState.voiceAudio.currentTime = 0;
    if (typeof beforePlay === "function") await beforePlay();
    await appState.voiceAudio.play();
    return true;
  }
  stopVoice(false);
  const sequence = ++appState.voiceSequence;
  const ready = automatic ? await waitForVoiceAvailability(VOICE_STATUS_TIMEOUT_MS) : appState.voiceAvailable;
  if (sequence !== appState.voiceSequence || !ready) return false;
  let audio = null;
  let timeoutId;
  const timeout = new Promise((resolve) => {
    timeoutId = window.setTimeout(() => {
      appState.voiceAvailable = false;
      stopVoice(false);
      window.setTimeout(loadVoiceStatus, 2000);
      resolve(false);
    }, voiceSynthesisTimeout(text));
  });
  try {
    const playback = (async () => {
      if (sequence !== appState.voiceSequence) return false;
      audio = voicePlayer() || new Audio();
      audio.pause();
      audio.src = `/api/voice/stream?text=${encodeURIComponent(text)}`;
      audio.muted = false;
      audio.volume = 1;
      audio.loop = false;
      const playable = waitUntilPlayable ? waitForVoicePlayable(audio, signal) : null;
      audio.load?.();
      appState.voiceAudio = audio;
      appState.activeVoiceText = text;
      audio.onended = () => {
        if (sequence === appState.voiceSequence) stopVoice(shouldRender);
      };
      if (playable && !await playable) {
        if (!signal?.aborted) throw new Error("voice audio did not become playable");
        return false;
      }
      if (sequence !== appState.voiceSequence || signal?.aborted) return false;
      if (typeof beforePlay === "function") await beforePlay();
      if (sequence !== appState.voiceSequence || signal?.aborted) return false;
      await audio.play();
      if (sequence !== appState.voiceSequence || audio.paused) return false;
      if (shouldRender) renderVoiceState();
      return true;
    })();
    const started = await Promise.race([playback, timeout]);
    return started;
  } catch (error) {
    if (sequence !== appState.voiceSequence) return false;
    appState.voiceAvailable = false;
    stopVoice(false);
    if (!automatic) announce("语音服务暂不可用，文字对话仍可继续。");
    window.setTimeout(loadVoiceStatus, 2000);
    return false;
  } finally {
    window.clearTimeout?.(timeoutId);
  }
}

function disposePreparedVoice(audio) {
  if (!audio) return;
  appState.preparedVoiceAudios.delete(audio);
  if (appState.voiceAudio === audio) {
    appState.voiceAudio = null;
    appState.activeVoiceText = null;
  }
  audio.pause();
  audio.currentTime = 0;
  audio.src = "";
  audio.load?.();
}

async function prepareStreamingVoice(text, signal, sequence, availability) {
  const available = await availability;
  if (!available || signal?.aborted || sequence !== appState.voiceSequence || typeof Audio !== "function") return null;

  let audio = voicePlayer();
  if (!audio || appState.preparedVoiceAudios.has(audio) || (appState.voiceAudio === audio && !audio.ended)) {
    audio = new Audio();
  }
  audio.pause();
  audio.preload = "auto";
  audio.src = `/api/voice/stream?text=${encodeURIComponent(text)}`;
  audio.muted = false;
  audio.volume = 1;
  audio.loop = false;
  appState.preparedVoiceAudios.add(audio);

  const playable = waitForVoicePlayable(audio, signal);
  audio.load?.();
  const ready = await playable;
  if (!ready || signal?.aborted || sequence !== appState.voiceSequence) {
    disposePreparedVoice(audio);
    return null;
  }
  return { audio, text };
}

async function playPreparedVoiceAndWait(prepared, signal, sequence, releaseText) {
  const { audio, text } = prepared;
  if (signal?.aborted || sequence !== appState.voiceSequence) {
    disposePreparedVoice(audio);
    return false;
  }

  appState.voiceAudio = audio;
  appState.activeVoiceText = text;
  let releasePromise = null;
  let sawPlaying = false;
  let resolveStart;
  let resolveCancelled;
  let startTimeoutId;
  const started = new Promise((resolve) => { resolveStart = resolve; });
  const cancelled = new Promise((resolve) => { resolveCancelled = resolve; });
  const release = () => {
    if (!releasePromise) releasePromise = Promise.resolve(typeof releaseText === "function" ? releaseText() : undefined);
    return releasePromise;
  };
  const onPlaying = () => {
    if (sawPlaying) return;
    sawPlaying = true;
    release();
    resolveStart("playing");
  };
  const onStartError = () => resolveStart("failed");
  const onCancelled = () => {
    resolveStart("cancelled");
    resolveCancelled();
  };
  let cleanupEnded = () => {};
  const ended = new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      cleanupEnded();
      resolve();
    };
    cleanupEnded = () => {
      audio.removeEventListener?.("ended", finish);
      audio.removeEventListener?.("error", finish);
      signal?.removeEventListener?.("abort", finish);
    };
    audio.addEventListener?.("ended", finish, { once: true });
    audio.addEventListener?.("error", finish, { once: true });
    signal?.addEventListener?.("abort", finish, { once: true });
    if (audio.ended || signal?.aborted) finish();
  });
  audio.addEventListener?.("playing", onPlaying, { once: true });
  audio.addEventListener?.("error", onStartError, { once: true });
  signal?.addEventListener?.("abort", onCancelled, { once: true });
  appState.voiceStopWaiters.add(onCancelled);
  startTimeoutId = window.setTimeout(() => resolveStart("failed"), voiceSynthesisTimeout(text));

  try {
    try {
      const playback = audio.play();
      if (playback && typeof playback.catch === "function") playback.catch(onStartError);
    } catch {
      onStartError();
    }
    const outcome = await started;
    window.clearTimeout?.(startTimeoutId);
    if (outcome !== "playing") {
      if (outcome === "failed" && !signal?.aborted && sequence === appState.voiceSequence) await release();
      return false;
    }
    await release();
    if (signal?.aborted || sequence !== appState.voiceSequence || audio.paused) return false;
    await Promise.race([ended, cancelled]);
    return !signal?.aborted && sequence === appState.voiceSequence;
  } catch {
    if (!signal?.aborted && sequence === appState.voiceSequence) await release();
    return false;
  } finally {
    window.clearTimeout?.(startTimeoutId);
    audio.removeEventListener?.("playing", onPlaying);
    audio.removeEventListener?.("error", onStartError);
    signal?.removeEventListener?.("abort", onCancelled);
    appState.voiceStopWaiters.delete(onCancelled);
    cleanupEnded();
    disposePreparedVoice(audio);
  }
}

function createStreamingVoiceQueue(signal, releaseText) {
  const sequence = appState.voiceSequence;
  const availability = waitForVoiceAvailability(VOICE_STATUS_TIMEOUT_MS);
  const items = [];
  let closed = false;
  let cancelled = false;
  let textOnly = false;
  let wake = null;

  const notify = () => {
    const resolve = wake;
    wake = null;
    if (resolve) resolve();
  };
  const isCancelled = () => cancelled || signal?.aborted || sequence !== appState.voiceSequence;
  const ensureLookahead = () => {
    for (const item of items.slice(0, 2)) {
      if (!item.prepared) item.prepared = prepareStreamingVoice(item.text, signal, sequence, availability);
    }
  };
  const waitForSelectedVoice = (item) => {
    let timeoutId;
    let timedOut = false;
    const timeout = new Promise((resolve) => {
      timeoutId = window.setTimeout(() => {
        timedOut = true;
        resolve(null);
      }, voiceSynthesisTimeout(item.text));
    });
    return Promise.race([item.prepared, timeout]).then((prepared) => {
      window.clearTimeout?.(timeoutId);
      if (prepared || !timedOut) return prepared;
      appState.voiceAvailable = false;
      window.setTimeout(loadVoiceStatus, 2000);
      item.prepared.then((latePrepared) => {
        if (latePrepared) disposePreparedVoice(latePrepared.audio);
      }).catch(() => {});
      return null;
    });
  };
  const releaseTextOnlyItems = async () => {
    while (items.length) {
      const item = items.shift();
      await releaseText(item.fullText);
      item.prepared?.then((latePrepared) => {
        if (latePrepared) disposePreparedVoice(latePrepared.audio);
      }).catch(() => {});
    }
  };

  const done = (async () => {
    while (true) {
      if (isCancelled()) return;
      if (!items.length) {
        if (closed) return;
        await new Promise((resolve) => { wake = resolve; });
        continue;
      }

      ensureLookahead();
      const item = items[0];
      const prepared = await waitForSelectedVoice(item);
      if (isCancelled()) return;
      if (!prepared && !appState.voiceAvailable) {
        textOnly = true;
      }
      if (textOnly) {
        await releaseTextOnlyItems();
        continue;
      }
      if (prepared) {
        await playPreparedVoiceAndWait(prepared, signal, sequence, () => releaseText(item.fullText));
      } else {
        await releaseText(item.fullText);
      }
      items.shift();
      ensureLookahead();
    }
  })();

  signal?.addEventListener?.("abort", notify, { once: true });
  return {
    enqueue(text, fullText) {
      if (closed || isCancelled()) return;
      if (textOnly) {
        void releaseText(fullText);
        return;
      }
      items.push({ text, fullText, prepared: null });
      ensureLookahead();
      notify();
    },
    close() {
      closed = true;
      notify();
    },
    cancel() {
      if (cancelled) return;
      cancelled = true;
      closed = true;
      stopVoice(false);
      notify();
    },
    done,
  };
}

function pauseVoice() {
  const audio = appState.voiceAudio;
  if (!audio) return;
  if (audio.paused) {
    unlockVoiceFromGesture();
    const playback = audio.play();
    if (playback && typeof playback.catch === "function") playback.catch(() => {});
  } else {
    audio.pause();
  }
  renderVoiceState();
}

async function loadVoiceStatus() {
  try {
    const result = await request("/api/voice/status");
    appState.voiceConfigured = Boolean(result.configured || result.enabled);
    appState.voiceAvailable = Boolean(result.enabled);
    appState.voiceStatusChecked = true;
    if (!appState.voiceAvailable) {
      if (appState.voiceAudio || appState.voiceAbortController) {
        stopVoice(false);
        renderVoiceState();
      }
      if (appState.voiceConfigured) {
        window.setTimeout(loadVoiceStatus, 2000);
      } else {
        resolveVoiceStatusWaiters(false);
      }
      return;
    }
    resolveVoiceStatusWaiters(true);
  } catch {
    appState.voiceAvailable = false;
    appState.voiceConfigured = false;
    appState.voiceStatusChecked = true;
    resolveVoiceStatusWaiters(false);
  }
}

function setBusy(value) {
  appState.busy = value;
  root.querySelectorAll("button,input").forEach((control) => {
    const keepChatInput = appState.pendingChat && control.matches?.("[data-chat-input]");
    const keepCurrentChatDelete = appState.pendingChat
      && control.dataset.action === "delete-chat"
      && control.dataset.chatSession === appState.chatSessionId;
    control.disabled = value && control.dataset.action !== "pause-chat" && !keepChatInput && !keepCurrentChatDelete;
  });
}

function showError(message) {
  const node = root.querySelector("[data-error], [data-chat-error]");
  if (node) node.innerHTML = `<div class="error-box" role="alert">${escapeHtml(message)}</div>`;
  else announce(message);
}

function renderHome() {
  root.innerHTML = `
    <section class="home">
      <div class="home-mark"><span>風</span></div>
      <div class="eyebrow">文字互动旅途</div>
      <h1>风起异途</h1>
      <p class="home-lead">一段关于选择、真相与承担的短途旅程。<br>风不会替任何人停留，答案也不会自己出现。</p>
      <div class="home-rule"></div>
      <p class="home-sub">纯文字互动 · 约 5 分钟 · 可随时重新开始</p>
      <a class="intro-link" href="#/intro">角色与玩法</a>
      <label class="player-name-field" for="player-name">开始前，先告诉我该如何称呼你</label>
      <input class="player-name-input" id="player-name" data-player-name name="player_name" maxlength="20" autocomplete="nickname" required placeholder="输入你的名字" value="${escapeHtml(appState.playerName)}">
      <div class="home-actions"><a class="primary-btn" data-action="story-directory" href="#/stories">开始剧情旅途 <span aria-hidden="true">→</span></a><a class="secondary-btn home-chat-link" href="#/chat">进入自由对话</a></div>
    </section>`;
}

function showResumeDialog() {
  if (!appState.session || appState.session.state?.is_finished || appState.resumePromptDismissed) return "";
  return `<div class="resume-overlay"><section class="resume-dialog" role="dialog" aria-modal="true" aria-labelledby="resume-title"><div class="eyebrow">未完成的旅途</div><h2 id="resume-title">要继续上一段旅途吗？</h2><p>上一段故事停在「${escapeHtml(sceneLabel(appState.session.state.scene_id))}」，你的选择与进度都还在。</p><div class="resume-actions"><button class="primary-btn" data-action="resume-journey">是，继续上一段旅途</button><button class="secondary-btn" data-action="dismiss-resume">否，暂不继续</button></div></section></div>`;
}

function dismissResumePrompt() {
  appState.resumePromptRequired = false;
  appState.resumePromptDismissed = true;
  if (window.location.hash === "#/game") window.location.hash = "#home";
  renderRoute();
}

function renderStoryDirectory() {
  const rows = storyCatalog.map((story) => `
    <button class="story-row" data-action="select-story" data-replay-id="${escapeHtml(story.replayId)}">
      <span class="story-chapter">${escapeHtml(story.chapter)}</span>
      <span class="story-copy"><strong>${escapeHtml(story.title)}</strong><small>${escapeHtml(story.summary)}</small></span>
      <span class="story-mark" aria-hidden="true">${escapeHtml(story.mark)}</span>
    </button>`).join("");
  root.innerHTML = `<section class="story-directory"><div class="eyebrow">可选故事</div><h1>选择一段旅途</h1><p class="directory-intro">从一宗旧档案篡改事件开始，追寻失踪目击者留下的线索。当前收录的故事会随你的调查选择分出不同走向；更多故事线可在此目录中继续扩展。</p><div class="story-list" aria-label="剧情目录">${rows}</div></section>`;
}

function selectStory(replayId) {
  const story = storyCatalog.find((item) => item.replayId === replayId);
  if (!story) return;
  appState.selectedReplayId = story.replayId;
  if (!appState.playerName) renderNameGate("story", story.replayId);
  else startSession(story.replayId);
}

function renderRoleIntro() {
  root.innerHTML = `
    <section class="intro-page">
      <div class="eyebrow">角色与玩法</div>
      <h1>${CHARACTER_NAME}</h1>
      <p class="intro-lead">身份成谜的浮浪人，心随形至的修验者，如清风一般，活在世间，行在人间。</p>
      <div class="intro-rule"></div>
      <h2>关于这段旅途</h2>
      <p>你可以用自己的名字踏上旅途。须弥近郊一宗关于旧档案遭篡改的委托，把你和${CHARACTER_NAME}带到同一条线索上。追查、保护他人或承担风险，都会留下不同的后果；这段故事不会替任何人开脱。</p>
      <h2>前情概要</h2>
      <p>一名委托人声称，旧档案里记录的事故经过遭人改写，唯一知情的目击者也失去了踪迹。你将在荒野与旧址间寻找证据，判断该保护谁、公开什么，以及谁应该承担代价。</p>
      <h2>操作方式</h2>
       <p>每回合点击当前选项推进剧情。剧情旅途无需网络；自由对话是否连接模型服务由项目配置决定。</p>
      <label class="player-name-field" for="intro-player-name">你希望故事如何称呼你？</label>
      <input class="player-name-input" id="intro-player-name" data-player-name name="player_name" maxlength="20" autocomplete="nickname" required placeholder="输入你的名字" value="${escapeHtml(appState.playerName)}">
      <div class="home-actions"><button class="primary-btn" data-action="start">开始剧情旅途 <span aria-hidden="true">→</span></button><a class="secondary-btn home-chat-link" href="#/chat">进入自由对话</a></div>
    </section>`;
}

function renderNameGate(target = "story", replayId = appState.selectedReplayId) {
  root.innerHTML = `
    <section class="intro-page name-gate">
      <div class="eyebrow">旅途准备</div>
      <h1>先取一个称呼</h1>
      <p>开始前，请告诉「浮浪倾客」该如何称呼你。这个名字会显示在对话和旅途记录中。</p>
      <form data-form="player-name" data-start-target="${target}" data-replay-id="${escapeHtml(replayId)}">
        <label class="player-name-field" for="gate-player-name">你的名字</label>
        <input class="player-name-input" id="gate-player-name" data-player-name name="player_name" maxlength="20" autocomplete="nickname" required placeholder="输入你的名字">
        <button class="primary-btn" type="submit">继续</button>
      </form>
    </section>`;
}

function chatMessageText(message) {
  return message?.role === "user"
    ? (message.content || message.message || message.reply || "")
    : (message.reply || message.content || message.message || "");
}

function renderReplyActions({ index, canRegenerate = false }) {
  const copy = `<button class="chat-action" type="button" data-action="copy-reply" data-index="${index}" title="复制这条回复">复制</button>`;
  const text = appState.chatSession?.messages?.[index]?.reply || "";
  const voice = voicePauseMarkup(text);
  const regenerate = canRegenerate ? `<button class="chat-action" type="button" data-action="regenerate-reply" title="让${CHARACTER_NAME}重新回应这条消息">重新生成</button>` : "";
  return `<div class="chat-actions">${copy}${regenerate}${voice}</div>`;
}

function renderChatMessage(message, playerName = appState.playerName || "你", actions = {}) {
  if (message?.role) {
    const pending = message.pending ? " pending" : "";
    const paused = message.paused ? " paused" : "";
    const reveal = message.reveal ? " reveal" : "";
    const text = message.pending
      ? `${CHARACTER_NAME}正在思考……`
      : (message.paused ? PAUSED_CHAT_COPY : chatMessageText(message));
    const isAssistant = message.role !== "user";
    const showActions = isAssistant && !message.pending && !message.paused && Number.isInteger(actions.index);
    const replyActions = showActions ? renderReplyActions({ index: actions.index, canRegenerate: Boolean(actions.canRegenerate) }) : "";
    const streamingReply = message.streaming ? " data-streaming-reply" : "";
    return `<div class="chat-message ${message.role === "user" ? "user" : "assistant"}${pending}${paused}${reveal}"><div class="chat-speaker">${message.role === "user" ? escapeHtml(playerName) : CHARACTER_NAME}</div><p${streamingReply}>${escapeHtml(text)}</p><time>${escapeHtml(message.created_at || "")}</time>${replyActions}</div>`;
  }
  return `${renderChatMessage({ role: "user", message: message?.message }, playerName)}${renderChatMessage({ role: "assistant", reply: message?.reply, reveal: message?.reveal }, playerName, actions)}`;
}

function chatHistoryMarkup() {
  if (!appState.chatHistory.length) return `<p class="chat-history-empty">尚无历史对话</p>`;
  return appState.chatHistory.map((id) => `<div class="chat-history-entry"><button class="chat-history-item ${id === appState.chatSessionId ? "active" : ""}" data-action="restore-chat" data-chat-session="${escapeHtml(id)}"><span>${escapeHtml(appState.chatTitles[id] || "历史对话")}</span></button><button class="chat-history-delete" data-action="delete-chat" data-chat-session="${escapeHtml(id)}" aria-label="删除这段对话">删除</button></div>`).join("");
}

function renderChat() {
  const session = appState.chatSession;
  const messages = session?.messages || [];
  const chatPlayerName = session?.player_name || appState.playerName || "你";
  const regeneratingMessage = appState.regeneratingChat && messages.length ? messages.at(-1) : null;
  const visibleMessages = regeneratingMessage ? messages.slice(0, -1) : messages;
  const storedMarkup = visibleMessages.length
    ? visibleMessages.map((message, index) => renderChatMessage(
        { ...message, reveal: appState.revealChatReply && index === messages.length - 1 },
        chatPlayerName,
        { index, canRegenerate: !regeneratingMessage && index === messages.length - 1 },
      )).join("")
    : "";
  const regeneratingMarkup = regeneratingMessage
    ? `${renderChatMessage({ role: "user", message: regeneratingMessage.message }, chatPlayerName)}${renderChatMessage({ role: "assistant", pending: true }, chatPlayerName)}`
    : "";
  const pendingMarkup = appState.pendingChat
    ? `${renderChatMessage({ role: "user", message: appState.pendingChat.message }, chatPlayerName)}${renderChatMessage(
        appState.pendingChat.reply
          ? {
              role: "assistant",
              reply: appState.pendingChat.reply,
              reveal: Boolean(appState.pendingChat.streamingReveal),
              streaming: Boolean(appState.pendingChat.streaming),
            }
          : { role: "assistant", pending: true },
        chatPlayerName,
      )}`
    : "";
  const pausedMarkup = appState.pausedChat
    ? `${renderChatMessage({ role: "user", message: appState.pausedChat.message }, chatPlayerName)}${renderChatMessage({ role: "assistant", paused: true }, chatPlayerName)}`
    : "";
  const messageMarkup = messages.length
    ? `${storedMarkup}${regeneratingMarkup}${pendingMarkup}${pausedMarkup}`
    : (pendingMarkup || pausedMarkup || `<div class="chat-empty"><div class="role-symbol" aria-hidden="true">風</div><h2>让风听见你的话</h2><p>这里没有预设选项。你可以直接说出想问的事，${CHARACTER_NAME}会以自己的方式回应。</p></div>`);
  const draft = appState.pausedChat
    ? (appState.chatDraft || appState.pausedChat.draft || appState.pausedChat.message || "")
    : appState.chatDraft;
  const chatSubmitButton = appState.pendingChat
    ? `<button class="primary-btn" type="button" data-action="pause-chat" title="暂停本轮思考">暂停</button>`
    : `<button class="primary-btn" type="submit">发送</button>`;
  root.innerHTML = `
    <section class="chat-layout">
      <aside class="chat-history">
        <div class="chat-history-head"><div><div class="side-label">历史</div><h2>对话记录</h2></div><button class="quiet-btn" data-action="start-chat" title="新建对话">新建</button></div>
        <div class="chat-history-list">${chatHistoryMarkup()}</div>
      </aside>
      <section class="chat-panel" aria-label="自由对话">
        <div class="scene-head"><div><div class="eyebrow">自由对话</div><h1 class="chat-title">与${CHARACTER_NAME}交谈</h1></div></div>
        <p class="chat-disclaimer">自由对话不改变剧情模式的状态与结局。</p>
        <div class="chat-messages" aria-live="polite">${messageMarkup}</div>
        <div data-chat-error></div>
        ${session ? `<form class="input-row chat-input-row" data-form="chat"><label class="screen-reader" for="chat-message">输入对话</label><input id="chat-message" data-chat-input maxlength="1000" value="${escapeHtml(draft)}" placeholder="说点什么……" autocomplete="off">${chatSubmitButton}</form>` : `<button class="primary-btn chat-start-btn" data-action="start-chat">开始自由对话</button>`}
      </section>
    </section>`;
}

function renderGame() {
  const session = appState.session;
  if (!session) return renderHome();
  const state = session.state;
  const response = session.last_response;
  const history = state.history || [];
  const pendingTurn = appState.pendingTurn;
  // The backend records the submitted choice on the current history item before
  // returning its response. Keep that player input visible in the same turn;
  // the response is rendered from last_response below to avoid duplicating it.
  const completedHistory = pendingTurn ? history : history.slice(0, -1);
  const currentPlayerInput = pendingTurn?.playerText || (state.is_finished ? null : history.at(-1)?.player_input);
  const playerName = state.player_name || appState.playerName || "你";
  const lines = completedHistory.map((item) => `<div class="dialogue player"><div class="speaker">${escapeHtml(playerName)}</div><p>${escapeHtml(item.player_input)}</p></div><div class="dialogue"><div class="speaker">${CHARACTER_NAME}</div><p>${escapeHtml(item.response_summary)}</p></div>`).join("");
  const currentLine = currentPlayerInput ? `<div class="dialogue player"><div class="speaker">${escapeHtml(playerName)}</div><p>${escapeHtml(currentPlayerInput)}</p></div>` : "";
  const renderedResponse = pendingTurn ? { reply: "……" } : response;
  const options = pendingTurn ? [] : response?.next_scene?.options || [];
  const ended = state.is_finished;

  if (ended) return renderEnding(response, appState.ending, playerName);

  root.innerHTML = `
    <section class="game-layout">
      <aside class="side-rail">
        <div class="role-symbol" aria-hidden="true">風</div>
        <div><h2>${CHARACTER_NAME}</h2></div>
        <div class="side-divider"></div>
        <div class="side-label">旅途状态</div>
        <div class="status-list">
          <div class="status-item"><span>信任</span><strong>${state.trust}</strong></div>
          <div class="status-item"><span>共情</span><strong>${state.compassion}</strong></div>
          <div class="status-item"><span>承担</span><strong>${state.responsibility}</strong></div>
        </div>
        <button class="quiet-btn" data-action="restart">重新开始</button>
      </aside>
      <section class="conversation" aria-label="互动故事">
        <div class="scene-head"><div class="scene-head-title"><h3 class="scene-title">${escapeHtml(sceneLabel(state.scene_id))}</h3><span class="turn-count">第 ${state.turn_count + 1} 回合</span></div></div>
        ${state.turn_count === 0 ? `<section class="story-briefing" aria-label="前情概要"><h2>前情概要</h2><p>须弥近郊有人委托调查一宗旧档案篡改事件，唯一知情的目击者也失去了踪迹。你将和${CHARACTER_NAME}沿着遗留线索寻找真相，并决定保护谁、公开什么，以及谁来承担代价。</p><p>本局将以「${escapeHtml(playerName)}」称呼你。</p></section>` : ""}
        <p class="scene-copy">${escapeHtml(sceneDescriptions[state.scene_id] || `风从身侧掠过，${CHARACTER_NAME}等着你给出一个理由。`)}</p>
        <div class="dialogue-list">
          ${lines}${currentLine}
          ${renderedResponse ? `<div class="dialogue"><div class="speaker">${CHARACTER_NAME}</div><div class="dialogue-content"><p>${escapeHtml(renderedResponse.reply)}</p></div></div>` : ""}
        </div>
        <div data-error></div>
        ${options.length ? `<div class="options" aria-label="可选行动">${options.map((option) => `<button class="option-btn" data-action="option" data-option="${escapeHtml(option.id)}">${escapeHtml(option.text)}</button>`).join("")}</div>` : ""}
      </section>
    </section>`;
}

function renderEnding(response, ending, playerName = "你") {
  const endingDetails = ending
    ? `<div class="ending-id">结局记录 · ${escapeHtml(endingLabel(ending.ending_id))}</div><h2>${escapeHtml(ending.title)}</h2><p>${escapeHtml(ending.summary)}</p>`
    : `<p class="ending-pending">结局说明暂不可用。</p>`;
  const reply = response?.reply || "风停了片刻。接下来要走哪条路，由你自己决定。";
  root.innerHTML = `<section class="result"><div class="scene-head"><span class="eyebrow">旅途记录</span></div><h1>旅途暂告一段落</h1>${endingDetails}<section class="ending-epilogue"><h2>旅途之后</h2><p>${escapeHtml(endingEpilogue(ending?.ending_id, playerName))}</p></section><div class="ending-quote"><span class="speaker">${CHARACTER_NAME}</span><p>${escapeHtml(reply)}</p></div><button class="primary-btn" data-action="restart">重新开始</button></section>`;
}

async function startSession(replayId = appState.selectedReplayId) {
  const nameInput = root.querySelector("[data-player-name]");
  const playerName = normalizePlayerName(nameInput?.value || appState.playerName);
  if (!playerName) {
    if (nameInput) showError("开始旅途前，请先填写你的名字。最多 20 个字。");
    else renderNameGate("story", replayId);
    return;
  }
  appState.playerName = playerName;
  stopVoice(false);
  unlockVoiceFromGesture();
  appState.pendingTurn = null;
  localStorage.setItem("wanderer-player-name", appState.playerName);
  setBusy(true);
  try {
    const session = await request("/api/sessions", { method: "POST", body: JSON.stringify({ mode: "offline", replay_id: replayId, player_name: appState.playerName }) });
    appState.sessionId = session.session_id;
    appState.session = session;
    appState.ending = session.ending || null;
    localStorage.setItem("wanderer-session", session.session_id);
    appState.selectedReplayId = replayId;
    appState.resumePromptDismissed = false;
    appState.resumePromptRequired = false;
    window.location.hash = "#/game";
    renderGame();
    if (session.last_response?.reply) void playVoice(session.last_response.reply, { automatic: true });
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
}

async function submitTurn(input) {
  if (!appState.sessionId || appState.busy) return;
  stopVoice(false);
  unlockVoiceFromGesture();
  const options = appState.session?.last_response?.next_scene?.options || [];
  const selectedOption = options.find((option) => option.id === input.option_id);
  appState.pendingTurn = {
    playerText: selectedOption?.text || "选择了一个行动",
    startedAt: Date.now(),
  };
  setBusy(true);
  renderGame();
  try {
    const result = await request(`/api/sessions/${appState.sessionId}/turn`, { method: "POST", body: JSON.stringify(input) });
    const elapsed = Date.now() - appState.pendingTurn.startedAt;
    const remaining = Math.max(0, STORY_REPLY_PLACEHOLDER_MS - elapsed);
    if (remaining > 0) await new Promise((resolve) => window.setTimeout(resolve, remaining));
    appState.session.state = result.state;
    appState.session.last_response = result.response;
    appState.ending = result.ending || null;
    appState.pendingTurn = null;
    renderGame();
    if (result.response?.reply) void playVoice(result.response.reply, { automatic: true });
  } catch (error) {
    appState.pendingTurn = null;
    renderGame();
    showError(error.message);
  } finally {
    appState.busy = false;
    setBusy(false);
  }
}

async function restoreSession() {
  if (!appState.sessionId) return;
  try {
    appState.pendingTurn = null;
    appState.session = await request(`/api/sessions/${appState.sessionId}`);
    appState.ending = appState.session.ending || null;
    appState.resumePromptRequired = !appState.session.state?.is_finished;
    if (!appState.playerName && appState.session.state?.player_name) {
      appState.playerName = appState.session.state.player_name;
      localStorage.setItem("wanderer-player-name", appState.playerName);
    }
    renderRoute();
  } catch {
    localStorage.removeItem("wanderer-session");
    appState.sessionId = null;
    appState.session = null;
    renderRoute();
  }
}

async function restartSession() {
  if (!appState.sessionId) return startSession();
  stopVoice(false);
  setBusy(true);
  try {
    appState.pendingTurn = null;
    const session = await request(`/api/sessions/${appState.sessionId}/restart`, { method: "POST" });
    appState.sessionId = session.session_id;
    appState.session = session;
    appState.ending = session.ending || null;
    localStorage.setItem("wanderer-session", session.session_id);
    window.location.hash = "#/game";
    renderGame();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
}

async function startChatSession() {
  if (!appState.playerName) {
    renderNameGate("chat");
    return;
  }
  stopVoice(false);
  appState.pendingChat = null;
  appState.pausedChat = null;
  appState.chatDraft = "";
  setBusy(true);
  try {
    const session = await request("/api/chat/sessions", { method: "POST", body: JSON.stringify({ player_name: appState.playerName || "同行者" }) });
    appState.chatSessionId = session.chat_session_id || session.session_id;
    appState.chatSession = session;
    rememberChatSession(appState.chatSessionId);
    localStorage.setItem("wanderer-chat-session", appState.chatSessionId);
    renderChat();
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
}

async function restoreChatSession(sessionId = appState.chatSessionId) {
  if (!sessionId) return;
  stopVoice(false);
  try {
    appState.chatSession = await request(`/api/chat/sessions/${sessionId}`);
    appState.chatSessionId = appState.chatSession.chat_session_id || appState.chatSession.session_id || sessionId;
    if (!appState.playerName && appState.chatSession.player_name) {
      appState.playerName = appState.chatSession.player_name;
      localStorage.setItem("wanderer-player-name", appState.playerName);
    }
    rememberChatSession(appState.chatSessionId);
    rememberChatTitle(appState.chatSessionId, appState.chatSession.title);
    localStorage.setItem("wanderer-chat-session", appState.chatSessionId);
    appState.pendingChat = null;
    appState.pausedChat = null;
    appState.chatDraft = "";
    renderChat();
  } catch (error) {
    if (sessionId === appState.chatSessionId) {
      appState.chatSession = null;
      localStorage.removeItem("wanderer-chat-session");
    }
    showError(error.message);
  }
}

function chatAbortError() {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
}

function releaseStreamingChatText(text, requestToken, sessionId) {
  if (requestToken !== appState.chatRequestToken || sessionId !== appState.chatSessionId) return;
  const pending = appState.pendingChat;
  if (!pending?.streaming) return;
  pending.reply = text;
  if (!pending.streamingStarted) {
    if (!text) return;
    pending.streamingStarted = true;
    pending.streamingReveal = true;
    renderChat();
    pending.streamingReveal = false;
    return;
  }
  const replyNode = root.querySelector("[data-streaming-reply]");
  if (replyNode) replyNode.textContent = text;
}

async function consumeChatEvents(events, { message, signal, requestToken, sessionId, streamId }) {
  const currentPending = appState.pendingChat;
  if (signal.aborted
    || requestToken !== appState.chatRequestToken
    || sessionId !== appState.chatSessionId
    || currentPending?.streamId !== streamId) {
    throw chatAbortError();
  }
  let completed = null;
  appState.pendingChat = {
    ...currentPending,
    message,
    streaming: true,
    streamingStarted: false,
    streamingReveal: false,
    bufferedReply: appState.pendingChat?.reply || "",
  };
  const releaseText = (text) => releaseStreamingChatText(text, requestToken, sessionId);
  let voiceQueue = createStreamingVoiceQueue(signal, releaseText);
  try {
    for await (const event of events) {
      if (signal.aborted || requestToken !== appState.chatRequestToken || sessionId !== appState.chatSessionId) {
        throw chatAbortError();
      }
      if (event?.type === "text" && typeof event.delta === "string" && event.delta) {
        const bufferedReply = `${appState.pendingChat?.bufferedReply || ""}${event.delta}`;
        appState.pendingChat.bufferedReply = bufferedReply;
        voiceQueue.enqueue(event.delta, bufferedReply);
      } else if (event?.type === "reset") {
        voiceQueue.cancel();
        voiceQueue = createStreamingVoiceQueue(signal, releaseText);
        appState.pendingChat.bufferedReply = "";
        releaseText("");
      } else if (event?.type === "error") {
        throw new Error(event.message || "模型服务暂时无法完成回复，请稍后重试。");
      } else if (event?.type === "done") {
        completed = event;
        break;
      }
    }
    if (!completed) throw new Error("流式回复意外中断，请重试。");
    voiceQueue.close();
    await voiceQueue.done;
    if (signal.aborted || requestToken !== appState.chatRequestToken || sessionId !== appState.chatSessionId) {
      throw chatAbortError();
    }
    return completed;
  } catch (error) {
    voiceQueue.cancel();
    throw error;
  } finally {
    voiceQueue.close();
  }
}

async function submitChat(message) {
  if (!appState.chatSessionId || appState.busy) return;
  const sessionId = appState.chatSessionId;
  const cancellation = appState.chatCancellation?.sessionId === sessionId ? appState.chatCancellation : null;
  if (cancellation) {
    const waitToken = ++appState.chatRequestToken;
    appState.chatDraft = message;
    setBusy(true);
    try {
      const result = await cancellation.request();
      if (!result.confirmed) {
        if (waitToken === appState.chatRequestToken && sessionId === appState.chatSessionId) {
          showError(result.error?.message || "服务端未确认本轮已暂停，请检查当前对话后重试。");
        }
        return;
      }
    } finally {
      if (waitToken === appState.chatRequestToken && sessionId === appState.chatSessionId) setBusy(false);
    }
    if (waitToken !== appState.chatRequestToken || sessionId !== appState.chatSessionId) return;
    if (appState.chatCancellation === cancellation) appState.chatCancellation = null;
    return submitChat(message);
  }
  const requestToken = ++appState.chatRequestToken;
  stopVoice(false);
  unlockVoiceFromGesture();
  appState.chatDraft = "";
  const streamId = createChatStreamId(sessionId, requestToken);
  appState.pendingChat = {
    message,
    streamId,
    previousMessageCount: appState.chatSession?.messages?.length || 0,
  };
  appState.pausedChat = null;
  const controller = new AbortController();
  appState.chatAbortController = controller;
  renderChat();
  setBusy(true);
  try {
    const signal = controller.signal;
    const reply = await requestChatReply(
      `/api/chat/sessions/${sessionId}/messages`,
      message,
      signal,
      streamId,
    );
    const result = reply.events
      ? await consumeChatEvents(reply.events, { message, signal, requestToken, sessionId, streamId })
      : reply.result;
    if (requestToken !== appState.chatRequestToken || sessionId !== appState.chatSessionId) return;
    const title = result.title || result.response?.title || appState.chatSession.title;
    const nextChatSession = { ...appState.chatSession, ...result, title, session_id: result.session_id || appState.chatSessionId };
    appState.chatSession = nextChatSession;
    rememberChatTitle(appState.chatSessionId, title);
    appState.pendingChat = null;
    appState.pausedChat = null;
    appState.revealChatReply = !reply.events;
    renderChat();
    if (!reply.events && result.response?.reply) void playVoice(result.response.reply, { automatic: true });
    window.setTimeout(() => { appState.revealChatReply = false; }, 700);
  } catch (error) {
    if (requestToken !== appState.chatRequestToken || sessionId !== appState.chatSessionId) return;
    if (error?.name === "AbortError" || appState.chatAbortController?.signal.aborted) {
      appState.pausedChat = { message, draft: appState.chatDraft || message, streamId };
      appState.pendingChat = null;
      renderChat();
      return;
    }
    appState.pendingChat = null;
    renderChat();
    showError(error.message);
  } finally {
    if (requestToken === appState.chatRequestToken) {
      appState.chatAbortController = null;
      appState.busy = false;
      setBusy(false);
    }
  }
}

function pauseChat() {
  const pending = appState.pendingChat;
  const controller = appState.chatAbortController;
  const sessionId = appState.chatSessionId;
  if (!pending || !controller || !sessionId || !pending.streamId) return;
  const draft = appState.chatDraft || pending.message;
  controller.abort();
  appState.chatRequestToken += 1;
  appState.chatAbortController = null;
  appState.pendingChat = null;
  appState.pausedChat = { message: pending.message, draft, streamId: pending.streamId };
  appState.chatDraft = draft;
  appState.busy = false;
  setBusy(false);
  stopVoice(false);
  renderChat();

  const cancellation = {
    sessionId,
    streamId: pending.streamId,
    message: pending.message,
    previousMessageCount: pending.previousMessageCount || 0,
    promise: null,
  };
  const requestCancellation = () => {
    if (cancellation.promise) return cancellation.promise;
    const attempt = (async () => {
      try {
        const response = await fetch(`/api/chat/sessions/${sessionId}/cancel`, {
          method: "POST",
          headers: { "X-Chat-Stream-ID": pending.streamId },
          keepalive: true,
        });
        if (!response.ok) throw await responseError(response);
        const body = await response.json();
        if (body?.data?.cancelled === true) return { confirmed: true };

        // A false result can mean the server committed just before pause won
        // the network race. Preserve that completed turn, but never resend
        // until the authoritative session confirms it is in history.
        const completedSession = await request(`/api/chat/sessions/${sessionId}`);
        const newMessages = completedSession.messages?.slice(cancellation.previousMessageCount) || [];
        const committed = newMessages.some((item) => item.message === cancellation.message);
        if (committed) return { confirmed: true, completedSession };
        throw new Error("服务端未确认本轮已暂停，请检查当前对话后重试。");
      } catch (error) {
        return { confirmed: false, error };
      }
    })();
    cancellation.promise = attempt;
    attempt.then((result) => {
      if (cancellation.promise === attempt) cancellation.promise = null;
      if (result.confirmed && result.completedSession && appState.chatSessionId === sessionId) {
        appState.chatSession = result.completedSession;
        appState.pausedChat = null;
        renderChat();
      }
    });
    return attempt;
  };
  cancellation.request = requestCancellation;
  const initialCancellation = requestCancellation();
  appState.chatCancellation = cancellation;
  initialCancellation.then((result) => {
    if (appState.chatCancellation !== cancellation) return;
    if (result.confirmed) {
      appState.chatCancellation = null;
      return;
    }
    if (appState.chatSessionId === sessionId && appState.pausedChat?.streamId === pending.streamId) {
      showError(result.error?.message || "服务端未确认本轮已暂停，请检查当前对话后重试。");
    }
  });
}

async function deleteChatSession(sessionId) {
  if (!sessionId || !window.confirm("删除这段历史对话？删除后无法恢复。")) return;
  const isCurrentSession = sessionId === appState.chatSessionId;
  const cancelledPending = isCurrentSession ? appState.pendingChat : null;
  if (isCurrentSession) {
    appState.chatRequestToken += 1;
    appState.chatAbortController?.abort();
    appState.chatAbortController = null;
    stopVoice(false);
  }
  setBusy(true);
  try {
    await request(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
    appState.chatHistory = appState.chatHistory.filter((id) => id !== sessionId);
    delete appState.chatTitles[sessionId];
    localStorage.setItem("wanderer-chat-history", JSON.stringify(appState.chatHistory));
    localStorage.setItem("wanderer-chat-titles", JSON.stringify(appState.chatTitles));
    if (sessionId === appState.chatSessionId) {
      appState.chatSessionId = null;
      appState.chatSession = null;
      appState.pendingChat = null;
      appState.pausedChat = null;
      appState.chatDraft = "";
      appState.chatRequestToken += 1;
      localStorage.removeItem("wanderer-chat-session");
    }
    renderChat();
    announce("这段对话已删除");
  } catch (error) {
    if (isCurrentSession && cancelledPending && sessionId === appState.chatSessionId) {
      appState.pendingChat = null;
      appState.pausedChat = { message: cancelledPending.message, draft: appState.chatDraft };
      renderChat();
    }
    showError(error.message);
  } finally {
    appState.busy = false;
    root.querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
  }
}

async function writeClipboard(text) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    if (typeof document !== "undefined" && typeof document.createElement === "function" && document.body) {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const copied = typeof document.execCommand === "function" ? document.execCommand("copy") : false;
      document.body.removeChild(area);
      return Boolean(copied);
    }
  } catch {
    return false;
  }
  return false;
}

async function copyReply(index) {
  const messages = appState.chatSession?.messages || [];
  const text = messages[index]?.reply;
  if (!text) return;
  const copied = await writeClipboard(text);
  announce(copied ? `已复制${CHARACTER_NAME}的回复` : "复制失败，请重试");
}

async function regenerateReply() {
  if (!appState.chatSessionId || appState.busy) return;
  stopVoice(false);
  unlockVoiceFromGesture();
  appState.regeneratingChat = true;
  renderChat();
  setBusy(true);
  try {
    const result = await request(`/api/chat/sessions/${appState.chatSessionId}/regenerate`, { method: "POST" });
    const nextChatSession = { ...appState.chatSession, ...result, session_id: result.session_id || appState.chatSessionId };
    appState.chatSession = nextChatSession;
    appState.regeneratingChat = false;
    appState.revealChatReply = true;
    renderChat();
    if (result.response?.reply) void playVoice(result.response.reply, { automatic: true });
    window.setTimeout(() => { appState.revealChatReply = false; }, 700);
  } catch (error) {
    appState.regeneratingChat = false;
    renderChat();
    showError(error.message);
  } finally {
    appState.busy = false;
    root.querySelectorAll("button,input").forEach((control) => { control.disabled = false; });
  }
}

root.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  if (button.dataset.action === "pause-chat") {
    pauseChat();
    return;
  }
  if (button.dataset.action === "pause-voice") {
    pauseVoice();
    return;
  }
  if (button.dataset.action === "delete-chat") {
    deleteChatSession(button.dataset.chatSession);
    return;
  }
  if (appState.busy) return;
  if (button.dataset.action === "start") startSession();
  if (button.dataset.action === "select-story") selectStory(button.dataset.replayId);
  if (button.dataset.action === "resume-journey" && appState.session && !appState.session.state?.is_finished) {
    appState.resumePromptRequired = false;
    appState.resumePromptDismissed = true;
    window.location.hash = "#/game";
    renderGame();
  }
  if (button.dataset.action === "dismiss-resume") dismissResumePrompt();
  if (button.dataset.action === "restart") restartSession();
  if (button.dataset.action === "option") submitTurn({ option_id: button.dataset.option });
  if (button.dataset.action === "start-chat") startChatSession();
  if (button.dataset.action === "restore-chat") restoreChatSession(button.dataset.chatSession);
  if (button.dataset.action === "copy-reply") copyReply(Number(button.dataset.index));
  if (button.dataset.action === "regenerate-reply") regenerateReply();
});

function renderRoute() {
  const route = window.location.hash || "#home";
  if (route === "#/intro") renderRoleIntro();
  else if (route === "#/stories") renderStoryDirectory();
  else if (route === "#/game") {
    if (appState.session) renderGame();
    else renderHome();
  }
  else if (route === "#/chat") {
    renderChat();
    if (!appState.chatSession && appState.chatSessionId) restoreChatSession();
  }
  else renderHome();
  if (appState.resumePromptRequired && appState.session && !appState.session.state?.is_finished && !appState.resumePromptDismissed) {
    root.innerHTML += showResumeDialog();
  }
}

window.addEventListener("hashchange", renderRoute);

root.addEventListener("input", (event) => {
  if (event.target.matches("[data-player-name]")) {
    appState.playerName = normalizePlayerName(event.target.value);
    localStorage.setItem("wanderer-player-name", appState.playerName);
    return;
  }
  if (event.target.matches("[data-chat-input]")) {
    appState.chatDraft = String(event.target.value || "").slice(0, 1000);
  }
});

root.addEventListener("submit", (event) => {
  if (event.target.matches('[data-form="player-name"]')) {
    event.preventDefault();
    const input = event.target.querySelector("[data-player-name]");
    const name = normalizePlayerName(input.value);
    if (!name) return showError("请填写名字后再继续。");
    appState.playerName = name;
    localStorage.setItem("wanderer-player-name", appState.playerName);
    if (event.target.dataset.startTarget === "chat") startChatSession();
    else startSession(event.target.dataset.replayId || appState.selectedReplayId);
    return;
  }
  if (!event.target.matches('[data-form="chat"]')) return;
  event.preventDefault();
  const input = event.target.querySelector("input");
  if (!input.value.trim()) return showError(`先输入一句话，再发送给${CHARACTER_NAME}。`);
  submitChat(input.value.trim());
});

renderRoute();
restoreSession();
loadVoiceStatus();
