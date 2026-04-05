(function() {
    // 1. Initial Config
    const API_KEY = "dev-api-key-123"; 
    const BACKEND_URL = "/chat"; // Relative path works since served from same domain

    // Session Memory Tracking
    let sessionId = localStorage.getItem("keiz_chat_session");
    if (!sessionId) {
        sessionId = "sess_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("keiz_chat_session", sessionId);
    }

    // 2. Inject CSS
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/widget/chat.css"; 
    document.head.appendChild(link);

    // 3. Build UI Elements
    const bubble = document.createElement("div");
    bubble.id = "keiz-chat-bubble";
    bubble.innerHTML = "💬";
    document.body.appendChild(bubble);

    const container = document.createElement("div");
    container.id = "keiz-chat-container";
    container.innerHTML = `
        <div id="keiz-chat-header">
            <span>Keiz Support</span>
            <span style="cursor:pointer;" id="keiz-chat-close">✖</span>
        </div>
        <div id="keiz-chat-messages" style="display:flex; flex-direction:column;"></div>
        <div id="keiz-chat-input-area">
            <input type="text" id="keiz-chat-input" placeholder="Type a message...">
            <button id="keiz-chat-send">Send</button>
        </div>
    `;
    document.body.appendChild(container);

    const msgContainer = document.getElementById("keiz-chat-messages");
    const input = document.getElementById("keiz-chat-input");

    // 4. Interaction Logic
    bubble.onclick = () => {
        container.style.display = container.style.display === "flex" ? "none" : "flex";
    };

    document.getElementById("keiz-chat-close").onclick = () => {
        container.style.display = "none";
    };

    function appendMessage(text, sender) {
        const div = document.createElement("div");
        div.className = `keiz-message keiz-${sender}`;
        div.innerText = text;
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
                body: JSON.stringify({ message: text, session_id: sessionId })
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

    document.getElementById("keiz-chat-send").onclick = sendMessage;
    input.onkeypress = (e) => {
        if (e.key === "Enter") sendMessage();
    };

    // Initial greeting
    setTimeout(() => {
        appendMessage("Hello! I am the Omni-Engine. How can I help you today?", "bot");
    }, 500);
})();
