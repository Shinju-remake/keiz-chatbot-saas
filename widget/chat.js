(function() {
    // 1. Initial Config
    const API_KEY = "dev-api-key-123"; 
    const BASE_ORIGIN = window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1") 
                        ? window.location.origin 
                        : "https://keiz-chatbot-saas-1.onrender.com";
    const BACKEND_URL = `${BASE_ORIGIN}/chat`;

    let sessionId = localStorage.getItem("shinju_chat_session");
    if (!sessionId) {
        sessionId = "sess_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("shinju_chat_session", sessionId);
    }

    // 2. Inject CSS with hard cache-busting
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `/widget/chat.css?v=${new Date().getTime()}`; 
    document.head.appendChild(link);

    async function applyBranding() {
        try {
            const res = await fetch(`${BASE_ORIGIN}/widget/config`, {
                headers: { "X-API-Key": API_KEY }
            });
            const config = await res.json();
            if (config.primary_color) {
                document.documentElement.style.setProperty('--primary', config.primary_color);
                const bubble = document.getElementById("shinju-chat-bubble");
                const header = document.getElementById("shinju-chat-header");
                const sendBtn = document.getElementById("shinju-chat-send");
                if (bubble) bubble.style.background = config.primary_color;
                if (header) header.style.background = config.primary_color;
                if (sendBtn) sendBtn.style.background = config.primary_color;
            }
            if (config.logo_url) {
                const title = document.getElementById("shinju-chat-title");
                title.innerHTML = `<img src="${config.logo_url}" style="height:24px; margin-right:10px; vertical-align:middle;"> ${config.name}`;
            }
        } catch (e) { console.error("Branding fetch failed", e); }
    }

    // 3. Build UI Elements
    const bubble = document.createElement("div");
    bubble.id = "shinju-chat-bubble";
    bubble.innerHTML = "💬";
    document.body.appendChild(bubble);

    const translations = {
        "en": { "header": "Shinju AI Support", "input": "Type a message...", "send": "Send", "greeting": "Hello! I am Shinju AI. How can I help you today?" },
        "fr": { "header": "Support Shinju AI", "input": "Écrivez un message...", "send": "Envoyer", "greeting": "Bonjour! Je suis Shinju AI. Comment puis-je vous aider aujourd'hui ?" },
        "es": { "header": "Soporte Shinju AI", "input": "Escribe un mensaje...", "send": "Enviar", "greeting": "¡Hola! Soy Shinju AI. ¿Cómo puedo ayudarte hoy?" }
    };

    let currentLang = localStorage.getItem("shinju_chat_lang") || "en";

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
        <div id="shinju-recording-status" style="display:none; background:#ff4d4d; color:white; text-align:center; font-size:10px; font-weight:bold; padding:5px; letter-spacing:1px; animation: flash 1s infinite alternate;">● VOICE ACTIVE - LISTENING...</div>
        <div id="shinju-chat-messages" style="display:flex; flex-direction:column;"></div>
        <div id="shinju-chat-input-area">
            <input type="text" id="shinju-chat-input" placeholder="${translations[currentLang].input}">
            <button id="shinju-mic-btn" title="Tap to Speak">⚲</button>
            <button id="shinju-chat-send">${translations[currentLang].send}</button>
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

    // --- PHASE 5: VOICE CONCIERGE ---
    let isRecording = false;
    let recognition;
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        
        recognition.onstart = () => {
            isRecording = true;
            micBtn.classList.add("recording");
            statusBanner.style.setProperty("display", "block", "important");
            input.placeholder = "Listening...";
        };
        
        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            input.value = transcript;
            sendMessage();
        };
        
        recognition.onend = () => {
            isRecording = false;
            micBtn.classList.remove("recording");
            statusBanner.style.setProperty("display", "none", "important");
            input.placeholder = translations[currentLang].input;
        };
        
        recognition.onerror = (e) => {
            console.error("Speech Error", e);
            recognition.stop();
        };

        micBtn.onclick = () => {
            if (isRecording) {
                recognition.stop();
            } else {
                recognition.lang = currentLang;
                recognition.start();
            }
        };
    } else {
        micBtn.onclick = () => { alert("Voice features are only available in modern browsers (Chrome/Safari) over HTTPS."); };
    }

    function speakText(text) {
        if ('speechSynthesis' in window) {
            const cleanText = text.replace(/\[DATA\].*?\[\/DATA\]/gs, "").replace(/\*\*/g, "").replace(/\[RESERVATION_SUCCESS\]/g, "Your reservation is confirmed.");
            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = currentLang;
            window.speechSynthesis.speak(utterance);
        }
    }

    // 4. Interaction Logic
    langSelect.onchange = (e) => {
        currentLang = e.target.value;
        localStorage.setItem("shinju_chat_lang", currentLang);
        headerTitle.innerText = translations[currentLang].header;
        input.placeholder = translations[currentLang].input;
        sendBtn.innerText = translations[currentLang].send;
    };

    bubble.onclick = () => { container.style.display = "flex"; bubble.style.display = "none"; };
    document.getElementById("shinju-chat-close").onclick = () => { container.style.display = "none"; bubble.style.display = "flex"; };

    function appendMessage(text, sender, identity = null) {
        const div = document.createElement("div");
        div.className = `shinju-message shinju-${sender}`;
        
        if (sender === "bot") {
            const tag = identity ? `<div style="font-size:9px; font-weight:900; color:var(--primary); margin-bottom:5px; text-transform:uppercase; letter-spacing:1px;">● ${identity}</div>` : "";
            const highlightedText = text.replace(/\*\*(.*?)\*\*/g, '<span class="shinju-highlight">$1</span>');
            div.innerHTML = tag + highlightedText;
        } else {
            div.innerText = text;
        }
        
        msgContainer.appendChild(div);
        msgContainer.scrollTop = msgContainer.scrollHeight;
    }

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        appendMessage(text, "user");
        input.value = "";
        try {
            const response = await fetch(BACKEND_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
                body: JSON.stringify({ message: text, session_id: sessionId, language: currentLang })
            });
            const data = await response.json();
            if (data.reply) {
                appendMessage(data.reply, "bot", data.agent_identity);
                speakText(data.reply);
            }
        } catch (error) {
            appendMessage("Sorry, I'm having trouble connecting to the server.", "bot");
        }
    }

    sendBtn.onclick = sendMessage;
    input.onkeypress = (e) => { if (e.key === "Enter") sendMessage(); };
    setTimeout(() => { appendMessage(translations[currentLang].greeting, "bot"); }, 500);
    applyBranding();
})();
