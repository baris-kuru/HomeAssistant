let ws = null;
let messages = [];
let currentUser = "guest";
let isStreaming = false;
let pendingSwitchUser = null;
let userLocation = null;
let pendingAttachments = [];
let authToken = null;
let tokenExpiry = null;
let briefingDismissed = false;
let recentMemories = [];
let currentMemoryId = null;
let sidebarOpen = false;

// ── Auth ──

async function login(user, password) {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: user, password }),
  });
  if (!res.ok) {
    throw new Error("Invalid credentials");
  }
  const data = await res.json();
  authToken = data.access_token;
  currentUser = user;
  localStorage.setItem("auth_token", authToken);
  localStorage.setItem("current_user", user);
  try {
    const payload = JSON.parse(atob(authToken.split(".")[1]));
    tokenExpiry = payload.exp * 1000;
  } catch(e) {}
  return data;
}

function logout() {
  authToken = null;
  tokenExpiry = null;
  currentUser = "guest";
  briefingDismissed = false;
  localStorage.removeItem("auth_token");
  localStorage.removeItem("current_user");
  if (ws) ws.close();
  document.getElementById("loginScreen").style.display = "flex";
  document.getElementById("app").classList.remove("visible");
  document.getElementById("briefingCard").classList.remove("visible");
  document.getElementById("contextBar").style.display = "none";
}

function restoreSession() {
  const saved = localStorage.getItem("auth_token");
  const savedUser = localStorage.getItem("current_user");
  if (saved && savedUser) {
    authToken = saved;
    currentUser = savedUser;
    try {
      const payload = JSON.parse(atob(authToken.split(".")[1]));
      tokenExpiry = payload.exp * 1000;
      if (Date.now() + 300000 < tokenExpiry) {
        startApp(savedUser);
      } else {
        logout();
      }
    } catch(e) {
      logout();
    }
  }
}

function selectUser(user, event) {
  pendingSwitchUser = user;
  document.querySelectorAll("#userBtns button").forEach(b => b.classList.remove("active"));
  event.target.classList.add("active");
  const form = document.getElementById("pwForm");
  form.classList.add("visible");
  document.getElementById("pwInput").focus();
  document.getElementById("loginErr").textContent = "";
}

async function submitLogin() {
  const password = document.getElementById("pwInput").value;
  if (!password) return;
  try {
    await login(pendingSwitchUser, password);
    startApp(pendingSwitchUser);
  } catch (e) {
    document.getElementById("loginErr").textContent = "Wrong password.";
    document.getElementById("pwInput").value = "";
    document.getElementById("pwInput").focus();
  }
}

function fetchLocation() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    pos => { userLocation = { lat: pos.coords.latitude, lon: pos.coords.longitude }; },
    () => {}
  );
}

async function startApp(user) {
  fetchLocation();
  document.getElementById("loginScreen").style.display = "none";
  const app = document.getElementById("app");
  app.classList.add("visible");
  document.getElementById("userPill").textContent = capitalize(user);
  connectWS();

  // Show briefing card first
  await showBriefingCard(user);

  // Load context bar
  await loadContextBar(user);

  // Load memory timeline
  await loadMemoryTimeline(user);
}

async function showBriefingCard(user) {
  // Check if already dismissed today
  const today = new Date().toDateString();
  briefingDismissed = localStorage.getItem(`briefing_dismissed_${user}_${today}`) === "true";
  
  if (briefingDismissed) {
    document.getElementById("briefingCard").classList.remove("visible");
    appendWelcome(user);
    return;
  }
  
  // Show loading state
  const contentDiv = document.getElementById("briefingContent");
  contentDiv.innerHTML = "<p class='loading-text'>Generating your morning briefing...</p>";
  document.getElementById("briefingDate").textContent = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric"
  });
  
  document.getElementById("briefingCard").classList.add("visible");
  
  try {
    const res = await fetch(`/api/briefing/latest`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    
    if (!res.ok) {
      contentDiv.innerHTML = "<p class='error-text'>Failed to load briefing. Please try again.</p>";
      return;
    }
    
    const data = await res.json();
    const briefing = data.briefing;
    
    // Render markdown to HTML (simple conversion)
    contentDiv.innerHTML = renderMarkdown(briefing);
  } catch (e) {
    console.error("Failed to load briefing:", e);
    contentDiv.innerHTML = "<p class='error-text'>Failed to load briefing. Please try again.</p>";
  }
}

