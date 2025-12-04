/**
 * Chat UI for Trello Orders Agent
 * 
 * Handles communication with the Cloud Run API backend
 * and manages session persistence.
 */

// Configuration - Cloud Run service URL
const API_URL = 'https://trello-orders-api-kspii3btya-uc.a.run.app';

// Generate or retrieve session ID
function getSessionId() {
    let sessionId = localStorage.getItem('chat_session_id');
    if (!sessionId) {
        sessionId = 'session-' + crypto.randomUUID();
        localStorage.setItem('chat_session_id', sessionId);
    }
    return sessionId;
}

// Initialize
const sessionId = getSessionId();
document.getElementById('session-id').textContent = sessionId;

const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendButton = document.getElementById('send-button');
const errorMessage = document.getElementById('error-message');

// Auto-scroll to bottom
function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Add message to chat
function addMessage(text, isUser = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    if (isUser) {
        // User messages are plain text
        const p = document.createElement('p');
        p.textContent = text;
        contentDiv.appendChild(p);
    } else {
        // Bot messages are rendered as markdown
        try {
            // Check if marked is loaded
            if (typeof marked !== 'undefined' && marked.parse) {
                // Configure marked for safe rendering
                marked.setOptions({
                    breaks: true,      // Convert \n to <br>
                    gfm: true,         // GitHub Flavored Markdown
                });
                contentDiv.innerHTML = marked.parse(text);
            } else {
                // Fallback: basic formatting if marked isn't available
                console.warn('Marked library not loaded, using fallback formatting');
                contentDiv.innerHTML = text
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                    .replace(/\*(.+?)\*/g, '<em>$1</em>')
                    .replace(/`(.+?)`/g, '<code>$1</code>')
                    .replace(/\n/g, '<br>');
            }
        } catch (e) {
            console.error('Markdown parsing error:', e);
            // Simple fallback
            contentDiv.innerHTML = text
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/`(.+?)`/g, '<code>$1</code>')
                .replace(/\n/g, '<br>');
        }
    }
    
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

// Show error
function showError(message) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
    setTimeout(() => {
        errorMessage.style.display = 'none';
    }, 5000);
}

// Send message to API
async function sendMessage(message) {
    if (!message.trim()) {
        return;
    }

    // Disable input while processing
    messageInput.disabled = true;
    sendButton.disabled = true;
    sendButton.classList.add('loading');

    // Add user message to chat
    addMessage(message, true);

    // Clear input
    messageInput.value = '';

    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                session_id: sessionId,
                message: message
            })
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();
        addMessage(data.reply || 'No response received');

    } catch (error) {
        console.error('Error sending message:', error);
        showError(`Error: ${error.message}`);
        addMessage('Sorry, I encountered an error. Please try again.');
    } finally {
        // Re-enable input
        messageInput.disabled = false;
        sendButton.disabled = false;
        sendButton.classList.remove('loading');
        messageInput.focus();
    }
}

// Event listeners
sendButton.addEventListener('click', () => {
    const message = messageInput.value.trim();
    if (message) {
        sendMessage(message);
    }
});

messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const message = messageInput.value.trim();
        if (message) {
            sendMessage(message);
        }
    }
});

// Focus input on load
messageInput.focus();

// Initial scroll
scrollToBottom();

