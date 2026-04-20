(function() {
    const API_KEY = "dev-api-key-123"; 
    const BASE_ORIGIN = window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1") 
                        ? window.location.origin 
                        : "https://keiz-chatbot-saas-1.onrender.com";
    const BACKEND_URL = `${BASE_ORIGIN}/chat`;
    const TRANSCRIBE_URL = `${BASE_ORIGIN}/transcribe`;

    let sessionId = localStorage.getItem("shinju_chat_session") || "sess_" + Math.random().toString(36).substr(2, 9);
    localStorage.setItem("shinju_chat_session", sessionId);

    // --- ELITE UI STYLES ---
    const styleTag = document.createElement("style");
    styleTag.innerHTML = `
        #shinju-chat-container { position: fixed; bottom: 20px; right: 20px; width: 350px; height: 500px; background: #fff; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); display: none; flex-direction: column; z-index: 10000; font-family: 'Inter', sans-serif; overflow: hidden; border: 1px solid rgba(187,0,255,0.1); }
        #shinju-chat-bubble { position: fixed; bottom: 20px; right: 20px; width: 65px; height: 60px; background: #BB00FF; border-radius: 50%; box-shadow: 0 8px 20px rgba(187,0,255,0.4); cursor: pointer; display: flex; justify-content: center; align-items: center; color: white; font-size: 26px; z-index: 10001; transition: 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275); }
        #shinju-chat-bubble:hover { transform: scale(1.1) rotate(5deg); }
        #shinju-chat-header { background: linear-gradient(135deg, #BB00FF 0%, #7000FF 100%); color: white; padding: 18px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
        #shinju-recording-status { display:none; background:#ff4d4d; color:white; text-align:center; font-size:10px; font-weight:900; padding:8px; z-index:10001; animation: shinju-flash 0.8s infinite alternate; letter-spacing:1px; }
        @keyframes shinju-flash { from { opacity: 1; } to { opacity: 0.6; } }
        #shinju-chat-messages { flex: 1; padding: 15px; overflow-y: auto; background: #fcfcfc; display: flex; flex-direction: column; gap: 12px; }
        .shinju-message { padding: 10px 14px; border-radius: 12px; max-width: 85%; font-size: 14px; line-height: 1.5; word-wrap: break-word; position: relative; }
        .shinju-user { background: #BB00FF; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
        .shinju-bot { background: #fff; color: #333; align-self: flex-start; border-bottom-left-radius: 2px; border: 1px solid #eee; box-shadow: 0 2px 5px rgba(0,0,0,0.02); }
        .shinju-agent-tag { font-size: 8px; font-weight: 900; color: #BB00FF; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 1.2px; display: flex; align-items: center; gap: 4px; }
        .shinju-agent-tag::before { content: ""; width: 4px; height: 4px; background: #BB00FF; border-radius: 50%; display: inline-block; box-shadow: 0 0 5px #BB00FF; }
        #shinju-chat-input-area { padding: 12px; border-top: 1px solid #eee; display: flex; align-items: center; background: white; gap: 10px; }
        #shinju-chat-input { flex: 1; border: none; padding: 8px; outline: none; font-size: 15px; color: #333; }
        #shinju-mic-btn { background: #f5f5f5; border: none; cursor: pointer; font-size: 18px; width: 38px; height: 38px; display: flex; align-items: center; justify-content: center; color: #666; transition: 0.3s; border-radius: 50%; }
        #shinju-mic-btn.recording { background: #ff4d4d !important; color: white !important; box-shadow: 0 0 15px rgba(255,77,77,0.6); animation: shinju-pulse 1s infinite alternate !important; }
        @keyframes shinju-pulse { from { transform: scale(1); } to { transform: scale(1.15); } }
        .shinju-highlight { color: #BB00FF; font-weight: 800; border-bottom: 1px dashed rgba(187,0,255,0.3); }

        @media (max-width: 768px) {
            #shinju-chat-bubble { bottom: 80px !important; right: 15px !important; width: 55px !important; height: 55px !important; }
            #shinju-chat-container { width: 100% !important; height: calc(100% - 60px) !important; bottom: 60px !important; right: 0 !important; border-radius: 0 !important; }
        }
    `;
    document.head.appendChild(styleTag);

    const translations = {
        "en": { "header": "Shinju AI Elite Support", "input": "Ask me anything...", "send": "Send", "greeting": "Welcome to the Shinju Experience. How may I assist you today?" },
        "fr": { "header": "Support Elite Shinju AI", "input": "Posez votre question...", "send": "Envoyer", "greeting": "Bienvenue chez Shinju AI. Comment puis-je vous assister ?" },
        "es": { "header": "Soporte Elite Shinju AI", "input": "Pregúntame lo que sea...", "send": "Enviar", "greeting": "Bienvenido a Shinju AI. ¿En qué puedo ayudarle hoy?" }
    };

    let currentLang = localStorage.getItem("shinju_chat_lang") || "en";

    const container = document.createElement("div");
    container.id = "shinju-chat-container";
    container.innerHTML = `
        <div id="shinju-chat-header">
            <span id="shinju-chat-title">${translations[currentLang].header}</span>
            <div style="display:flex; align-items:center; gap:10px;">
                <select id="shinju-chat-lang-select" style="background:transparent; color:white; border:1px solid rgba(255,255,255,0.3); border-radius:4px; font-size:11px; cursor:pointer; outline:none;">
                    <option value="en" ${currentLang === 'en' ? 'selected' : ''}>EN</option>
                    <option value="fr" ${currentLang === 'fr' ? 'selected' : ''}>FR</option>
                    <option value="es" ${currentLang === 'es' ? 'selected' : ''}>ES</option>
                </select>
                <span id="shinju-chat-close" style="cursor:pointer; font-size:18px; opacity:0.8;">×</span>
            </div>
        </div>
        <div id="shinju-recording-status">● VOICE ACTIVE - LISTENING...</div>
        <div id="shinju-chat-messages"></div>
        <div id="shinju-chat-input-area">
            <button id="shinju-mic-btn" title="Tap to Speak">🎤</button>
            <input type="text" id="shinju-chat-input" placeholder="${translations[currentLang].input}">
            <button id="shinju-chat-send" style="background:#BB00FF; color:white; border:none; padding:10px 18px; border-radius:12px; cursor:pointer; font-weight:800; font-size:13px;">${translations[currentLang].send}</button>
        </div>
    `;
    document.body.appendChild(container);

    const bubble = document.createElement("div");
    bubble.id = "shinju-chat-bubble";
    bubble.innerHTML = "💬";
    document.body.appendChild(bubble);

    const msgContainer = document.getElementById("shinju-chat-messages");
    const input = document.getElementById("shinju-chat-input");
    const sendBtn = document.getElementById("shinju-chat-send");
    const micBtn = document.getElementById("shinju-mic-btn");
    const statusBanner = document.getElementById("shinju-recording-status");

    function appendMessage(text, sender, identity = null) {
        const div = document.createElement("div");
        div.className = `shinju-message shinju-${sender}`;
        if (sender === "bot") {
            const tag = identity ? `<div class="shinju-agent-tag">${identity}</div>` : "";
            div.innerHTML = tag + text.replace(/\*\*(.*?)\*\*/g, '<span class="shinju-highlight">$1</span>');
        } else { div.innerText = text; }
        msgContainer.appendChild(div);
        msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    async function sendMessage(overrideText = null) {
        const text = overrideText || input.value.trim();
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
            if (data.reply) { appendMessage(data.reply, "bot", data.agent_identity); }
        } catch (e) { appendMessage("The connection seems weak. Retrying...", "bot"); }
    }

    // --- UNIVERSAL VOICE ENGINE V2 ---
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;

    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
            mediaRecorder = new MediaRecorder(stream, { mimeType });
            audioChunks = [];
            
            mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: mimeType });
                const formData = new FormData();
                formData.append('file', audioBlob, 'voice.wav');
                
                statusBanner.innerText = "● ANALYZING VOICE...";
                try {
                    const res = await fetch(TRANSCRIBE_URL, {
                        method: 'POST',
                        headers: { "X-API-Key": API_KEY },
                        body: formData
                    });
                    const data = await res.json();
                    if (data.text && data.text.length > 1) { sendMessage(data.text); }
                    else { throw new Error("Empty audio"); }
                } catch (e) { alert("Could not process audio. Please try speaking closer to the mic."); }
                
                statusBanner.style.display = "none";
                statusBanner.innerText = "● VOICE ACTIVE - LISTENING...";
                micBtn.classList.remove("recording");
            };

            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add("recording");
            statusBanner.style.display = "block";
            input.placeholder = "Listening to your request...";
        } catch (err) {
            alert("Please enable microphone permissions in your browser to use voice features.");
        }
    }

    micBtn.onclick = () => { if (isRecording) { mediaRecorder.stop(); isRecording = false; } else { startRecording(); } };
    sendBtn.onclick = () => sendMessage();
    input.onkeypress = (e) => { if (e.key === "Enter") sendMessage(); };
    bubble.onclick = () => { container.style.display = "flex"; bubble.style.display = "none"; };
    document.getElementById("shinju-chat-close").onclick = () => { container.style.display = "none"; bubble.style.display = "flex"; };
    
    document.getElementById("shinju-chat-lang-select").onchange = (e) => {
        currentLang = e.target.value;
        localStorage.setItem("shinju_chat_lang", currentLang);
        document.getElementById("shinju-chat-title").innerText = translations[currentLang].header;
        input.placeholder = translations[currentLang].input;
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