function renderMarkdown(text) {
  // Simple markdown to HTML conversion
  let html = text
    // Headers
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Bullet points
    .replace(/^• (.+)$/gm, '<li>$1</li>')
    // Line breaks
    .replace(/\n/g, '<br>');
  
  // Wrap consecutive <li> elements in <ul>
  html = html.replace(/((?:<li>.*<\/li><br>?)+)/g, '<ul>$1</ul>');
  // Clean up <br> inside <ul>
  html = html.replace(/<ul>(.*?)<br>/g, '<ul>$1</ul>');
  html = html.replace(/<\/li><br>/g, '</li>');
  
  return html;
}

async function regenerateBriefing() {
  const contentDiv = document.getElementById("briefingContent");
  contentDiv.innerHTML = "<p class='loading-text'>Regenerating briefing...</p>";
  
  try {
    const res = await fetch(`/api/briefing/send`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    
    if (!res.ok) throw new Error("Regeneration failed");
    
    // Reload the briefing
    await showBriefingCard(currentUser);
  } catch (e) {
    console.error("Failed to regenerate briefing:", e);
    contentDiv.innerHTML = "<p class='error-text'>Failed to regenerate. Please try again.</p>";
  }
}

function dismissBriefing() {
  document.getElementById("briefingCard").classList.remove("visible");
  briefingDismissed = true;
  const today = new Date().toDateString();
  localStorage.setItem(`briefing_dismissed_${currentUser}_${today}`, "true");
  appendWelcome(currentUser);
  
  // Fade out timeline
  const strip = document.getElementById("timelineStrip");
  if (strip) strip.classList.add("fading");
}

async function loadContextBar(user) {
  try {
    const res = await fetch(`/api/context`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (res.ok) {
      const data = await res.json();
      const memories = data.new_memories || 0;
      const events = data.today_events || 0;
      const weather = data.weather || "";

      document.getElementById("ctxMemories").textContent = `🧠 ${memories} new ${memories === 1 ? "memory" : "memories"}`;
      document.getElementById("ctxCalendar").textContent = `📅 ${events} event${events !== 1 ? "s" : ""} today`;
      if (weather) {
        document.getElementById("ctxWeather").textContent = `🌤️ ${weather}`;
      }
      document.getElementById("contextBar").style.display = "flex";
    }
  } catch (e) {
    console.error("Failed to load context:", e);
  }
}

function appendWelcome(user) {
  const container = document.getElementById("messages");
  // Only append if not already present
  if (container.children.length === 0) {
    const div = document.createElement("div");
    div.className = "message assistant";
    div.innerHTML = `<div class="steps"></div><div class="bubble">Hey ${capitalize(user)}! What can I help you with?</div>`;
    container.appendChild(div);
  }
}

// ── Switch User Modal ──

function openSwitch() {
  document.getElementById("switchOverlay").classList.add("open");
  document.getElementById("switchPwForm").classList.remove("visible");
  document.getElementById("switchPwInput").value = "";
  document.getElementById("switchErr").textContent = "";
  document.querySelectorAll("#switchUserBtns button").forEach(b => b.classList.remove("active"));
}

function closeSwitch() {
  document.getElementById("switchOverlay").classList.remove("open");
}

function selectSwitchUser(user) {
  pendingSwitchUser = user;
  document.querySelectorAll("#switchUserBtns button").forEach(b => b.classList.remove("active"));
  event.target.classList.add("active");
  document.getElementById("switchPwForm").classList.add("visible");
  document.getElementById("switchPwInput").focus();
  document.getElementById("switchErr").textContent = "";
}

async function submitSwitch() {
  const password = document.getElementById("switchPwInput").value;
  if (!password) return;
  try {
    await login(pendingSwitchUser, password);
    closeSwitch();
    handleUserSwitched(pendingSwitchUser);
  } catch (e) {
    document.getElementById("switchErr").textContent = "Wrong password.";
    document.getElementById("switchPwInput").value = "";
    document.getElementById("switchPwInput").focus();
  }
}

// ── WebSocket ──

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const tokenParam = authToken ? `?token=${authToken}` : "";
  ws = new WebSocket(`${proto}://${location.host}/ws/chat${tokenParam}`);
  ws.onopen = () => {
    console.log("WebSocket connected");
  };
  ws.onclose = (e) => {
    console.log("WebSocket closed", e.code, e.reason);
    if (e.code === 4003) {
      logout();
    } else {
      setTimeout(connectWS, 1000);
    }
  };
  ws.onerror = (err) => {
    console.error("WebSocket error", err);
  };
}

// ── Chat ──

function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

const TOOL_LABELS = {
  get_weather:          "Checking weather",
  get_calendar_events:  "Reading calendar",
  add_calendar_event:   "Adding to calendar",
  list_devices:         "Checking devices",
  control_device:  "Controlling device",
  recall_memory:   "Reading memory",
  get_memory_guide: "Reading memory guide",
  add_memory:      "Saving to memory",
  forget_memory:        "Forgetting memory",
  consolidate_memories: "Consolidating memories",
  switch_user:     "Switching user",
  change_password: "Changing password",
  list_uploads:    "Listing files",
  read_upload:     "Reading file",
  search_web:      "Searching web",
};

function sendMessage() {
  if (isStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text) return;

  input.value = "";
  input.style.height = "auto";

  messages.push({ role: "user", content: text });
  appendMessage("user", text);

  const msgDiv = appendAssistantMessage();
  const steps = msgDiv.querySelector(".steps");
  const bubble = msgDiv.querySelector(".bubble");
  msgDiv.classList.add("typing");

  isStreaming = true;
  document.getElementById("sendBtn").disabled = true;
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (voiceMode) { setOrbState("thinking"); thinkingSpoken = false; }

  let assistantText = "";

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === "thinking") {
      msgDiv.classList.add("typing");
    } else if (data.type === "status") {
      const pill = document.createElement("span");
      pill.className = "step-pill";
      pill.textContent = data.content;
      steps.appendChild(pill);
      scrollBottom();
    } else if (data.type === "tool_call") {
      const label = TOOL_LABELS[data.name] || data.name;
      const pill = document.createElement("span");
      pill.className = "step-pill";
      pill.textContent = label;
      steps.appendChild(pill);
      scrollBottom();
      if (voiceMode && !thinkingSpoken) {
        thinkingSpoken = true;
        const utt = new SpeechSynthesisUtterance("Let me think…");
        const voice = getNiceVoice();
        if (voice) utt.voice = voice;
        utt.lang = "en-GB";
        utt.rate = 1.0;
        speechSynthesis.speak(utt);
      }
    } else if (data.type === "text") {
      assistantText += data.content;
      bubble.textContent = assistantText;
      msgDiv.classList.remove("typing");
      scrollBottom();
    } else if (data.type === "user_switched") {
      handleUserSwitched(data.user);
    } else if (data.type === "done") {
      isStreaming = false;
      document.getElementById("sendBtn").disabled = false;
      msgDiv.classList.remove("typing");
      if (assistantText) {
        messages.push({ role: "assistant", content: assistantText });
        speak(assistantText);
        // Check for memory references and add sparkle
        if (hasMemoryReference(assistantText)) {
          addMemorySparkle(msgDiv);
        }
      }
    }
  };

  ws.send(JSON.stringify({ messages, user: currentUser, location: userLocation, attachments: pendingAttachments }));
  pendingAttachments = [];
}

