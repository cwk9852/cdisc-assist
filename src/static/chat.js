document.addEventListener('DOMContentLoaded', function() {
  const form = document.querySelector('form');
  const messageInput = document.querySelector('#message-input');
  const messagesContainer = document.querySelector('.messages');
  const domainTooltip = document.getElementById('domain-info-tooltip');
  
  // Configure marked.js for better performance
  marked.setOptions({
    gfm: true,             // GitHub Flavored Markdown
    breaks: true,          // Convert \n to <br>
    silent: true,          // Don't throw on error
    smartLists: true,      // Use smarter list behavior
    smartypants: false,    // Don't use "smart" typography punctuation
    xhtml: false,          // Don't use self-closing tags
    headerIds: false,      // Don't include ids in headers (faster)
    mangle: false,         // Don't escape autolinks (faster)
    pedantic: false,       // Don't be pedantic about spec conformance (faster)
    async: false,          // Synchronous rendering (faster for our use case)
  });
  
  // Simpler marked extension with minimal transformations to avoid breaking rendering
  const cleanExtension = {
    name: 'cleanMarkdown',
    level: 'block',
    start(src) { return 0; },
    tokenizer(src) {
      // No need to create a token, just return undefined
      return undefined;
    },
    renderer(token) {
      return token.text;
    }
  };

  marked.use({ extensions: [cleanExtension] });
  
  // Create a basic renderer with minimal customization to avoid bugs
  const renderer = new marked.Renderer();
  
  // Only minimal styling for paragraphs
  renderer.paragraph = function(text) {
    if (text === '[object Object]') {
      return '<p style="margin-bottom: 0.4em; line-height: 1.3;"></p>';
    }
    return '<p style="margin-bottom: 0.4em; line-height: 1.3;">' + text + '</p>';
  };
  
  // Simple header with minimal styling
  renderer.heading = function(text, level) {
    if (text === '[object Object]' || typeof text === 'object') {
      return '<h' + level + ' style="margin-top: 0.4em; margin-bottom: 0.3em;">Section Heading</h' + level + '>';
    }
    return '<h' + level + ' style="margin-top: 0.4em; margin-bottom: 0.3em;">' + text + '</h' + level + '>';
  };
  
  // Simple list
  renderer.list = function(body, ordered) {
    const type = ordered ? 'ol' : 'ul';
    return '<' + type + ' style="margin-top: 0.2em; margin-bottom: 0.2em; padding-left: 1.2em;">' + 
           body + '</' + type + '>';
  };
  
  // Simple list item
  renderer.listitem = function(text) {
    if (text === '[object Object]') {
      return '<li style="margin-bottom: 0.1em; line-height: 1.3;"></li>';
    }
    return '<li style="margin-bottom: 0.1em; line-height: 1.3;">' + text + '</li>';
  };
  
  // Simple table
  renderer.table = function(header, body) {
    return '<table style="font-size: 0.9em; border-collapse: collapse; margin: 0.5em 0;">' +
           '<thead>' + header + '</thead>' +
           '<tbody>' + body + '</tbody>' +
           '</table>';
  };
  
  marked.use({ renderer });

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
              // Clean any [object Object] references in the response
              const cleanedResponse = data.response.replace(/\[object Object\]/g, '');
              updateMessage(processingId, cleanedResponse);
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

      // We don't need sender labels anymore, but keep the class for styling
      // Create message element directly without the roleEl
      const messageEl = document.createElement('div');
      messageEl.classList.add(className, sender.toLowerCase() + '-container');
      messageEl.dataset.id = Date.now();
      
      // Ensure content is a string
      if (typeof content !== 'string') {
          console.warn('Non-string content received in appendMessage:', content);
          // Try to safely convert to string
          try {
              if (content === null || content === undefined) {
                  content = '';
              } else if (typeof content === 'object') {
                  // Try to JSON stringify if it's an object
                  content = JSON.stringify(content, null, 2);
              } else {
                  content = String(content);
              }
          } catch (e) {
              console.error('Error converting content to string:', e);
              content = 'Error: Unable to display content';
          }
      }
      
      // For user messages, just do basic formatting
      if (sender.toLowerCase() === 'user') {
          messageEl.textContent = content;
          messageEl.innerHTML = messageEl.innerHTML.replace(/\n/g, '<br>');
      } 
      // For assistant processing message, show spinner - without hardcoded ellipsis
      else if (content === 'Processing...') {
          messageEl.innerHTML = `
              <div class="loading-container">
                  <div class="loading-spinner"></div>
                  <span>Processing your request<span class="thinking-dots"></span></span>
              </div>
          `;
      }
      // For assistant messages, use the same markdown/code handling as updateMessage
      else if (content.includes('```')) {
          // Handle in updateMessage through initial content
          messageEl.textContent = content;
      }
      else {
          // Use the same direct HTML approach for better reliability
          try {
              let html = '';
              const lines = content.split('\n');
              
              for (let i = 0; i < lines.length; i++) {
                  const line = lines[i];
                  
                  // Check if it's a heading
                  if (line.startsWith('#')) {
                      const level = line.match(/^#+/)[0].length;
                      const text = line.substring(level).trim();
                      html += `<h${level} style="margin: 0.4em 0">${text}</h${level}>`;
                  }
                  // Check if it's a list item
                  else if (line.match(/^\s*[-*+]\s/)) {
                      // Start a list if we're not already in one
                      if (i === 0 || !lines[i-1].match(/^\s*[-*+]\s/)) {
                          html += '<ul style="margin: 0.2em 0; padding-left: 1.2em">';
                      }
                      
                      const text = line.replace(/^\s*[-*+]\s/, '');
                      html += `<li>${text}</li>`;
                      
                      // End list if next line is not a list item
                      if (i === lines.length - 1 || !lines[i+1].match(/^\s*[-*+]\s/)) {
                          html += '</ul>';
                      }
                  }
                  // Just a normal paragraph
                  else if (line.trim() !== '') {
                      html += `<p style="margin: 0.4em 0">${line}</p>`;
                  }
                  // Empty line - add some space
                  else if (line.trim() === '') {
                      html += '<div style="height: 0.5em"></div>';
                  }
              }
              
              messageEl.innerHTML = html;
          } catch (e) {
              console.error('Error formatting content:', e);
              // Very basic fallback
              messageEl.textContent = content;
              messageEl.innerHTML = messageEl.innerHTML.replace(/\n/g, '<br>');
          }
      }
      
      // Add message to container and scroll to bottom
      messagesContainer.appendChild(messageEl);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      return messageEl.dataset.id;
  }

  // Simple helper function to clean markdown - minimal changes to avoid breaking rendering
  function cleanMarkdown(content) {
      if (typeof content !== 'string') {
          return "Error: Non-string content received";
      }
      
      // Remove all [object Object] occurrences
      content = content.replace(/\[object Object\]/g, '');
      
      // Remove "Section Header" text (which might be inserted by fallbacks)
      content = content.replace(/Section Header/g, '');
      
      // Clean up excess newlines - replace 3+ newlines with 2
      content = content.replace(/\n{3,}/g, '\n\n');
      
      // Fix any headers that might end up empty after object removal
      content = content.replace(/^(#{1,6})\s*$/gm, '');
      
      return content;
  }
  
  function updateMessage(id, content) {
      console.time('updateMessage');
      const messages = document.querySelectorAll('.assistant-message');
      let found = false;
      
      // Ensure content is a string
      if (typeof content !== 'string') {
          console.warn('Non-string content received:', content);
          // Try to safely convert to string
          try {
              if (content === null || content === undefined) {
                  content = '';
              } else if (typeof content === 'object') {
                  // Try to JSON stringify if it's an object
                  content = JSON.stringify(content, null, 2);
              } else {
                  content = String(content);
              }
          } catch (e) {
              console.error('Error converting content to string:', e);
              content = 'Error: Unable to display content';
          }
      }
      
      // Clean up markdown content
      content = cleanMarkdown(content);
      
      for (const message of messages) {
          if (message.dataset.id === id) {
              // Check if content has code blocks
              if (content.includes('```')) {
                  console.log('Message contains code blocks');
                  
                  // More direct approach to handle code blocks
                  let parts = [];
                  let lastIndex = 0;
                  
                  // Simple regex to find code blocks
                  const codeBlockRegex = /```(sql|python|r)?\s*\n([\s\S]*?)```/g;
                  let match;
                  
                  // Find each code block and process text before it
                  while ((match = codeBlockRegex.exec(content)) !== null) {
                      // Process text before code block with markdown
                      if (match.index > lastIndex) {
                          const textBefore = content.substring(lastIndex, match.index);
                          parts.push({ type: 'text', content: textBefore });
                      }
                      
                      // Process code block
                      const language = match[1] || 'sql';
                      const code = match[2].trim();
                      parts.push({ type: 'code', language: language, content: code });
                      
                      // Update lastIndex to after this code block
                      lastIndex = match.index + match[0].length;
                  }
                  
                  // Process any remaining text after the last code block
                  if (lastIndex < content.length) {
                      const textAfter = content.substring(lastIndex);
                      parts.push({ type: 'text', content: textAfter });
                  }
                  
                  // Build the final HTML
                  let finalHTML = '';
                  for (const part of parts) {
                      if (part.type === 'text') {
                          // Apply markdown to text parts
                          try {
                              finalHTML += marked.parse(part.content);
                          } catch (e) {
                              console.error('Error parsing markdown:', e);
                              finalHTML += part.content.replace(/\n/g, '<br>');
                          }
                      } else if (part.type === 'code') {
                          // Format code blocks
                          finalHTML += formatCodeBlock(part.language, part.content);
                      }
                  }
                  
                  message.innerHTML = finalHTML;
              } else {
                  // For messages without code, apply simpler formatting
                  try {
                      // Use a more direct HTML approach for better reliability
                      let html = '';
                      const lines = content.split('\n');
                      
                      for (let i = 0; i < lines.length; i++) {
                          const line = lines[i];
                          
                          // Check if it's a heading
                          if (line.startsWith('#')) {
                              const level = line.match(/^#+/)[0].length;
                              const text = line.substring(level).trim();
                              html += `<h${level} style="margin: 0.4em 0">${text}</h${level}>`;
                          }
                          // Check if it's a list item
                          else if (line.match(/^\s*[-*+]\s/)) {
                              // Start a list if we're not already in one
                              if (i === 0 || !lines[i-1].match(/^\s*[-*+]\s/)) {
                                  html += '<ul style="margin: 0.2em 0; padding-left: 1.2em">';
                              }
                              
                              const text = line.replace(/^\s*[-*+]\s/, '');
                              html += `<li>${text}</li>`;
                              
                              // End list if next line is not a list item
                              if (i === lines.length - 1 || !lines[i+1].match(/^\s*[-*+]\s/)) {
                                  html += '</ul>';
                              }
                          }
                          // Just a normal paragraph
                          else if (line.trim() !== '') {
                              html += `<p style="margin: 0.4em 0">${line}</p>`;
                          }
                          // Empty line - add some space
                          else {
                              html += '<div style="height: 0.5em"></div>';
                          }
                      }
                      
                      message.innerHTML = html;
                  } catch (e) {
                      console.error('Error formatting content:', e);
                      // Very basic fallback
                      message.textContent = content;
                      message.innerHTML = message.innerHTML.replace(/\n/g, '<br>');
                  }
              }
              
              // Apply highlighting to any inline code that was missed
              message.querySelectorAll('code:not(.hljs)').forEach(block => {
                  if (!block.classList.contains('highlighted') && block.parentElement.tagName !== 'PRE') {
                      hljs.highlightElement(block);
                      block.classList.add('highlighted');
                  }
              });
              
              messagesContainer.scrollTop = messagesContainer.scrollHeight;
              console.timeEnd('updateMessage');
              found = true;
              break;
          }
      }
      if (!found) {
          console.error('Could not find message with ID:', id);
          appendMessage('Assistant', content, 'assistant-message');
      }
  }
  
  // Format a single code block with syntax highlighting - simplified for reliability
  function formatCodeBlock(language, code) {
      // Make sure we have a valid language
      language = language || 'sql';
      if (!language) language = 'sql';
      
      // Create a very simple code block with minimal styling
      return `<div style="margin: 0.6em 0; border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden;">
          <div style="background-color: #f5f5f5; padding: 4px 8px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between;">
              <span style="font-weight: bold">${language.toUpperCase()}</span>
              <button class="copy-btn" style="border: none; background: none; cursor: pointer; color: #1a73e8;">Copy</button>
          </div>
          <pre style="margin: 0; padding: 8px; max-height: 300px; overflow: auto; font-size: 12px; line-height: 1.3;"><code class="${language}">${
              // Basic HTML escaping
              code.replace(/&/g, "&amp;")
                  .replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;")
                  .replace(/"/g, "&quot;")
                  .replace(/'/g, "&#039;")
          }</code></pre>
      </div>`;
  }

  // Apply syntax highlighting to code blocks
  function applyCodeHighlighting() {
      // Apply syntax highlighting to all code blocks using highlight.js
      document.querySelectorAll('pre code').forEach(block => {
          if (!block.classList.contains('highlighted')) {
              hljs.highlightElement(block);
              block.classList.add('highlighted');
          }
      });
      
      // Add copy functionality to all copy buttons
      document.querySelectorAll('.copy-btn').forEach(btn => {
          if (!btn.hasAttribute('listener-added')) {
              btn.setAttribute('listener-added', 'true');
              btn.addEventListener('click', function() {
                  // Find the associated code block
                  const container = this.closest('.code-block-container');
                  const codeBlock = container.querySelector('pre code');
                  
                  // Copy code text to clipboard
                  navigator.clipboard.writeText(codeBlock.textContent)
                  .then(() => {
                      // Success feedback
                      const originalText = this.textContent;
                      this.textContent = 'Copied!';
                      this.style.backgroundColor = '#4caf50';
                      
                      // Reset after 2 seconds
                      setTimeout(() => {
                          this.textContent = originalText;
                          this.style.backgroundColor = '';
                      }, 2000);
                  })
                  .catch(err => {
                      console.error('Failed to copy:', err);
                      this.textContent = 'Failed!';
                      this.style.backgroundColor = '#f44336';
                      
                      setTimeout(() => {
                          this.textContent = 'Copy';
                          this.style.backgroundColor = '';
                      }, 2000);
                  });
              });
          }
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

          // Don't update the input value anymore - just show in tooltip instead
          // Store the suggestion for use if the user clicks, but don't auto-fill
          domainItem.dataset.suggestion = domainSuggestions[domain] || `Tell me about the ${domain} domain structure and purpose`;
      }

      // Hide domain info tooltip
      function hideDomainInfo() {
          domainTooltip.classList.remove('visible');
      }

      // Add event listeners to all domain items
      domainItems.forEach(item => {
          item.addEventListener('mouseenter', showDomainInfo);
          item.addEventListener('mouseleave', hideDomainInfo);

          // Add click handler that only fills the input box when clicked (but doesn't auto-submit)
          item.addEventListener('click', function(e) {
              const domain = this.dataset.domain;
              const suggestion = domainSuggestions[domain] || `Tell me about the ${domain} domain structure and purpose`;

              // Only change input value, don't auto-submit
              messageInput.value = suggestion;
              messageInput.focus();
              
              // Hide tooltip
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