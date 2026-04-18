(function() {
    // 1. Initial Config
    const API_KEY = "dev-api-key-123"; 
    // Use window.location.origin if served from same domain, otherwise fallback to Render URL
    const BASE_ORIGIN = window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1") 
                        ? window.location.origin 
                        : "https://keiz-chatbot-saas-1.onrender.com";
    const BACKEND_URL = `${BASE_ORIGIN}/chat`;

    // Session Memory Tracking
    let sessionId = localStorage.getItem("shinju_chat_session");
    if (!sessionId) {
        sessionId = "sess_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("shinju_chat_session", sessionId);
    }

    // 2. Inject CSS
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/widget/chat.css"; 
    document.head.appendChild(link);

    // --- NEW: Fetch Dynamic Config ---
    async function applyBranding() {
        try {
            const res = await fetch(`${BASE_ORIGIN}/widget/config`, {
                headers: { "X-API-Key": API_KEY }
            });
            const config = await res.json();
            if (config.primary_color) {
                document.documentElement.style.setProperty('--primary', config.primary_color);
                // Update elements already in DOM
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
        "en": {
            "header": "Shinju AI Support",
            "input": "Type a message...",
            "send": "Send",
            "greeting": "Hello! I am Shinju AI. How can I help you today?"
        },
        "fr": {
            "header": "Support Shinju AI",
            "input": "Écrivez un message...",
            "send": "Envoyer",
            "greeting": "Bonjour! Je suis Shinju AI. Comment puis-je vous aider aujourd'hui ?"
        },
        "es": {
            "header": "Soporte Shinju AI",
            "input": "Escribe un mensaje...",
            "send": "Enviar",
            "greeting": "¡Hola! Soy Shinju AI. ¿Cómo puedo ayudarte hoy?"
        }
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
        <div id="shinju-chat-messages" style="display:flex; flex-direction:column;"></div>
        <div id="shinju-chat-input-area" style="display:flex; align-items:center; gap:5px; padding:10px; border-top:1px solid #eee; background:white;">
            <input type="text" id="shinju-chat-input" placeholder="${translations[currentLang].input}" style="flex:1; border:none; outline:none; padding:8px;">
            <button id="shinju-mic-btn" style="background:transparent; border:none; cursor:pointer; font-size:18px; padding:5px; color:#666;" title="Tap to Speak">🎤</button>
            <button id="shinju-chat-send" style="background:var(--primary); color:white; border:none; padding:8px 15px; border-radius:15px; cursor:pointer; font-weight:bold;">${translations[currentLang].send}</button>
        </div>
    `;
    document.body.appendChild(container);

    const msgContainer = document.getElementById("shinju-chat-messages");
    const input = document.getElementById("shinju-chat-input");
    const langSelect = document.getElementById("shinju-chat-lang-select");
    const headerTitle = document.getElementById("shinju-chat-title");
    const sendBtn = document.getElementById("shinju-chat-send");
    const micBtn = document.getElementById("shinju-mic-btn");

    // --- PHASE 5: VOICE CONCIERGE MVP ---
    let isRecording = false;
    let recognition;
    
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        
        recognition.onstart = () => {
            isRecording = true;
            micBtn.classList.add("recording");
            input.placeholder = "Listening...";
        };
        
        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            input.value = transcript;
            sendMessage(); // Auto-send when voice is captured
        };
        
        recognition.onend = () => {
            isRecording = false;
            micBtn.classList.remove("recording");
            input.placeholder = translations[currentLang].input;
        };
        
        micBtn.onclick = () => {
            if (isRecording) {
                recognition.stop();
            } else {
                recognition.lang = currentLang; // Use currently selected language
                recognition.start();
            }
        };
    } else {
        console.warn("Web Speech API not supported in this browser.");
        // We keep the button but it will show an alert if clicked and not supported
        micBtn.onclick = () => { alert("Voice features are only available in modern browsers (Chrome/Safari) over HTTPS."); };
    }

    function speakText(text) {
        if ('speechSynthesis' in window) {
            // Strip markdown, [DATA] tags, and extra symbols for a natural voice
            const cleanText = text.replace(/\[DATA\].*?\[\/DATA\]/gs, "")
                                  .replace(/\*\*/g, "")
                                  .replace(/\[RESERVATION_SUCCESS\]/g, "Your reservation is successfully confirmed.");
            
            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = currentLang;
            window.speechSynthesis.speak(utterance);
        }
    }
    // ------------------------------------

    // 4. Interaction Logic
    langSelect.onchange = (e) => {
        currentLang = e.target.value;
        localStorage.setItem("shinju_chat_lang", currentLang);
        
        // Update UI Text
        headerTitle.innerText = translations[currentLang].header;
        input.placeholder = translations[currentLang].input;
        sendBtn.innerText = translations[currentLang].send;
    };

    bubble.onclick = () => {
        container.style.display = "flex";
        bubble.style.display = "none";
    };

    document.getElementById("shinju-chat-close").onclick = () => {
        container.style.display = "none";
        bubble.style.display = "flex";
    };

    function appendMessage(text, sender) {
        const div = document.createElement("div");
        div.className = `shinju-message shinju-${sender}`;
        
        // Color-highlighting for AI questions (Pro UI feature)
        if (sender === "bot") {
            // Replace **Question?** with <span class="shinju-highlight">Question?</span>
            const highlightedText = text.replace(/\*\*(.*?)\*\*/g, '<span class="shinju-highlight">$1</span>');
            div.innerHTML = highlightedText;
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
                headers: {
                    "Content-Type": "application/json",
                    "X-API-Key": API_KEY
                },
                body: JSON.stringify({ 
                    message: text, 
                    session_id: sessionId,
                    language: currentLang
                })
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                appendMessage(`Error (${response.status}): ` + (errData.detail || "Server logic error"), "bot");
                return;
            }

            const data = await response.json();
            if (data.reply) {
                appendMessage(data.reply, "bot");
                speakText(data.reply); // --- PHASE 5: Trigger Voice Concierge ---
            } else {
                appendMessage("Received an empty response.", "bot");
            }
        } catch (error) {
            console.error("Chat Error:", error);
            appendMessage("Sorry, I'm having trouble connecting to the server.", "bot");
        }
    }

    document.getElementById("shinju-chat-send").onclick = sendMessage;
    input.onkeypress = (e) => {
        if (e.key === "Enter") sendMessage();
    };

    // Initial greeting
    setTimeout(() => {
        appendMessage(translations[currentLang].greeting, "bot");
    }, 500);

    // Apply branding from server
    applyBranding();
})();