function hasMemoryReference(text) {
  const memoryPhrases = [
    "i remember", "you mentioned", "as you noted", "you said",
    "based on your memory", "from our previous conversation",
    "you told me", "according to my memory"
  ];
  const lower = text.toLowerCase();
  return memoryPhrases.some(phrase => lower.includes(phrase));
}

function addMemorySparkle(msgDiv) {
  const sparkle = document.createElement("span");
  sparkle.className = "memory-sparkle";
  sparkle.textContent = "✦ memory";
  sparkle.onclick = () => {
    // Could show memory details on click
    alert("This response references your memories.");
  };
  msgDiv.querySelector(".bubble").appendChild(sparkle);
}

function appendMessage(role, text) {
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.innerHTML = `<div class="bubble">${esc(text)}</div>`;
  container.appendChild(div);
  scrollBottom();
  return div;
}

function appendAssistantMessage() {
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "message assistant";
  div.innerHTML = `<div class="steps"></div><div class="bubble"></div>`;
  container.appendChild(div);
  scrollBottom();
  return div;
}

function scrollBottom() {
  const c = document.getElementById("messages");
  c.scrollTop = c.scrollHeight;
}

// ── Upload ──

async function uploadFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  await fetch("/api/upload", { method: "POST", body: form });
  pendingAttachments.push(file.name);
  e.target.value = "";
  const input = document.getElementById("chatInput");
  input.value = `I just uploaded "${file.name}". Can you take a look?`;
  autoResize(input);
}

// ── Voice (MediaRecorder → Whisper) ──

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

