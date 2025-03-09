// Minimal chat handler
document.addEventListener('DOMContentLoaded', function() {
  const form = document.querySelector('form');
  const messageInput = document.querySelector('#message-input');
  const messagesContainer = document.querySelector('.messages');
  
  // Prevent normal form submission
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    
    // Get user message
    const userMessage = messageInput.value.trim();
    if (!userMessage) return;
    
    // Display user message
    appendMessage('User', userMessage, 'user-message');
    
    // Clear input
    messageInput.value = '';
    
    // Display processing message
    const processingId = appendMessage('Assistant', 'Processing...', 'assistant-message');
    
    // Make request with basic XMLHttpRequest
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/chat');
    xhr.setRequestHeader('Content-Type', 'application/json');
    
    xhr.onload = function() {
      if (xhr.status === 200) {
        try {
          // Parse response
          const data = JSON.parse(xhr.responseText);
          
          // Update message content
          if (data.success) {
            updateMessage(processingId, data.response);
          } else {
            updateMessage(processingId, 'Error: ' + data.response);
          }
        } catch (e) {
          updateMessage(processingId, 'Error parsing response');
          console.error('Error parsing response:', e);
        }
      } else {
        updateMessage(processingId, 'Server error: ' + xhr.status);
        console.error('Server error:', xhr.status);
      }
    };
    
    xhr.onerror = function() {
      updateMessage(processingId, 'Network error');
      console.error('Network error');
    };
    
    // Send request
    xhr.send(JSON.stringify({message: userMessage}));
  });
  
  // Helper function to add a message to the chat
  function appendMessage(sender, content, className) {
    // Remove welcome message if present
    const welcomeMessage = document.querySelector('.welcome-message');
    if (welcomeMessage) {
      welcomeMessage.remove();
    }
    
    // Create role element
    const roleEl = document.createElement('div');
    roleEl.classList.add('message-role');
    roleEl.classList.add(sender.toLowerCase());
    roleEl.textContent = sender;
    messagesContainer.appendChild(roleEl);
    
    // Create message element
    const messageEl = document.createElement('div');
    messageEl.classList.add(className);
    messageEl.textContent = content;
    messageEl.dataset.id = Date.now(); // Use timestamp as ID
    messagesContainer.appendChild(messageEl);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    
    return messageEl.dataset.id;
  }
  
  // Helper function to update a message
  function updateMessage(id, content) {
    console.log('Updating message with ID:', id, 'Content:', content.substring(0, 50) + '...');
    
    // Only look at assistant messages - prevent updating user messages
    const messages = document.querySelectorAll('.assistant-message');
    
    let found = false;
    for (const message of messages) {
      if (message.dataset.id === id) {
        console.log('Found matching message element');
        message.textContent = content;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        found = true;
        break;
      }
    }
    
    if (!found) {
      console.error('Could not find message with ID:', id);
      // Fallback - append a new message
      appendMessage('Assistant', content, 'assistant-message');
    }
  }
});