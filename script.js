/* =========================================================================
   SpareX Assist – Chat Interaction Logic
   ========================================================================= */

const chatMessages = document.getElementById("chat-messages");
const chatArea = document.getElementById("chat-area");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");

// Enter key sends message
userInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

/**
 * Send the user's message to the backend and display the response.
 */
async function sendMessage() {
    const query = userInput.value.trim();
    if (!query) return;

    // Clear input and disable button
    userInput.value = "";
    sendBtn.disabled = true;

    // Show user message
    appendMessage(query, "user");

    // Show typing indicator
    const typingEl = showTyping();

    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query }),
        });

        const data = await res.json();

        // Remove typing indicator
        typingEl.remove();

        // Show bot answer
        appendMessage(data.answer, "bot");

        // Show result cards
        if (data.cards && data.cards.length > 0) {
            data.cards.forEach((card) => appendCard(card));
        }
    } catch (err) {
        typingEl.remove();
        appendMessage("❌ Connection error. Please check if the server is running.", "bot");
    } finally {
        sendBtn.disabled = false;
        userInput.focus();
    }
}

/**
 * Append a chat message bubble.
 */
function appendMessage(text, sender) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${sender}-message animate-in`;

    const label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = sender === "user" ? "You" : "🤖 SpareX";

    const bubble = document.createElement("div");
    bubble.className = `msg-bubble ${sender}-bubble`;

    // Convert newlines to <br> and preserve HTML tags from the backend
    bubble.innerHTML = text.replace(/\n/g, "<br>");

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    chatMessages.appendChild(wrapper);

    scrollToBottom();
}

/**
 * Append a result card (key-value pairs).
 */
function appendCard(data) {
    const card = document.createElement("div");
    card.className = "result-card animate-in";

    for (const [key, val] of Object.entries(data)) {
        const row = document.createElement("div");
        row.className = "card-row";

        const keyEl = document.createElement("span");
        keyEl.className = "card-key";
        keyEl.textContent = key + ":";

        const valEl = document.createElement("span");
        valEl.className = "card-val";
        valEl.textContent = val;

        row.appendChild(keyEl);
        row.appendChild(valEl);
        card.appendChild(row);
    }

    chatMessages.appendChild(card);
    scrollToBottom();
}

/**
 * Show a typing indicator and return the element (so caller can remove it).
 */
function showTyping() {
    const wrapper = document.createElement("div");
    wrapper.className = "message bot-message animate-in";

    const label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = "🤖 SpareX";

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble bot-bubble typing-indicator";
    bubble.innerHTML = `
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
    `;

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    chatMessages.appendChild(wrapper);

    scrollToBottom();
    return wrapper;
}

/**
 * Scroll chat to the bottom.
 */
function scrollToBottom() {
    requestAnimationFrame(() => {
        chatArea.scrollTop = chatArea.scrollHeight;
    });
}