async function toggleMic() {
  const micBtn = document.getElementById("micBtn");
  const input = document.getElementById("chatInput");

  if (isRecording) {
    mediaRecorder.stop();
    isRecording = false;
    return;
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    alert("Microphone access denied.");
    return;
  }

  const mimeType = ["audio/webm", "audio/mp4", "audio/ogg"].find(t => MediaRecorder.isTypeSupported(t)) || "";
  mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  audioChunks = [];

  mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };

  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    isRecording = false;
    if (voiceMode) setOrbState("thinking");
    micBtn.textContent = "⏳";
    input.placeholder = "Transcribing…";

    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
    const ext = (mediaRecorder.mimeType || "").includes("mp4") ? ".m4a" : ".webm";
    const form = new FormData();
    form.append("file", blob, "audio" + ext);

    try {
      const res = await fetch("/api/transcribe", {
        method: "POST",
        headers: { "Authorization": `Bearer ${authToken}` },
        body: form,
      });
      const data = await res.json();
      if (data.transcript) {
        input.value = data.transcript;
        autoResize(input);
        sendMessage();
      }
    } catch (e) {
      console.error("Transcription error:", e);
    }

    micBtn.textContent = "🎤";
    micBtn.classList.remove("recording");
    input.placeholder = "Ask anything…";
  };

  // silence detection
  const audioCtx = new AudioContext();
  const source = audioCtx.createMediaStreamSource(stream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const freqData = new Uint8Array(analyser.frequencyBinCount);
  let hasSpoken = false;
  let silenceTimer = null;

  function checkSilence() {
    if (!isRecording) return;
    analyser.getByteFrequencyData(freqData);
    const avg = freqData.reduce((a, b) => a + b, 0) / freqData.length;
    if (avg > 8) {
      hasSpoken = true;
      clearTimeout(silenceTimer);
      silenceTimer = null;
    } else if (hasSpoken && !silenceTimer) {
      silenceTimer = setTimeout(() => { mediaRecorder.stop(); audioCtx.close(); }, 2000);
    }
    requestAnimationFrame(checkSilence);
  }
  requestAnimationFrame(checkSilence);

  mediaRecorder.start();
  isRecording = true;
  if (voiceMode) setOrbState("listening");
  audioChunks = [];
  input.value = "";
  input.placeholder = "Recording…";
  micBtn.classList.add("recording");
  micBtn.textContent = "⏹";
}

// ── Voice Mode ──

let voiceMode = false;
let thinkingSpoken = false;

// TTS cache: composite key -> audio URL
const ttsCache = new Map();

function detectLanguage(text) {
  const lower = text.toLowerCase();
  // ı, ş, ğ are Turkish-only letters — a strong, unambiguous signal
  const turkishStrong = (lower.match(/[ışğ]/g) || []).length;
  const turkishWords = ["bir", "ve", "için", "değil", "var", "yok", "nasıl", "günaydın", "teşekkür", "merhaba", "evet", "hayır", "ben", "sen", "bu"]
    .filter(w => new RegExp(`(^|\\s)${w}(\\s|$|[.,!?])`).test(lower)).length;
  const germanWords = ["der", "die", "das", "und", "ist", "nicht", "ß", "ich", "mich", "sich"]
    .filter(w => new RegExp(`(^|\\s)${w}(\\s|$|[.,!?])`).test(lower)).length;
  if (turkishStrong > 0 || turkishWords >= 2) return "tr";
  if (germanWords >= 3) return "de";
  return "en"; // default to English
}

// Stop any in-flight TTS (MMS audio + browser speech) before starting new — prevents overlap/echo
let currentAudio = null;
function stopCurrentAudio() {
  try { if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; } } catch (e) {}
  currentAudio = null;
  try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) {}
}

