(function() {
    // 1. Initial Config
    const API_KEY = "dev-api-key-123"; 
    const BACKEND_URL = "/chat"; // Relative path works since served from same domain

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
        <div id="shinju-chat-input-area">
            <input type="text" id="shinju-chat-input" placeholder="${translations[currentLang].input}">
            <button id="shinju-chat-send">${translations[currentLang].send}</button>
        </div>
    `;
    document.body.appendChild(container);

    const msgContainer = document.getElementById("shinju-chat-messages");
    const input = document.getElementById("shinju-chat-input");
    const langSelect = document.getElementById("shinju-chat-lang-select");
    const headerTitle = document.getElementById("shinju-chat-title");
    const sendBtn = document.getElementById("shinju-chat-send");

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
                const errData = await response.json();
                appendMessage("Error: " + (errData.detail || "Server error"), "bot");
                return;
            }

            const data = await response.json();
            if (data.reply) {
                appendMessage(data.reply, "bot");
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
})();
