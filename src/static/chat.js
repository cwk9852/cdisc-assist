document.addEventListener('DOMContentLoaded', function() {
  const form = document.querySelector('form');
  const messageInput = document.querySelector('#message-input');
  const messagesContainer = document.querySelector('.messages');
  const domainTooltip = document.getElementById('domain-info-tooltip');

  form.addEventListener('submit', function(e) {
      e.preventDefault();

      const userMessage = messageInput.value.trim();
      if (!userMessage) return;

      appendMessage('User', userMessage, 'user-message');
      messageInput.value = '';

      const processingId = appendMessage('Assistant', 'Processing...', 'assistant-message');

      fetch('/chat', {
          method: 'POST',
          headers: {
              'Content-Type': 'application/json'
          },
          body: JSON.stringify({ message: userMessage })
      })
      .then(response => {
          if (!response.ok) {
              throw new Error(`Server error: ${response.status}`);
          }
          return response.json();
      })
      .then(data => {
          if (data.success) {
              updateMessage(processingId, data.response);
              applyCodeHighlighting();
          } else {
              updateMessage(processingId, 'Error: ' + data.response);
          }
      })
      .catch(error => {
          console.error('Error:', error);
          updateMessage(processingId, 'Error: ' + error.message);
      });
  });

  function appendMessage(sender, content, className) {
      const welcomeMessage = document.querySelector('.welcome-message');
      if (welcomeMessage) welcomeMessage.remove();

      const roleEl = document.createElement('div');
      roleEl.classList.add('message-role', sender.toLowerCase());
      roleEl.textContent = sender;
      messagesContainer.appendChild(roleEl);

      const messageEl = document.createElement('div');
      messageEl.classList.add(className);
      messageEl.dataset.id = Date.now();
      messageEl.textContent = content;
      messageEl.innerHTML = messageEl.innerHTML.replace(/\n/g, '<br>');
      messagesContainer.appendChild(messageEl);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      return messageEl.dataset.id;
  }

  function updateMessage(id, content) {
      const messages = document.querySelectorAll('.assistant-message');
      let found = false;
      for (const message of messages) {
          if (message.dataset.id === id) {
              message.textContent = content;
              message.innerHTML = message.innerHTML.replace(/\n/g, '<br>');
              messagesContainer.scrollTop = messagesContainer.scrollHeight;
              found = true;
              break;
          }
      }
      if (!found) {
          console.error('Could not find message with ID:', id);
          appendMessage('Assistant', content, 'assistant-message');
      }
  }

  // Basic code formatting (wraps SQL in <pre><code class="language-sql">)
  function applyCodeHighlighting() {
      const codeBlocks = document.querySelectorAll('.assistant-message');
      codeBlocks.forEach(block => {
          let content = block.innerHTML; // Work with innerHTML

          if (content.includes('SELECT') || content.includes('WITH')) {
            // Simple SQL detection
              content = content.replace(/<!--/g, '<!--').replace(/-->/g, '-->');
              if (!content.includes('<pre>')) { // Check if already formatted
                  content = `<pre><code class="language-sql">${content}</code></pre>`;
              }
          }
            block.innerHTML = content; // Set using innerHTML
      });
  }

  // Function to handle domain interactions and information display
  function setupDomainInteractions() {
      const domainItems = document.querySelectorAll('.domain-item');

      // Create template suggestions by domain
      const domainSuggestions = {
          'DM': 'Create a mapping to convert source demographics to SDTM DM domain',
          'AE': 'Generate SQL for mapping adverse events to SDTM AE domain',
          'LB': 'Write SQL to transform lab data into SDTM LB domain',
          'VS': 'Create a transformation for vital signs to SDTM VS domain',
          'CM': 'Map concomitant medication data to SDTM CM domain',
          'EX': 'Write code to convert study drug administration to SDTM EX domain',
          'MH': 'Transform medical history data to SDTM MH domain',
          'TU': 'Map tumor assessment data to SDTM TU domain',
          'RS': 'Create SDTM RS domain mapping for response data',
          'ADSL': 'Generate ADaM ADSL code from source demographics data',
          'ADAE': 'Create ADaM ADAE dataset SQL for adverse event analysis',
          'ADLB': 'Generate lab analysis with normal range flags for ADLB',
          'ADTTE': 'Create time-to-event analysis dataset (ADTTE) with SQL',
          'ADRS': 'Generate RECIST response analysis for ADRS domain',
          'ADTR': 'Create Best Overall Response analysis in ADTR domain'
      };

      // Process domain variables for tooltip display
      function formatVariables(varsString) {
          const varsList = varsString.split(', ');
          let varHtml = '';

          varsList.forEach(variable => {
              varHtml += `<span>${variable}</span>`;
          });

          return varHtml;
      }

      // Show domain information in tooltip
      function showDomainInfo(e) {
          const domainItem = e.currentTarget;
          const domain = domainItem.dataset.domain;
          const description = domainItem.dataset.desc;
          const variables = domainItem.dataset.vars;
          const domainName = domainItem.textContent.trim();

          document.getElementById('tooltip-domain-code').textContent = domain;
          document.getElementById('tooltip-domain-name').textContent = domainName.replace(domain, '').trim();
          document.getElementById('tooltip-domain-desc').textContent = description;
          document.getElementById('tooltip-domain-vars').innerHTML = formatVariables(variables);

          const rect = domainItem.getBoundingClientRect();
          domainTooltip.style.top = rect.top + 'px';
          domainTooltip.classList.add('visible');

          // Set the initial value of messageInput with the suggestion but do not focus
          const suggestion = domainSuggestions[domain] || `Tell me about the ${domain} domain structure and purpose`;
          messageInput.value = suggestion;
      }

      // Hide domain info tooltip
      function hideDomainInfo() {
          domainTooltip.classList.remove('visible');
      }

      // Add event listeners to all domain items
      domainItems.forEach(item => {
          item.addEventListener('mouseenter', showDomainInfo);
          item.addEventListener('mouseleave', hideDomainInfo);

          // Add click handler to submit the query
          item.addEventListener('click', function(e) {
              const domain = this.dataset.domain;
              const suggestion = domainSuggestions[domain] || `Tell me about the ${domain} domain structure and purpose`;

              messageInput.value = suggestion;  // Set value from suggestion
              form.dispatchEvent(new Event('submit')); // Trigger the submit event on the form
              hideDomainInfo();

          });
      });
  }

  // Add handler for context reset button
  const clearContextBtn = document.getElementById('clear-context-btn');
  if (clearContextBtn) {
      clearContextBtn.addEventListener('click', function() {
          if (confirm("This will clear all context from the assistant. Continue?")) {
              fetch('/clear_chat', {
                  method: 'POST',
                  headers: {
                      'Content-Type': 'application/json'
                  }
              })
              .then(response => response.json())
              .then(data => {
                  if (data.success) {
                      // Reset UI with welcome HTML from server
                      if (data.welcome_html) {
                          document.querySelector('.messages').innerHTML = data.welcome_html;
                      } else {
                          // Fallback if no welcome HTML is provided
                          document.querySelector('.messages').innerHTML = `
                <div class="welcome-message">
                  <h3>Welcome to the CDISC Standards Assistant</h3>
                  <p>Context has been reset successfully.</p>
                </div>
              `;
                      }
                  } else {
                      console.error('Failed to clear context:', data.message);
                  }
              })
              .catch(error => {
                  console.error('Error clearing context:', error);
              });
          }
      });
  }

  // Initialize the new tooltip and interactions here
  setupDomainInteractions();
});