async function speak(text) {
  if (!voiceMode) return;
  
  const language = detectLanguage(text);
  const cacheKey = `${language}:${text.slice(0, 200)}`; // Truncate very long keys

  // Stop the "Let me think…" filler / any prior clip so audio never overlaps
  stopCurrentAudio();

  // Check cache first
  if (ttsCache.has(cacheKey)) {
    const audioUrl = ttsCache.get(cacheKey);
    const audio = new Audio(audioUrl);
    currentAudio = audio;
    audio.onstart = () => setOrbState("speaking");
    audio.onend = () => { if (voiceMode) setOrbState("idle"); };
    audio.onerror = () => { if (voiceMode) setOrbState("idle"); };
    await audio.play();
    return;
  }
  
  setOrbState("speaking");
  
  try {
    const res = await fetch("/api/tts/synthesize", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify({ text, language })
    });
    
    if (!res.ok) throw new Error(`TTS API error: ${res.status}`);

    const wavBlob = await res.blob();
    // User may have exited voice mode while we were fetching — don't start playback
    if (!voiceMode) return;
    const audioUrl = URL.createObjectURL(wavBlob);
    
    // Cache the result
    ttsCache.set(cacheKey, audioUrl);

    const audio = new Audio(audioUrl);
    currentAudio = audio;
    audio.onstart = () => setOrbState("speaking");
    audio.onend = () => { if (voiceMode) setOrbState("idle"); };
    audio.onerror = () => { if (voiceMode) setOrbState("idle"); };
    
    await audio.play();
  } catch (e) {
    console.error("TTS error:", e);
    // Graceful fallback to browser speechSynthesis
    if (window.speechSynthesis) {
      speechSynthesis.cancel();
      const utt = new SpeechSynthesisUtterance(text);
      const voice = getNiceVoice();
      if (voice) utt.voice = voice;
      utt.lang = language === "de" ? "de-DE" : "tr-TR";
      utt.rate = 1.0;
      utt.onstart = () => setOrbState("speaking");
      utt.onend = () => { if (voiceMode) setOrbState("idle"); };
      utt.onerror = () => { if (voiceMode) setOrbState("idle"); };
      speechSynthesis.speak(utt);
    } else {
      if (voiceMode) setOrbState("idle");
    }
  }
}

const NICE_VOICES = ["Zoe", "Serena", "Samantha", "Karen", "Moira", "Kate", "Fiona", "Tessa"];

let cachedVoice = null;

function loadVoice() {
  const voices = speechSynthesis.getVoices();
  if (!voices.length) return;
  for (const name of NICE_VOICES) {
    const v = voices.find(v => v.name.includes(name));
    if (v) { cachedVoice = v; return; }
  }
  cachedVoice = voices.find(v => v.lang === "en-GB")
    || voices.find(v => v.lang.startsWith("en"))
    || null;
}

function getNiceVoice() {
  if (!cachedVoice) loadVoice();
  return cachedVoice;
}

function enterVoiceMode() {
  voiceMode = true;
  document.getElementById("voiceOverlay").classList.add("open");
  setOrbState("idle");
  if (window.speechSynthesis) {
    speechSynthesis.onvoiceschanged = loadVoice;
    loadVoice();
    speechSynthesis.speak(new SpeechSynthesisUtterance(""));
  }
}

function exitVoiceMode() {
  voiceMode = false;
  document.getElementById("voiceOverlay").classList.remove("open");
  stopCurrentAudio();
  // Stop recording too, if a capture is in progress
  try { if (isRecording && mediaRecorder) mediaRecorder.stop(); } catch (e) {}
}

function setOrbState(state) {
  const orb = document.getElementById("voiceOrb");
  const status = document.getElementById("voiceStatus");
  if (orb) orb.dataset.state = state;
  const labels = { idle: "Tap to speak", listening: "Listening…", thinking: "Let me think…", speaking: "Speaking…" };
  if (status) status.textContent = labels[state] || "";
}

function handleOrbTap() {
  const state = document.getElementById("voiceOrb")?.dataset.state;
  if (state === "thinking") return;
  if (state === "speaking") { stopCurrentAudio(); setOrbState("idle"); return; }
  toggleMic();
}

// ── Webcam ──

let webcamStream = null;
let webcamVideo = null;
let webcamActive = false;

async function startWebcam() {
  try {
    webcamStream = await navigator.mediaDevices.getUserMedia({ 
      video: { facingMode: "user", width: 640, height: 480 } 
    });
    
    webcamVideo = document.createElement("video");
    webcamVideo.srcObject = webcamStream;
    webcamVideo.autoplay = true;
    webcamVideo.muted = true;
    webcamVideo.playsInline = true;
    
    webcamActive = true;
    updateWebcamButton(true);
    
    // Add webcam preview to the UI (if not already present)
    let preview = document.getElementById("webcamPreview");
    if (!preview) {
      preview = document.createElement("div");
      preview.id = "webcamPreview";
      preview.className = "webcam-preview";
      preview.appendChild(webcamVideo);
      
      // Insert before the input bar
      const inputBar = document.querySelector(".input-bar");
      inputBar.parentNode.insertBefore(preview, inputBar);
    }
    
    console.log("Webcam started");
  } catch (e) {
    console.error("Failed to start webcam:", e);
    alert("Could not access webcam. Please grant camera permissions.");
  }
}

function stopWebcam() {
  if (webcamStream) {
    webcamStream.getTracks().forEach(track => track.stop());
    webcamStream = null;
  }
  if (webcamVideo) {
    webcamVideo.srcObject = null;
    webcamVideo = null;
  }
  webcamActive = false;
  updateWebcamButton(false);
  
  // Remove preview
  const preview = document.getElementById("webcamPreview");
  if (preview) preview.remove();
}

