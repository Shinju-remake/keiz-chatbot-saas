(function() {
    // --- DUPLICATE PREVENTION & IFRAME GUARD ---
    if (window.self !== window.top && (window.location.pathname.includes('/demo') || window.location.pathname.includes('/dashboard'))) {
        return; 
    }
    if (window.SHINJU_LOADED) return;

    const ShinjuAI = {
        config: {
            apiKey: "dev-api-key-123",
            primaryColor: "#BB00FF",
            logoUrl: null,
            subdomain: null
        },
        init: function(userConfig) {
            this.config = { ...this.config, ...userConfig };
            this.boot();
        },
        boot: function() {
            window.SHINJU_LOADED = true;
            this.setupUI();
            this.applyBranding();
            setTimeout(() => this.appendMessage(this.translations[this.currentLang].greeting, "bot"), 500);
        }
    };

    const BASE_ORIGIN = (window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1"))
                        ? window.location.origin 
                        : "https://keiz-chatbot-saas-1.onrender.com";
    const BACKEND_URL = `${BASE_ORIGIN}/chat`;
    const TRANSCRIBE_URL = `${BASE_ORIGIN}/transcribe`;

    ShinjuAI.sessionId = localStorage.getItem("shinju_chat_session") || "sess_" + Math.random().toString(36).substr(2, 9);
    localStorage.setItem("shinju_chat_session", ShinjuAI.sessionId);

    ShinjuAI.translations = {
        "en": { "header": "Shinju AI Support", "input": "Type a message...", "send": "Send", "greeting": "Hello! I am Shinju AI. How can I help you today?" },
        "fr": { "header": "Support Shinju AI", "input": "Écrivez un message...", "send": "Envoyer", "greeting": "Bonjour! Je suis Shinju AI. Comment puis-je vous aider aujourd'hui ?" },
        "es": { "header": "Soporte Shinju AI", "input": "Escribe un message...", "send": "Enviar", "greeting": "¡Hola! Soy Shinju AI. ¿Cómo puedo ayudarte hoy?" }
    };

    ShinjuAI.currentLang = localStorage.getItem("shinju_chat_lang") || "en";

    ShinjuAI.setupUI = function() {
        const styleTag = document.createElement("style");
        styleTag.innerHTML = `
            #shinju-chat-container { position: fixed; bottom: 20px; right: 20px; width: 350px; height: 500px; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); display: none; flex-direction: column; z-index: 10000; font-family: sans-serif; overflow: hidden; }
            #shinju-chat-bubble { position: fixed; bottom: 20px; right: 20px; width: 60px; height: 60px; background: ${this.config.primaryColor}; border-radius: 50%; box-shadow: 0 4px 12px rgba(0,0,0,0.3); cursor: pointer; display: flex; justify-content: center; align-items: center; color: white; font-size: 24px; z-index: 10001; }
            #shinju-chat-header { background: ${this.config.primaryColor}; color: white; padding: 15px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
            #shinju-recording-status { display:none; background:#ff4d4d; color:white; text-align:center; font-size:10px; font-weight:bold; padding:8px; z-index:10001; animation: shinju-flash 0.8s infinite alternate; }
            @keyframes shinju-flash { from { opacity: 1; } to { opacity: 0.5; } }
            #shinju-chat-messages { flex: 1; padding: 10px; overflow-y: auto; background: #f9f9f9; display: flex; flex-direction: column; }
            .shinju-message { margin-bottom: 10px; padding: 8px 12px; border-radius: 8px; max-width: 85%; font-size: 14px; line-height: 1.4; word-wrap: break-word; }
            .shinju-user { background: ${this.config.primaryColor}; color: white; align-self: flex-end; }
            .shinju-bot { background: #e0e0e0; color: #333; align-self: flex-start; }
            #shinju-chat-input-area { padding: 10px; border-top: 1px solid #ddd; display: flex; align-items: center; background: white; }
            #shinju-chat-input { flex: 1; border: none; padding: 10px; outline: none; font-size: 16px; color: #333 !important; background: white !important; }
            #shinju-mic-btn { background: transparent; border: none; cursor: pointer; font-size: 20px; padding: 5px 10px; color: #888; transition: 0.3s; border-radius: 50%; }
            #shinju-mic-btn.recording { background: #ff4d4d !important; color: white !important; box-shadow: 0 0 20px #ff4d4d; animation: shinju-pulse 1s infinite alternate !important; }
            @keyframes shinju-pulse { from { transform: scale(1); } to { transform: scale(1.3); } }
            .shinju-highlight { color: ${this.config.primaryColor}; font-weight: 700; }
            .shinju-agent-tag { font-size:9px; font-weight:900; color:${this.config.primaryColor}; margin-bottom:5px; text-transform:uppercase; }

            @media (max-width: 768px) {
                #shinju-chat-bubble { bottom: 85px !important; right: 20px !important; width: 55px !important; height: 55px !important; }
                #shinju-chat-container { width: 100% !important; height: calc(100% - 70px) !important; bottom: 70px !important; right: 0 !important; border-radius: 0 !important; }
            }
        `;
        document.head.appendChild(styleTag);

        const bubble = document.createElement("div");
        bubble.id = "shinju-chat-bubble";
        bubble.innerHTML = "💬";
        document.body.appendChild(bubble);

        const container = document.createElement("div");
        container.id = "shinju-chat-container";
        container.innerHTML = `
            <div id="shinju-chat-header">
                <span id="shinju-chat-title">${this.translations[this.currentLang].header}</span>
                <div style="display:flex; align-items:center; gap:10px;">
                    <select id="shinju-chat-lang-select" style="background:transparent; color:white; border:1px solid white; border-radius:4px; font-size:12px; cursor:pointer;">
                        <option value="en" ${this.currentLang === 'en' ? 'selected' : ''}>EN</option>
                        <option value="fr" ${this.currentLang === 'fr' ? 'selected' : ''}>FR</option>
                        <option value="es" ${this.currentLang === 'es' ? 'selected' : ''}>ES</option>
                    </select>
                    <span id="shinju-chat-close" style="cursor:pointer;">✖</span>
                </div>
            </div>
            <div id="shinju-recording-status">● VOICE ACTIVE - LISTENING...</div>
            <div id="shinju-chat-messages"></div>
            <div id="shinju-chat-input-area">
                <input type="text" id="shinju-chat-input" placeholder="${this.translations[this.currentLang].input}">
                <button id="shinju-mic-btn" title="Tap to Speak">🎤</button>
                <button id="shinju-chat-send" style="background:${this.config.primaryColor}; color:white; border:none; padding:8px 15px; border-radius:15px; cursor:pointer; font-weight:bold;">${this.translations[this.currentLang].send}</button>
            </div>
        `;
        document.body.appendChild(container);

        this.msgContainer = document.getElementById("shinju-chat-messages");
        this.input = document.getElementById("shinju-chat-input");
        this.sendBtn = document.getElementById("shinju-chat-send");
        this.micBtn = document.getElementById("shinju-mic-btn");
        this.statusBanner = document.getElementById("shinju-recording-status");

        this.micBtn.onclick = () => { if (this.isRecording) { this.mediaRecorder.stop(); this.isRecording = false; } else { this.startRecording(); } };
        this.sendBtn.onclick = () => this.sendMessage();
        this.input.onkeypress = (e) => { if (e.key === "Enter") this.sendMessage(); };
        bubble.onclick = () => { container.style.display = "flex"; bubble.style.display = "none"; };
        document.getElementById("shinju-chat-close").onclick = () => { container.style.display = "none"; bubble.style.display = "flex"; };
        
        document.getElementById("shinju-chat-lang-select").onchange = (e) => {
            this.currentLang = e.target.value;
            localStorage.setItem("shinju_chat_lang", this.currentLang);
            document.getElementById("shinju-chat-title").innerText = this.translations[this.currentLang].header;
            this.input.placeholder = this.translations[this.currentLang].input;
            this.sendBtn.innerText = this.translations[this.currentLang].send;
        };
    };

    ShinjuAI.appendMessage = function(text, sender, identity = null) {
        const div = document.createElement("div");
        div.className = `shinju-message shinju-${sender}`;
        
        if (sender === "bot") {
            const tag = identity ? `<div class="shinju-agent-tag">● ${identity}</div>` : "";
            if (text.includes("[MENU_DATA]")) {
                const menuContent = text.replace("[MENU_DATA]", "").split("---")[1] || text;
                const items = menuContent.split("\n").filter(line => line.includes(":") || line.includes("€"));
                let html = `${tag}<div style="margin-bottom:10px;">Here is our <b>Premium Selection</b>:</div><div style="display:grid; gap:10px; margin-top:10px;">`;
                items.forEach(item => {
                    const parts = item.replace("- ", "").split(":");
                    if (parts.length >= 2) {
                        html += `<div style="background:white; padding:12px; border-radius:10px; border-left:4px solid ${this.config.primaryColor}; box-shadow:0 2px 5px rgba(0,0,0,0.05); color:#333;">
                                    <div style="font-weight:900; color:${this.config.primaryColor}; display:flex; justify-content:space-between;"><span>${parts[0].trim()}</span></div>
                                    <div style="font-size:11px; color:#666; margin-top:4px;">${parts[1].trim()}</div>
                                </div>`;
                    }
                });
                html += `</div>`;
                div.innerHTML = html;
            } else {
                div.innerHTML = tag + text.replace(/\*\*(.*?)\*\*/g, `<span style="color:${this.config.primaryColor}; font-weight:700;">$1</span>`);
            }
        } else { div.innerText = text; }
        this.msgContainer.appendChild(div);
        this.msgContainer.scrollTop = this.msgContainer.scrollHeight;
    };

    ShinjuAI.sendMessage = async function(overrideText = null) {
        const text = overrideText || this.input.value.trim();
        if (!text) return;
        this.appendMessage(text, "user");
        this.input.value = "";
        try {
            const res = await fetch(BACKEND_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-API-Key": this.config.apiKey },
                body: JSON.stringify({ message: text, session_id: this.sessionId, language: this.currentLang })
            });
            const data = await res.json();
            if (data.reply) { this.appendMessage(data.reply, "bot", data.agent_identity); }
        } catch (e) { this.appendMessage("Connection lost.", "bot"); }
    };

    ShinjuAI.startRecording = async function() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
            this.mediaRecorder = new MediaRecorder(stream, { mimeType });
            let chunks = [];
            this.mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
            this.mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(chunks, { type: mimeType });
                const formData = new FormData();
                formData.append('file', audioBlob, 'voice.wav');
                this.statusBanner.innerText = "● ANALYZING...";
                try {
                    const res = await fetch(TRANSCRIBE_URL, { method: 'POST', headers: { "X-API-Key": this.config.apiKey }, body: formData });
                    const d = await res.json();
                    if (d.text) this.sendMessage(d.text);
                } catch (e) {}
                this.statusBanner.style.display = "none";
                this.statusBanner.innerText = "● VOICE ACTIVE - LISTENING...";
                this.micBtn.classList.remove("recording");
            };
            this.mediaRecorder.start();
            this.isRecording = true;
            this.micBtn.classList.add("recording");
            this.statusBanner.style.display = "block";
        } catch (err) { alert("Mic required."); }
    };

    ShinjuAI.applyBranding = async function() {
        try {
            const res = await fetch(`${BASE_ORIGIN}/widget/config`, { headers: { "X-API-Key": this.config.apiKey } });
            const config = await res.json();
            if (config.primary_color) {
                this.config.primaryColor = config.primary_color;
                ["shinju-chat-bubble", "shinju-chat-header", "shinju-chat-send"].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.style.background = config.primary_color;
                });
            }
        } catch (e) {}
    };

    window.ShinjuAI = ShinjuAI;

    // Auto-boot if included via standard script tag
    setTimeout(() => {
        if (!window.SHINJU_LOADED) ShinjuAI.boot();
    }, 500);

})();
