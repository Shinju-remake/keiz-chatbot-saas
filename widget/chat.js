(function() {
    const API_KEY = "dev-api-key-123"; 
    const BASE_ORIGIN = window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1") 
                        ? window.location.origin 
                        : "https://keiz-chatbot-saas-1.onrender.com";
    const BACKEND_URL = `${BASE_ORIGIN}/chat`;

    let sessionId = localStorage.getItem("shinju_chat_session") || "sess_" + Math.random().toString(36).substr(2, 9);
    localStorage.setItem("shinju_chat_session", sessionId);

    // --- Styles ---
    const styleTag = document.createElement("style");
    styleTag.innerHTML = `
        #shinju-chat-container { position: fixed; bottom: 20px; right: 20px; width: 350px; height: 500px; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); display: none; flex-direction: column; z-index: 10000; font-family: sans-serif; overflow: hidden; }
        #shinju-chat-bubble { position: fixed; bottom: 20px; right: 20px; width: 60px; height: 60px; background: #BB00FF; border-radius: 50%; box-shadow: 0 4px 12px rgba(0,0,0,0.3); cursor: pointer; display: flex; justify-content: center; align-items: center; color: white; font-size: 24px; z-index: 10001; }
        #shinju-chat-header { background: #BB00FF; color: white; padding: 15px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
        #shinju-recording-status { display:none; background:#ff4d4d; color:white; text-align:center; font-size:10px; font-weight:bold; padding:8px; z-index:10001; animation: shinju-flash 0.8s infinite alternate; }
        @keyframes shinju-flash { from { opacity: 1; } to { opacity: 0.5; } }
        #shinju-chat-messages { flex: 1; padding: 10px; overflow-y: auto; background: #f9f9f9; display: flex; flex-direction: column; }
        .shinju-message { margin-bottom: 10px; padding: 8px 12px; border-radius: 8px; max-width: 85%; font-size: 14px; line-height: 1.4; word-wrap: break-word; }
        .shinju-user { background: #BB00FF; color: white; align-self: flex-end; }
        .shinju-bot { background: #e0e0e0; color: #333; align-self: flex-start; }
        #shinju-chat-input-area { padding: 10px; border-top: 1px solid #ddd; display: flex; align-items: center; background: white; }
        #shinju-chat-input { flex: 1; border: none; padding: 10px; outline: none; font-size: 16px; }
        #shinju-mic-btn { background: transparent; border: none; cursor: pointer; font-size: 20px; padding: 5px 10px; color: #888; transition: 0.3s; border-radius: 50%; }
        #shinju-mic-btn.recording { background: #ff4d4d !important; color: white !important; box-shadow: 0 0 20px #ff4d4d; animation: shinju-pulse 1s infinite alternate !important; }
        @keyframes shinju-pulse { from { transform: scale(1); } to { transform: scale(1.2); } }
        .shinju-highlight { color: #BB00FF; font-weight: 700; }
        .shinju-agent-tag { font-size:9px; font-weight:900; color:#BB00FF; margin-bottom:5px; text-transform:uppercase; }
    `;
    document.head.appendChild(styleTag);

    const translations = {
        "en": { "header": "Shinju AI Support", "input": "Type a message...", "send": "Send", "greeting": "Hello! I am Shinju AI. How can I help you today?" },
        "fr": { "header": "Support Shinju AI", "input": "Écrivez un message...", "send": "Envoyer", "greeting": "Bonjour! Je suis Shinju AI. Comment puis-je vous aider aujourd'hui ?" },
        "es": { "header": "Soporte Shinju AI", "input": "Escribe un mensaje...", "send": "Enviar", "greeting": "¡Hola! Soy Shinju AI. ¿Cómo puedo ayudarte hoy?" }
    };

    let currentLang = localStorage.getItem("shinju_chat_lang") || "en";

    const bubble = document.createElement("div");
    bubble.id = "shinju-chat-bubble";
    bubble.innerHTML = "💬";
    document.body.appendChild(bubble);

    const container = document.createElement("div");
    container.id = "shinju-chat-container";
    container.innerHTML = `
        <div id="shinju-chat-header">
            <span id="shinju-chat-title">${translations[currentLang].header}</span>
            <div style="display:flex; align-items:center; gap:10px;">
                <select id="shinju-chat-lang-select" style="background:transparent; color:white; border:1px solid white; border-radius:4px; font-size:12px; cursor:pointer;">
                    <option value="en" ${currentLang === 'en' ? 'selected' : ''}>EN</option>
                    <option value="fr" ${currentLang === 'fr' ? 'selected' : ''}>FR</option>
                    <option value="es" ${currentLang === 'es' ? 'selected' : ''}>ES</option>
                </select>
                <span id="shinju-chat-close" style="cursor:pointer;">✖</span>
            </div>
        </div>
        <div id="shinju-recording-status">● VOICE ACTIVE - LISTENING...</div>
        <div id="shinju-chat-messages"></div>
        <div id="shinju-chat-input-area">
            <input type="text" id="shinju-chat-input" placeholder="${translations[currentLang].input}">
            <button id="shinju-mic-btn" title="Tap to Speak">🎤</button>
            <button id="shinju-chat-send" style="background:#BB00FF; color:white; border:none; padding:8px 15px; border-radius:15px; cursor:pointer; font-weight:bold;">${translations[currentLang].send}</button>
        </div>
    `;
    document.body.appendChild(container);

    const msgContainer = document.getElementById("shinju-chat-messages");
    const input = document.getElementById("shinju-chat-input");
    const sendBtn = document.getElementById("shinju-chat-send");
    const micBtn = document.getElementById("shinju-mic-btn");
    const statusBanner = document.getElementById("shinju-recording-status");

    function appendMessage(text, sender, identity = null) {
        const div = document.createElement("div");
        div.className = `shinju-message shinju-${sender}`;
        if (sender === "bot") {
            const tag = identity ? `<div class="shinju-agent-tag">● ${identity}</div>` : "";
            div.innerHTML = tag + text.replace(/\*\*(.*?)\*\*/g, '<span class="shinju-highlight">$1</span>');
        } else { div.innerText = text; }
        msgContainer.appendChild(div);
        msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        appendMessage(text, "user");
        input.value = "";
        try {
            const res = await fetch(BACKEND_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
                body: JSON.stringify({ message: text, session_id: sessionId, language: currentLang })
            });
            const data = await res.json();
            if (data.reply) {
                appendMessage(data.reply, "bot", data.agent_identity);
            }
        } catch (e) { appendMessage("Connection lost.", "bot"); }
    }

    // --- INSTANT FEEDBACK VOICE LOGIC ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let isRecording = false;
    let recognition = null;

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.lang = currentLang;

        recognition.onstart = () => { isRecording = true; };
        recognition.onresult = (e) => { input.value = e.results[0][0].transcript; sendMessage(); };
        recognition.onend = () => { 
            isRecording = false; 
            micBtn.classList.remove("recording"); 
            statusBanner.style.display = "none";
            input.placeholder = translations[currentLang].input;
        };
        recognition.onerror = (e) => {
            console.error("Speech Recognition Error:", e.error);
            isRecording = false;
            micBtn.classList.remove("recording");
            statusBanner.style.display = "none";
            if (e.error === 'not-allowed') alert("Microphone access denied. Please enable mic permissions for this site.");
        };
    }

    micBtn.onclick = () => {
        if (!SpeechRecognition) {
            alert("Firefox User: Please enable 'media.webspeech.recognition.enable' in about:config.");
            return;
        }

        if (isRecording) {
            recognition.stop();
        } else {
            try {
                // FORCE UI FEEDBACK IMMEDIATELY
                micBtn.classList.add("recording");
                statusBanner.style.display = "block";
                input.placeholder = "Listening...";
                
                recognition.lang = currentLang;
                recognition.start();
            } catch (e) {
                console.error("Critical Mic Failure:", e);
                micBtn.classList.remove("recording");
                statusBanner.style.display = "none";
            }
        }
    };

    sendBtn.onclick = sendMessage;
    input.onkeypress = (e) => { if (e.key === "Enter") sendMessage(); };
    bubble.onclick = () => { container.style.display = "flex"; bubble.style.display = "none"; };
    document.getElementById("shinju-chat-close").onclick = () => { container.style.display = "none"; bubble.style.display = "flex"; };
    
    document.getElementById("shinju-chat-lang-select").onchange = (e) => {
        currentLang = e.target.value;
        localStorage.setItem("shinju_chat_lang", currentLang);
        document.getElementById("shinju-chat-title").innerText = translations[currentLang].header;
        input.placeholder = translations[currentLang].input;
        sendBtn.innerText = translations[currentLang].send;
    };

    setTimeout(() => appendMessage(translations[currentLang].greeting, "bot"), 500);

    async function applyBranding() {
        try {
            const res = await fetch(`${BASE_ORIGIN}/widget/config`, { headers: { "X-API-Key": API_KEY } });
            const config = await res.json();
            if (config.primary_color) {
                document.documentElement.style.setProperty('--primary', config.primary_color);
                ["shinju-chat-bubble", "shinju-chat-header", "shinju-chat-send"].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.style.background = config.primary_color;
                });
            }
        } catch (e) {}
    }
    applyBranding();
})();