function updateWebcamButton(active) {
  const btn = document.getElementById("webcamBtn");
  if (btn) {
    btn.textContent = active ? "📸" : "👁️‍🗨️";
    btn.classList.toggle("active", active);
  }
}

function captureFrame() {
  if (!webcamVideo || !webcamActive) return null;
  
  const canvas = document.createElement("canvas");
  canvas.width = webcamVideo.videoWidth;
  canvas.height = webcamVideo.videoHeight;
  
  const ctx = canvas.getContext("2d");
  ctx.drawImage(webcamVideo, 0, 0);
  
  return canvas.toDataURL("image/jpeg", 0.8);
}

function toggleWebcam() {
  if (webcamActive) {
    // If active, capture and send to agent
    sendFrameToAgent();
  } else {
    // If not active, start the webcam
    startWebcam();
  }
}

async function sendFrameToAgent() {
  const frame = captureFrame();
  if (!frame) {
    alert("Webcam is not active");
    return;
  }
  
  // Add user message indicating a photo was taken
  const container = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "message user";
  div.innerHTML = `<div class="bubble">📸 <em>captured a photo</em></div>`;
  container.appendChild(div);
  
  // Add image to message history (base64 data URL)
  messages.push({
    role: "user",
    content: [
      { type: "text", text: "What do you see in this image?" },
      { type: "image_url", image_url: { url: frame } }
    ]
  });
  
  // Trigger agent response
  appendAssistantMessage();
  const assistantDiv = container.lastElementChild;
  assistantDiv.classList.add("typing");
  
  try {
    const response = await fetch("/api/vision/describe", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify({ image: frame })
    });
    
    const data = await response.json();
    
    if (data.description) {
      // Add description to message history
      messages[messages.length - 1] = {
        role: "user",
        content: `What do you see in this image? The agent's vision system reports: ${data.description}`
      };
      
      assistantDiv.classList.remove("typing");
      assistantDiv.querySelector(".bubble").textContent = data.description;
      
      // Add to assistant message history
      messages.push({ role: "assistant", content: data.description });
    } else {
      assistantDiv.classList.remove("typing");
      assistantDiv.querySelector(".bubble").textContent = "I couldn't analyze the image.";
    }
  } catch (e) {
    console.error("Vision analysis failed:", e);
    assistantDiv.classList.remove("typing");
    assistantDiv.querySelector(".bubble").textContent = "Vision system unavailable.";
  }
  
  scrollBottom();
}

// ── Utils ──

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Token Refresh ──

async function refreshToken() {
  if (!authToken) return;
  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}` },
    });
    if (res.ok) {
      const data = await res.json();
      authToken = data.access_token;
      localStorage.setItem("auth_token", authToken);
      try {
        const payload = JSON.parse(atob(authToken.split(".")[1]));
        tokenExpiry = payload.exp * 1000;
      } catch(e) {}
    }
  } catch(e) {
    console.error("Token refresh failed", e);
  }
}

setInterval(async () => {
  if (tokenExpiry && Date.now() + 300000 >= tokenExpiry) {
    await refreshToken();
  }
}, 300000);

// ── Memory Timeline ──

async function loadMemoryTimeline(user) {
  try {
    const res = await fetch(`/api/memories?limit=20`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (!res.ok) return;
    
    const data = await res.json();
    recentMemories = data.memories || [];
    renderTimelinePills();
  } catch (e) {
    console.error("Failed to load memory timeline:", e);
  }
}

function renderTimelinePills() {
  const strip = document.getElementById("timelineStrip");
  strip.innerHTML = "";
  
  if (recentMemories.length === 0) {
    strip.style.display = "none";
    return;
  }
  
  strip.style.display = "flex";
  
  recentMemories.forEach(memory => {
    const pill = document.createElement("div");
    pill.className = "timeline-pill";
    // Truncate title to first 6 words
    const words = (memory.title || memory.content || "").split(/\s+/);
    let title = words.slice(0, 6).join(" ");
    if (words.length > 6) title += "...";
    pill.textContent = title;
    pill.onclick = () => openMemoryModal(memory);
    pill.dataset.memoryId = memory.id;
    strip.appendChild(pill);
  });
}

function openMemoryModal(memory) {
  currentMemoryId = memory.id;
  const overlay = document.getElementById("memoryOverlay");
  const title = document.getElementById("memoryModalTitle");
  const content = document.getElementById("memoryContent");
  const typeBadge = document.getElementById("memoryTypeBadge");
  const dateSpan = document.getElementById("memoryDate");
  const entityDiv = document.getElementById("memoryEntity");
  
  title.textContent = memory.title || "Memory";
  content.textContent = memory.content;
  
  typeBadge.textContent = memory.memory_type || "unknown";
  typeBadge.className = "memory-type-badge" + (memory.memory_type === "short_term" ? " short_term" : "");
  
  dateSpan.textContent = `Added: ${memory.added_on || "unknown"}`;
  
  if (memory.entity && memory.entity !== "self") {
    entityDiv.textContent = `Entity: ${memory.entity}`;
    entityDiv.style.display = "block";
  } else {
    entityDiv.style.display = "none";
  }
  
  overlay.classList.add("open");
}

function closeMemoryModal() {
  document.getElementById("memoryOverlay").classList.remove("open");
  currentMemoryId = null;
}

async function deleteCurrentMemory() {
  if (!currentMemoryId) return;
  
  if (!confirm("Delete this memory? This cannot be undone.")) return;
  
  try {
    const res = await fetch(`/api/memories/${currentMemoryId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    
    if (res.ok) {
      // Remove from local array and re-render
      recentMemories = recentMemories.filter(m => m.id != currentMemoryId);
      renderTimelinePills();
      closeMemoryModal();
    } else {
      alert("Failed to delete memory");
    }
  } catch (e) {
    console.error("Delete memory error:", e);
    alert("Failed to delete memory");
  }
}

