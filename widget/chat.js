(function() {
    const API_KEY = "dev-api-key-123"; 
    const BASE_ORIGIN = window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1") 
                        ? window.location.origin 
                        : "https://keiz-chatbot-saas-1.onrender.com";
    const BACKEND_URL = `${BASE_ORIGIN}/chat`;

    let sessionId = localStorage.getItem("shinju_chat_session") || "sess_" + Math.random().toString(36).substr(2, 9);
    localStorage.setItem("shinju_chat_session", sessionId);

    // --- ULTIMATE CACHE BUSTER: EMBEDDED STYLES ---
    const styleTag = document.createElement("style");
    styleTag.innerHTML = `
        #shinju-recording-status { display:none; background:#ff4d4d; color:white; text-align:center; font-size:10px; font-weight:bold; padding:8px; letter-spacing:1px; z-index:10001; }
        @keyframes shinju-flash { from { opacity: 1; } to { opacity: 0.5; } }
        .shinju-voice-active { animation: shinju-flash 0.8s infinite alternate; }
        
        #shinju-mic-btn.recording { 
            background: #ff4d4d !important; 
            color: white !important; 
            border-radius: 50%;
            box-shadow: 0 0 20px #ff4d4d;
            animation: shinju-pulse 1s infinite alternate !important;
        }
        @keyframes shinju-pulse { 
            from { transform: scale(1); box-shadow: 0 0 10px #ff4d4d; } 
            to { transform: scale(1.3); box-shadow: 0 0 30px #ff4d4d; } 
        }
        .shinju-highlight { color: var(--primary, #BB00FF); font-weight: 700; }
    `;
    document.head.appendChild(styleTag);

    async function applyBranding() {
        try {
            const res = await fetch(`${BASE_ORIGIN}/widget/config`, { headers: { "X-API-Key": API_KEY } });
            const config = await res.json();
            if (config.primary_color) {
                document.documentElement.style.setProperty('--primary', config.primary_color);
                const b = document.getElementById("shinju-chat-bubble");
                const h = document.getElementById("shinju-chat-header");
                const s = document.getElementById("shinju-chat-send");
                if (b) b.style.background = config.primary_color;
                if (h) h.style.background = config.primary_color;
                if (s) s.style.background = config.primary_color;
            }
        } catch (e) { console.error("Branding failed", e); }
    }

    const translations = {
        "en": { "header": "Shinju AI Support", "input": "Type a message...", "send": "Send", "greeting": "Hello! I am Shinju AI. How can I help you today?" },
        "fr": { "header": "Support Shinju AI", "input": "Écrivez un message...", "send": "Envoyer", "greeting": "Bonjour! Je suis Shinju AI. Comment puis-je vous aider aujourd'hui ?" },
        "es": { "header": "Soporte Shinju AI", "input": "Escribe un mensaje...", "send": "Enviar", "greeting": "¡Hola! Soy Shinju AI. ¿Cómo puedo ayudarte hoy?" }
    };

    let currentLang = localStorage.getItem("shinju_chat_lang") || "en";

    // 3. Build UI Elements
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
                <span style="cursor:pointer;" id="shinju-chat-close">✖</span>
            </div>
        </div>
        <div id="shinju-recording-status">● VOICE ACTIVE - LISTENING...</div>
        <div id="shinju-chat-messages" style="display:flex; flex-direction:column; flex:1; overflow-y:auto; padding:10px; background:#f9f9f9;"></div>
        <div id="shinju-chat-input-area" style="display:flex; align-items:center; gap:5px; padding:10px; border-top:1px solid #eee; background:white;">
            <input type="text" id="shinju-chat-input" placeholder="${translations[currentLang].input}" style="flex:1; border:none; outline:none; padding:8px; font-size:16px;">
            <button id="shinju-mic-btn" style="background:transparent; border:none; cursor:pointer; font-size:20px; padding:5px 10px; color:#666;" title="Tap to Speak">⚲</button>
            <button id="shinju-chat-send" style="background:var(--primary, #BB00FF); color:white; border:none; padding:8px 15px; border-radius:15px; cursor:pointer; font-weight:bold;">${translations[currentLang].send}</button>
        </div>
    `;
    document.body.appendChild(container);

    const msgContainer = document.getElementById("shinju-chat-messages");
    const input = document.getElementById("shinju-chat-input");
    const langSelect = document.getElementById("shinju-chat-lang-select");
    const headerTitle = document.getElementById("shinju-chat-title");
    const sendBtn = document.getElementById("shinju-chat-send");
    const micBtn = document.getElementById("shinju-mic-btn");
    const statusBanner = document.getElementById("shinju-recording-status");

    // --- SPEECH LOGIC ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        
        recognition.onstart = () => {
            micBtn.classList.add("recording");
            statusBanner.style.setProperty("display", "block", "important");
            statusBanner.classList.add("shinju-voice-active");
            input.placeholder = "Listening...";
        };
        
        recognition.onresult = (e) => {
            input.value = e.results[0][0].transcript;
            sendMessage();
        };
        
        recognition.onend = () => {
            micBtn.classList.remove("recording");
            statusBanner.style.setProperty("display", "none", "important");
            input.placeholder = translations[currentLang].input;
        };
        
        recognition.onerror = () => { recognition.stop(); };

        micBtn.onclick = () => { try { recognition.start(); } catch(e) { recognition.stop(); } };
    } else {
        micBtn.onclick = () => { 
            alert("Voice features are only available in modern browsers (Chrome/Safari) over HTTPS. Firefox users: Enable 'media.webspeech.recognition.enable' in about:config."); 
        };
    }

    function speakText(text) {
        if ('speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(text.replace(/\[DATA\].*?\[\/DATA\]/gs, "").replace(/\*\*/g, ""));
            utterance.lang = currentLang;
            window.speechSynthesis.speak(utterance);
        }
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
                speakText(data.reply);
            }
        } catch (e) { appendMessage("Connection lost.", "bot"); }
    }

    function appendMessage(text, sender, identity = null) {
        const div = document.createElement("div");
        div.className = `shinju-message shinju-${sender}`;
        if (sender === "bot") {
            const tag = identity ? `<div style="font-size:9px; font-weight:900; color:var(--primary); margin-bottom:5px; text-transform:uppercase; letter-spacing:1px;">● ${identity}</div>` : "";
            div.innerHTML = tag + text.replace(/\*\*(.*?)\*\*/g, '<span class="shinju-highlight">$1</span>');
        } else { div.innerText = text; }
        msgContainer.appendChild(div);
        msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    langSelect.onchange = (e) => {
        currentLang = e.target.value;
        localStorage.setItem("shinju_chat_lang", currentLang);
        headerTitle.innerText = translations[currentLang].header;
        input.placeholder = translations[currentLang].input;
        sendBtn.innerText = translations[currentLang].send;
    };

    sendBtn.onclick = sendMessage;
    input.onkeypress = (e) => { if (e.key === "Enter") sendMessage(); };
    bubble.onclick = () => { container.style.display = "flex"; bubble.style.display = "none"; };
    document.getElementById("shinju-chat-close").onclick = () => { container.style.display = "none"; bubble.style.display = "flex"; };
    
    setTimeout(() => appendMessage(translations[currentLang].greeting, "bot"), 500);
    applyBranding();
})();