function handleUserSwitched(user) {
  currentUser = user;
  briefingDismissed = false;
  document.getElementById("userPill").textContent = capitalize(user);
  messages = [];
  const container = document.getElementById("messages");
  container.innerHTML = "";
  document.getElementById("briefingCard").classList.remove("visible");
  document.getElementById("contextBar").style.display = "none";
  document.getElementById("timelineStrip").style.display = "none";
  appendWelcome(user);
  loadContextBar(user);
  loadMemoryTimeline(user);
  showBriefingCard(user);
}

// Enhanced memory sparkle with actual memory reference
function addMemorySparkle(msgDiv, referencedMemoryId) {
  const bubble = msgDiv.querySelector(".bubble");
  const badge = document.createElement("div");
  badge.className = "memory-reference-badge";
  badge.textContent = "✦ memory";
  badge.onclick = () => {
    if (referencedMemoryId) {
      const mem = recentMemories.find(m => m.id == referencedMemoryId);
      if (mem) openMemoryModal(mem);
    }
  };
  bubble.appendChild(badge);
}

// ── Consolidation Modal ──

async function openConsolidationModal() {
  const overlay = document.getElementById("consolidationOverlay");
  const content = document.getElementById("consolidationContent");
  
  content.innerHTML = "<p>Loading...</p>";
  overlay.classList.add("open");
  
  try {
    const res = await fetch(`/api/memories/consolidate`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (!res.ok) throw new Error("Failed to load consolidation candidates");
    
    const data = await res.json();
    
    if (!data.candidates || data.candidates.length === 0) {
      content.innerHTML = "<p>No memories to consolidate right now.</p>";
      return;
    }
    
    content.innerHTML = "";
    data.candidates.forEach(group => {
      const div = document.createElement("div");
      div.className = "consolidation-group";
      
      const header = document.createElement("div");
      header.className = "consolidation-group-header";
      
      const title = document.createElement("div");
      title.className = "consolidation-group-title";
      title.textContent = `${group.entity} (${group.count} memories, ${group.days_old} days)`;
      
      header.appendChild(title);
      div.appendChild(header);
      
      const list = document.createElement("div");
      list.className = "consolidation-memory-list";
      group.memories.forEach(m => {
        const item = document.createElement("div");
        item.className = "consolidation-memory-item";
        item.textContent = `• ${m.title}`;
        list.appendChild(item);
      });
      div.appendChild(list);
      
      const input = document.createElement("textarea");
      input.className = "consolidation-summary-input";
      input.placeholder = "Write a summary (or use auto-generated)...";
      input.rows = 2;
      div.appendChild(input);
      
      const btn = document.createElement("button");
      btn.className = "btn-consolidate";
      btn.textContent = "Consolidate";
      btn.onclick = () => consolidateGroup(group.entity, group.memories.map(m => m.id), input.value);
      div.appendChild(btn);
      
      content.appendChild(div);
    });
  } catch (e) {
    content.innerHTML = `<p>Error: ${e.message}</p>`;
  }
}

async function consolidateGroup(entity, memoryIds, summary) {
  if (!summary) {
    summary = `Consolidated ${memoryIds.length} memories about ${entity}`;
  }
  
  try {
    const res = await fetch("/api/memories/consolidate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify({
        entity,
        summary,
        memory_ids: memoryIds
      })
    });
    
    if (!res.ok) throw new Error("Consolidation failed");
    
    // Reload memory timeline
    await loadMemoryTimeline(currentUser);
    closeConsolidationModal();
  } catch (e) {
    alert(`Consolidation failed: ${e.message}`);
  }
}

function closeConsolidationModal() {
  document.getElementById("consolidationOverlay").classList.remove("open");
}

// ── Sidebar ──

function toggleSidebar() {
  sidebarOpen = !sidebarOpen;
  document.getElementById("conversationSidebar").classList.toggle("open", sidebarOpen);
  document.getElementById("sidebarOverlay").classList.toggle("open", sidebarOpen);
  if (sidebarOpen) loadConversationList();
}

async function loadConversationList() {
  try {
    const res = await fetch(`/api/conversations?limit=20`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (!res.ok) return;
    
    const data = await res.json();
    const content = document.getElementById("sidebarContent");
    content.innerHTML = "";
    
    if (!data.conversations || data.conversations.length === 0) {
      content.innerHTML = '<p style="padding: 12px; color: var(--muted); font-size: 14px;">No conversations yet.</p>';
      return;
    }
    
    data.conversations.forEach(conv => {
      const item = document.createElement("div");
      item.className = "sidebar-item";
      item.onclick = () => loadConversation(conv.id);
      
      const title = document.createElement("div");
      title.className = "sidebar-item-title";
      title.textContent = conv.title || "Untitled";
      
      const meta = document.createElement("div");
      meta.className = "sidebar-item-meta";
      meta.textContent = new Date(conv.started_at).toLocaleDateString();
      
      item.appendChild(title);
      item.appendChild(meta);
      content.appendChild(item);
    });
  } catch (e) {
    console.error("Failed to load conversations:", e);
  }
}

async function loadConversation(conversationId) {
  try {
    const res = await fetch(`/api/conversations/${conversationId}/messages`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (!res.ok) return;
    
    const data = await res.json();
    
    // Clear current messages and close WS connection for this conversation
    const container = document.getElementById("messages");
    container.innerHTML = "";
    messages = [];
    
    // Render messages
    data.messages.forEach(msg => {
      const div = document.createElement("div");
      div.className = `message ${msg.role}`;
      div.innerHTML = `<div class="bubble">${esc(msg.content)}</div>`;
      container.appendChild(div);
      messages.push({ role: msg.role, content: msg.content });
    });
    
    scrollBottom();
    toggleSidebar(); // Close sidebar after loading
  } catch (e) {
    console.error("Failed to load conversation:", e);
  }
}

// ── Settings Modal ──

async function openSettingsModal() {
  const overlay = document.getElementById("settingsOverlay");
  overlay.classList.add("open");
  
  try {
    const res = await fetch("/api/settings", {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    
    if (!res.ok) throw new Error("Failed to load settings");
    
    const settings = await res.json();
    
    // Populate form
    const langRadio = document.querySelector(`input[name="language"][value="${settings.language}"]`);
    if (langRadio) langRadio.checked = true;
    
    document.getElementById("briefingTime").value = settings.briefing_time || "07:30";
    document.getElementById("briefingWeekends").checked = settings.briefing_on_weekends || false;
    document.getElementById("notificationsEnabled").checked = settings.notifications_enabled !== false;
    document.getElementById("timezone").value = settings.timezone || "Europe/Berlin";
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

async function saveSettings() {
  const language = document.querySelector('input[name="language"]:checked')?.value || "tr";
  const briefing_time = document.getElementById("briefingTime").value;
  const briefing_on_weekends = document.getElementById("briefingWeekends").checked;
  const notifications_enabled = document.getElementById("notificationsEnabled").checked;
  const timezone = document.getElementById("timezone").value;
  
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify({
        language,
        briefing_time,
        briefing_on_weekends,
        notifications_enabled,
        timezone
      })
    });
    
    if (!res.ok) throw new Error("Failed to save settings");
    
    closeSettingsModal();
  } catch (e) {
    console.error("Failed to save settings:", e);
    alert("Failed to save settings. Please try again.");
  }
}

function closeSettingsModal() {
  document.getElementById("settingsOverlay").classList.remove("open");
}

document.addEventListener("DOMContentLoaded", () => {
  restoreSession();
});
