/**
 * Format all messages when the page loads - called from body onload
 */
function formatMessagesOnLoad() {
  console.log('Formatting messages on page load');
  
  // Process all assistant messages first
  const assistantMessages = document.querySelectorAll('.assistant-message');
  console.log('Found assistant messages:', assistantMessages.length);
  
  assistantMessages.forEach(message => {
    try {
      const rawContent = message.getAttribute('data-raw') || message.textContent;
      if (!rawContent || rawContent === 'Processing...') return;

      // Apply markdown formatting
      message.innerHTML = formatContent(rawContent);
      
      // Apply syntax highlighting to code blocks
      message.querySelectorAll('pre code').forEach(block => {
        if (!block.classList.contains('highlighted')) {
          hljs.highlightElement(block);
          block.classList.add('highlighted');
        }
      });

      // Add copy functionality to code blocks
      message.querySelectorAll('.copy-btn').forEach(btn => {
        if (!btn.hasAttribute('listener-added')) {
          btn.setAttribute('listener-added', 'true');
          btn.addEventListener('click', function() {
            const codeBlock = this.closest('.code-block');
            const code = codeBlock?.querySelector('pre code');
            if (code) {
              navigator.clipboard.writeText(code.textContent)
                .then(() => {
                  const originalText = this.textContent;
                  this.textContent = 'Copied!';
                  this.style.backgroundColor = '#4caf50';
                  setTimeout(() => {
                    this.textContent = originalText;
                    this.style.backgroundColor = '';
                  }, 1500);
                });
            }
          });
        }
      });
    } catch (e) {
      console.error('Error formatting message:', e);
    }
  });

  // Format user messages with simple line breaks
  const userMessages = document.querySelectorAll('.user-message');
  userMessages.forEach(message => {
    try {
      const content = message.textContent;
      if (content) {
        message.innerHTML = content.replace(/\n/g, '<br>');
      }
    } catch (e) {
      console.error('Error formatting user message:', e);
    }
  });
}

document.addEventListener('DOMContentLoaded', function() {
  const form = document.querySelector('form');
  const messageInput = document.querySelector('#message-input');
  const messagesContainer = document.querySelector('.messages');
  const domainTooltip = document.getElementById('domain-info-tooltip');
  
  // Initialize micromark for markdown rendering
  const micromarkAvailable = typeof micromark !== 'undefined';
  console.log('Micromark available:', micromarkAvailable);

  form.addEventListener('submit', function(e) {
      e.preventDefault();

      const userMessage = messageInput.value.trim();
      if (!userMessage) return;

      // Add user message with proper styling
      appendMessage('User', userMessage, 'user-message');
      messageInput.value = '';

      // Show processing message with spinner
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

      // Create message element
      const messageEl = document.createElement('div');
      messageEl.classList.add(className, sender.toLowerCase() + '-container');
      messageEl.dataset.id = Date.now();
      
      // Ensure content is a string
      if (typeof content !== 'string') {
          console.warn('Non-string content received in appendMessage:', content);
          try {
              if (content === null || content === undefined) {
                  content = '';
              } else if (typeof content === 'object') {
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
      // For assistant processing message, show spinner
      else if (content === 'Processing...') {
          messageEl.innerHTML = `
              <div class="loading-container">
                  <div class="loading-spinner"></div>
                  <span>Processing your request<span class="thinking-dots"></span></span>
              </div>
          `;
      }
      // For normal assistant messages
      else {
          try {
              // Use our unified formatter for consistency
              messageEl.innerHTML = formatContent(content);
              
              // Apply code highlighting if any
              messageEl.querySelectorAll('pre code').forEach(block => {
                  if (!block.classList.contains('highlighted')) {
                      hljs.highlightElement(block);
                      block.classList.add('highlighted');
                  }
              });
              
              // Add copy functionality to code blocks
              messageEl.querySelectorAll('.copy-btn').forEach(btn => {
                  if (!btn.hasAttribute('listener-added')) {
                      btn.setAttribute('listener-added', 'true');
                      btn.addEventListener('click', function() {
                          const codeBlock = this.closest('.code-block');
                          const codeElement = codeBlock?.querySelector('pre code');
                          if (codeElement) {
                              navigator.clipboard.writeText(codeElement.textContent)
                                .then(() => {
                                  // Visual feedback
                                  const originalText = this.textContent;
                                  this.textContent = 'Copied!';
                                  this.style.backgroundColor = '#4caf50';
                                  this.style.color = 'white';
                                  
                                  setTimeout(() => {
                                    this.textContent = originalText;
                                    this.style.backgroundColor = '';
                                    this.style.color = '#2563eb';
                                  }, 1500);
                                })
                                .catch(err => {
                                  console.error('Failed to copy:', err);
                                });
                          }
                      });
                  }
              });
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

  /**
   * Modern markdown renderer that uses micromark if available, falls back to custom parser
   */
  function formatContent(content) {
      if (typeof content !== 'string') {
          return "Error: Non-string content received";
      }
      
      // Basic cleanup
      content = content.replace(/\[object Object\]/g, '');
      content = content.replace(/Section Header/g, '');
      content = content.replace(/undefined/g, '');
      
      // Extract code blocks first to protect them from markdown processing
      const codeBlocks = [];
      content = content.replace(/```([\s\S]*?)```/g, function(match, codeContent) {
          const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
          codeBlocks.push(match);
          return placeholder;
      });

      // Always use custom parser since it handles CDISC-specific formatting better
      let html = customMarkdownParser(content);
      
      // Restore code blocks
      html = html.replace(/__CODE_BLOCK_(\d+)__/g, function(match, index) {
          const codeBlock = codeBlocks[parseInt(index, 10)];
          if (!codeBlock) return match;
          
          // Parse the code block
          const match1 = codeBlock.match(/```(?:(\w+)\n)?([\s\S]*?)```/);
          if (match1) {
              const language = match1[1] || '';
              const code = match1[2];
              return formatCodeBlock(language, code);
          }
          return match;
      });
      
      // Add target="_blank" to all external links
      html = html.replace(/<a href="(https?:\/\/[^"]+)">/g, '<a href="$1" target="_blank" rel="noopener noreferrer">');
      
      return html;
  }
  
  /**
   * Custom markdown parser as a fallback when micromark is unavailable
   * Enhanced for CDISC-specific formatting and better handling of complex markdown
   */
  function customMarkdownParser(content) {
      let html = '';
      const lines = content.split('\n');
      let i = 0;
      let inList = false;
      let inOrderedList = false;
      let inBlockquote = false;
      let inTable = false;
      let tableHeaders = [];
      let tableAlignments = [];
      
      while (i < lines.length) {
          const line = lines[i].trim();
          
          // Skip empty placeholder lines for code blocks (they'll be restored later)
          if (line.match(/^__CODE_BLOCK_\d+__$/)) {
              html += line;
              i++;
              continue;
          }
          
          // Headers
          if (line.startsWith('#')) {
              // Close any open structures before a heading
              if (inList) {
                  html += inOrderedList ? '</ol>' : '</ul>';
                  inList = false;
                  inOrderedList = false;
              }
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              const match = line.match(/^(#{1,6})\s+(.+)$/);
              if (match) {
                  const level = match[1].length;
                  const text = match[2];
                  const formattedText = processInlineFormatting(text);
                  html += `<h${level} style="margin: 0.7em 0 0.3em 0; font-weight: 600; color: #1f2328;">${formattedText}</h${level}>`;
              }
          }
          // Horizontal rule
          else if (line.match(/^(\*{3,}|-{3,}|_{3,})$/)) {
              // Close any open structures
              if (inList) {
                  html += inOrderedList ? '</ol>' : '</ul>';
                  inList = false;
                  inOrderedList = false;
              }
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              html += '<hr style="height: 0.25em; padding: 0; margin: 1.5em 0; background-color: #d0d7de; border: 0; border-radius: 2px;">';
          }
          // Table - header row (starts with | and contains |)
          else if (line.startsWith('|') && line.endsWith('|') && line.includes('|', 1)) {
              // Close any open structures before starting a table
              if (inList) {
                  html += inOrderedList ? '</ol>' : '</ul>';
                  inList = false;
                  inOrderedList = false;
              }
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              
              // Start a new table if we're not in one already
              if (!inTable) {
                  html += '<table style="border-collapse: collapse; margin: 1em 0; width: 100%; overflow: auto; font-size: 0.9em; border-radius: 6px; box-shadow: 0 0 0 1px #d0d7de;">';
                  inTable = true;
                  
                  // Process the header row
                  const headerCells = line.slice(1, -1).split('|').map(cell => cell.trim());
                  tableHeaders = headerCells;
                  
                  // Check if the next line is a separator row with dashes
                  if (i + 1 < lines.length && lines[i + 1].trim().startsWith('|') && 
                      lines[i + 1].trim().includes('-')) {
                      
                      // Get alignment from separator row
                      const alignmentRow = lines[i + 1].trim().slice(1, -1).split('|');
                      tableAlignments = alignmentRow.map(cell => {
                          const trimmed = cell.trim();
                          if (trimmed.startsWith(':') && trimmed.endsWith(':')) return 'center';
                          if (trimmed.endsWith(':')) return 'right';
                          return 'left';
                      });
                      
                      // Skip the separator row
                      i++;
                  } else {
                      // Default alignment to left if no separator row
                      tableAlignments = Array(headerCells.length).fill('left');
                  }
                  
                  // Add table header
                  html += '<thead><tr>';
                  for (let j = 0; j < tableHeaders.length; j++) {
                      const align = tableAlignments[j] || 'left';
                      const formattedCell = processInlineFormatting(tableHeaders[j]);
                      html += `<th style="padding: 6px 13px; border: 1px solid #d0d7de; text-align: ${align}; font-weight: 600; background-color: #f6f8fa;">${formattedCell}</th>`;
                  }
                  html += '</tr></thead><tbody>';
              } else {
                  // Process a regular table row
                  const cells = line.slice(1, -1).split('|').map(cell => cell.trim());
                  html += '<tr>';
                  for (let j = 0; j < cells.length; j++) {
                      const align = tableAlignments[j] || 'left';
                      const formattedCell = processInlineFormatting(cells[j]);
                      html += `<td style="padding: 6px 13px; border: 1px solid #d0d7de; text-align: ${align};">${formattedCell}</td>`;
                  }
                  html += '</tr>';
              }
          }
          // Ordered list items - match numbers like 1. or 1)
          else if (line.match(/^\s*\d+[.)]\s/)) {
              // Close blockquote or table if open
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              // If we're in a list already but with different type
              if (inList && !inOrderedList) {
                  html += '</ul>';
                  inList = false;
              }
              
              // Start a new ordered list
              if (!inList) {
                  html += '<ol style="margin: 0.5em 0; padding-left: 1.5em;">';
                  inList = true;
                  inOrderedList = true;
              }
              
              const text = line.replace(/^\s*\d+[.)]\s/, '');
              const formattedText = processInlineFormatting(text);
              html += `<li style="margin-bottom: 0.3em;">${formattedText}</li>`;
              
              // Check if we should end the list
              if (i === lines.length - 1 || 
                  !lines[i+1].trim().match(/^\s*\d+[.)]\s/) && 
                  !lines[i+1].trim().match(/^\s*[-*+]\s/)) {
                  html += '</ol>';
                  inList = false;
                  inOrderedList = false;
              }
          }
          // Unordered list items
          else if (line.match(/^\s*[-*+]\s/)) {
              // Close blockquote or table if open
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              // If we're in a list already but with different type
              if (inList && inOrderedList) {
                  html += '</ol>';
                  inList = false;
              }
              
              // Start a new unordered list
              if (!inList) {
                  html += '<ul style="margin: 0.5em 0; padding-left: 1.5em;">';
                  inList = true;
                  inOrderedList = false;
              }
              
              const text = line.replace(/^\s*[-*+]\s/, '');
              const formattedText = processInlineFormatting(text);
              html += `<li style="margin-bottom: 0.3em;">${formattedText}</li>`;
              
              // Check if we should end the list
              if (i === lines.length - 1 || 
                  !lines[i+1].trim().match(/^\s*[-*+]\s/) && 
                  !lines[i+1].trim().match(/^\s*\d+[.)]\s/)) {
                  html += '</ul>';
                  inList = false;
              }
          }
          // Blockquote
          else if (line.startsWith('>')) {
              // Close any open structures except blockquotes
              if (inList) {
                  html += inOrderedList ? '</ol>' : '</ul>';
                  inList = false;
                  inOrderedList = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              // Start a new blockquote if needed
              if (!inBlockquote) {
                  html += '<blockquote style="padding: 0.5em 1em; color: #57606a; background-color: #f6f8fa; border-left: 0.25em solid #d0d7de; margin: 1em 0; border-radius: 0 3px 3px 0;">';
                  inBlockquote = true;
              }
              
              const text = line.substring(1).trim();
              const formattedText = processInlineFormatting(text);
              
              // Add paragraph inside blockquote
              html += `<p style="margin: 0.4em 0;">${formattedText}</p>`;
              
              // Check if we should end the blockquote
              if (i === lines.length - 1 || !lines[i+1].trim().startsWith('>')) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
          }
          // CDISC-specific special sections - start with !!! and contain info, warning, etc.
          else if (line.match(/^!{3}\s*(info|warning|success|error|note)/i)) {
              // Close any open structures
              if (inList) {
                  html += inOrderedList ? '</ol>' : '</ul>';
                  inList = false;
                  inOrderedList = false;
              }
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              const match = line.match(/^!{3}\s*(info|warning|success|error|note)/i);
              const boxType = match[1].toLowerCase();
              
              // Determine style based on box type
              let boxStyle, boxTitle;
              switch (boxType) {
                  case 'info':
                      boxStyle = 'background-color: #f6f8fa; border-left-color: #0969da;';
                      boxTitle = 'Information';
                      break;
                  case 'warning':
                      boxStyle = 'background-color: #fff8c5; border-left-color: #e36209;';
                      boxTitle = 'Warning';
                      break;
                  case 'success':
                      boxStyle = 'background-color: #dafbe1; border-left-color: #2da44e;';
                      boxTitle = 'Success';
                      break;
                  case 'error':
                      boxStyle = 'background-color: #ffebe9; border-left-color: #cf222e;';
                      boxTitle = 'Error';
                      break;
                  case 'note':
                  default:
                      boxStyle = 'background-color: #f6f9fc; border-left-color: #6b7f99;';
                      boxTitle = 'Note';
              }
              
              // Extract custom title if provided after the box type (e.g., !!! info: Custom Title)
              const titleMatch = line.match(/^!{3}\s*[a-z]+:(.+)$/i);
              if (titleMatch && titleMatch[1].trim()) {
                  boxTitle = titleMatch[1].trim();
              }
              
              // Start box with the title
              html += `<div class="${boxType}-box" style="padding: 12px 16px; margin: 1em 0; border-radius: 6px; border-left: 4px solid; ${boxStyle}">`;
              html += `<strong>${boxTitle}</strong>`;
              
              // Look ahead for content indented under this box
              let j = i + 1;
              while (j < lines.length && (lines[j].trim() === '' || lines[j].match(/^\s+/))) {
                  if (lines[j].trim() !== '') {
                      const boxContent = lines[j].trim();
                      const formattedBoxContent = processInlineFormatting(boxContent);
                      html += `<p style="margin: 0.4em 0;">${formattedBoxContent}</p>`;
                  }
                  j++;
              }
              
              // Close the box
              html += '</div>';
              
              // Skip the processed lines
              i = j - 1;
          }
          // Paragraphs (non-empty lines)
          else if (line !== '') {
              // Close any open structures before starting a paragraph
              if (inList) {
                  html += inOrderedList ? '</ol>' : '</ul>';
                  inList = false;
                  inOrderedList = false;
              }
              if (inBlockquote) {
                  html += '</blockquote>';
                  inBlockquote = false;
              }
              if (inTable) {
                  html += '</tbody></table>';
                  inTable = false;
              }
              
              // Process inline formatting in paragraphs
              const formattedText = processInlineFormatting(line);
              html += `<p style="margin: 0.5em 0; line-height: 1.5;">${formattedText}</p>`;
          }
          // Empty lines - add spacing unless in certain structures
          else if (!inList && !inBlockquote && !inTable) {
              html += '<div style="height: 0.5em;"></div>';
          }
          
          i++;
      }
      
      // Close any open structures at the end
      if (inList) {
          html += inOrderedList ? '</ol>' : '</ul>';
      }
      if (inBlockquote) {
          html += '</blockquote>';
      }
      if (inTable) {
          html += '</tbody></table>';
      }
      
      return html;
  }
  
  /**
   * Process inline formatting (bold, italic, code, links) with CDISC-specific enhancements
   */
  function processInlineFormatting(text) {
      if (!text) return '';
      
      // Process links first - [text](url)
      text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      
      // CDISC-specific formatting - highlight domain codes (standard CDISC domains)
      // Don't match inside code blocks or already processed elements
      text = text.replace(/\b([A-Z]{2,4})\b(?![^<]*>)/g, (match, domain) => {
          // Official CDISC domains (SDTM + ADaM)
          const cdiscDomains = [
              // SDTM Study Data Domains
              "DM", "AE", "CM", "EX", "LB", "VS", "MH", "DS", "SV", "SE", "TS", 
              "RS", "TU", "TR", "EC", "SU", "RE", "PC", "PP", "MI", "SC", "FA", 
              "IS", "QS", "FT", "RP", "DV", "CO", "PR", "DD", "CE", "DI", "AG",
              // SDTM Special-Purpose Domains
              "TA", "TE", "TV", "TI", "TD", "TJ", "TX", "MS", "NS", "SM", "SS", "SR",
              // ADaM Standard Domains
              "ADSL", "ADAE", "ADCM", "ADLB", "ADVS", "ADEX", "ADEG", "ADMH", "ADRS", 
              "ADPR", "ADPC", "ADPP", "ADQS", "ADTR", "ADTTE", "ADCE", "ADHY", "ADLBHY", 
              "ADQLQC", "ADIS", "ADQSADAS", "ADQLQCCIBIC"
          ];
          
          if (cdiscDomains.includes(domain)) {
              return `<span class="cdisc-domain">${domain}</span>`;
          }
          return match;
      });
      
      // CDISC-specific formatting - highlight CORE variables from CDISC standards
      text = text.replace(/\b([A-Z]{2,8}(?:ID|DTC|STRT|END|DY|FL|SEQ|TERM|DECOD|CAT|BODSYS|SCAT|SPID|NAM|SPEC|REAS|REASND|LNKID|DSDECOD|VISIT|TEST|TESTCD|STRES|STRESC|ORRES|ORRESU))\b(?![^<]*>)/g, 
          '<span class="cdisc-variable">$1</span>');
          
      // Special highlighting for highly important CORE identifiers
      text = text.replace(/\b(STUDYID|USUBJID|SUBJID|DOMAIN|DTHDTC|DTHFL|SITEID|VISITNUM|EPOCH|ARM|ARMCD|ACTARM|ACTARMCD|SPDEVID|LBSEQ|LBTESTCD|LBTEST|LBCAT|LBORRES|LBORRESU|LBORNRLO|LBORNRHI|LBSTRESC|LBSTRESN|LBSTRESU|LBSTNRLO|LBSTNRHI|VISIT|VISITNUM|AEDECOD|AESTDTC|AEENDTC|AETERM|AESEV|AESER|AESDTH)\b(?![^<]*>)/g,
          '<span class="cdisc-variable" style="font-weight:bold;">$1</span>');
      
      // Process code before bold/italic to avoid interference
      text = text.replace(/`([^`]+)`/g, '<code class="md-inline-code" style="background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px; font-family: monospace;">$1</code>');
      
      // Handle bold and italic combinations carefully
      // First handle bold+italic
      text = text.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
      text = text.replace(/___([^_]+)___/g, '<strong><em>$1</em></strong>');
      
      // Then handle bold
      text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      text = text.replace(/__([^_]+)__/g, '<strong>$1</strong>');
      
      // Then handle italic
      text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      text = text.replace(/_([^_]+)_/g, '<em>$1</em>');
      
      return text;
  }
  
  function updateMessage(id, content) {
      console.time('updateMessage');
      const messages = document.querySelectorAll('.assistant-message');
      let found = false;
      
      // Ensure content is a string
      if (typeof content !== 'string') {
          console.warn('Non-string content received:', content);
          try {
              if (content === null || content === undefined) {
                  content = '';
              } else if (typeof content === 'object') {
                  content = JSON.stringify(content, null, 2);
              } else {
                  content = String(content);
              }
          } catch (e) {
              console.error('Error converting content to string:', e);
              content = 'Error: Unable to display content';
          }
      }
      
      for (const message of messages) {
          if (message.dataset.id === id) {
              try {
                  // Apply our simplified formatter
                  message.innerHTML = formatContent(content);
                  
                  // Apply code highlighting
                  message.querySelectorAll('pre code').forEach(block => {
                      if (!block.classList.contains('highlighted')) {
                          hljs.highlightElement(block);
                          block.classList.add('highlighted');
                      }
                  });
                  
                  // Add copy functionality
                  message.querySelectorAll('.copy-btn').forEach(btn => {
                      if (!btn.hasAttribute('listener-added')) {
                          btn.setAttribute('listener-added', 'true');
                          btn.addEventListener('click', function() {
                              // Find pre and code elements relative to the current button
                              const codeContainer = this.closest('div');
                              const codeElement = codeContainer.querySelector('pre code');
                              if (codeElement) {
                                  navigator.clipboard.writeText(codeElement.textContent);
                                  
                                  // Visual feedback
                                  const originalText = this.textContent;
                                  this.textContent = 'Copied!';
                                  setTimeout(() => {
                                      this.textContent = originalText;
                                  }, 1500);
                              }
                          });
                      }
                  });
                  
                  messagesContainer.scrollTop = messagesContainer.scrollHeight;
              } catch (e) {
                  console.error('Error formatting message:', e);
                  // Fallback to basic formatting
                  message.textContent = content;
                  message.innerHTML = message.innerHTML.replace(/\n/g, '<br>');
              }
              
              found = true;
              console.timeEnd('updateMessage');
              break;
          }
      }
      
      if (!found) {
          console.error('Could not find message with ID:', id);
          appendMessage('Assistant', content, 'assistant-message');
      }
  }
  
  /**
   * Format all existing messages in the chat history when the page loads
   */
  function formatMessagesOnLoad() {
    console.log('Formatting all messages on page load');
    
    // 1. Process any user messages - simple formatting
    const userMessages = document.querySelectorAll('.user-message');
    userMessages.forEach(message => {
      try {
        const rawContent = message.textContent.trim();
        // Basic line break formatting for user messages
        message.innerHTML = rawContent.replace(/\n/g, '<br>');
      } catch (e) {
        console.error('Error formatting user message:', e);
      }
    });
    
    // 2. Process all assistant messages - full markdown and code formatting
    const assistantMessages = document.querySelectorAll('.assistant-message');
    console.log('Found assistant messages:', assistantMessages.length);
    
    // Process each assistant message
    assistantMessages.forEach(message => {
      try {
        // Get the raw content
        const rawContent = message.textContent.trim();
        if (!rawContent) return;
        
        console.log('Processing message with content length:', rawContent.length);
        
        // Skip "Processing..." message
        if (rawContent === 'Processing...') return;
        
        // Apply our markdown renderer - always reapply on page load
        message.innerHTML = formatContent(rawContent);
        
        // Apply code highlighting
        message.querySelectorAll('pre code').forEach(block => {
          try {
            hljs.highlightElement(block);
            block.classList.add('highlighted');
          } catch (err) {
            console.error('Error highlighting code:', err);
          }
        });
        
        // Add copy functionality to code blocks
        message.querySelectorAll('.copy-btn').forEach(btn => {
          if (!btn.hasAttribute('listener-added')) {
            btn.setAttribute('listener-added', 'true');
            btn.addEventListener('click', function() {
              const codeBlock = this.closest('.code-block');
              const codeElement = codeBlock?.querySelector('pre code');
              if (codeElement) {
                navigator.clipboard.writeText(codeElement.textContent)
                  .then(() => {
                    // Visual feedback
                    const originalText = this.textContent;
                    this.textContent = 'Copied!';
                    this.style.backgroundColor = '#4caf50';
                    this.style.color = 'white';
                    
                    setTimeout(() => {
                      this.textContent = originalText;
                      this.style.backgroundColor = '';
                      this.style.color = '#2563eb';
                    }, 1500);
                  })
                  .catch(err => {
                    console.error('Failed to copy:', err);
                  });
              }
            });
          }
        });
      } catch (e) {
        console.error('Error formatting assistant message:', e);
      }
    });
  }
  
  /**
   * Format all existing messages when the page loads
   * Backwards compatibility function
   */
  function formatExistingMessages() {
    formatMessagesOnLoad();
  }
  
  /**
   * Format a code block with modern styling, syntax highlighting, and copy functionality
   */
  function formatCodeBlock(language, code) {
      // Normalize language and set defaults
      language = (language || '').toLowerCase().trim();
      
      // Map common languages to highlight.js supported languages
      const languageMap = {
          'sql': 'sql',
          'python': 'python',
          'py': 'python',
          'r': 'r',
          'plaintext': 'plaintext',
          'text': 'plaintext',
          'js': 'javascript',
          'javascript': 'javascript',
          'bash': 'bash',
          'sh': 'bash',
          'json': 'json',
          'csv': 'plaintext',
          'yaml': 'yaml',
          'yml': 'yaml',
          'xml': 'xml',
          'html': 'html',
          'css': 'css',
          'cdisc': 'plaintext', // Custom CDISC format
          'sas': 'plaintext',   // For SAS code
          '': 'plaintext'       // Default
      };
      
      // Use mapped language or fallback to plaintext
      const hlLanguage = languageMap[language] || 'plaintext';
      
      // Trim trailing whitespace and remove excessive blank lines
      code = code.trim().replace(/\n{3,}/g, '\n\n');
      
      // Sanitize the code content
      const sanitizedCode = code
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#039;");
          
      // Determine what icon to show based on language
      let langIcon = '';
      
      if (language === 'sql') {
          langIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 5px;"><path d="M12 2L22 8.5V15.5L12 22L2 15.5V8.5L12 2Z"></path><path d="M12 22V15.5"></path><path d="M22 8.5L12 15.5L2 8.5"></path><path d="M2 15.5L12 8.5L22 15.5"></path><path d="M12 2V8.5"></path></svg>';
      } else if (language === 'python' || language === 'py') {
          langIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 5px;"><path d="M12 2v6.5M12 22v-6.5"></path><path d="M6 8.5h12l-3 5.5"></path><path d="M16.5 10.5l1 2-4 6.5"></path><path d="M6 17l3.5-6"></path><circle cx="12" cy="8.5" r="6.5"></circle></svg>';
      } else if (language === 'r') {
          langIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 5px;"><path d="M4 10h16v4H4z"></path><path d="M16 14l4 6"></path><path d="M8 21h8"></path><path d="M12 3v18"></path><path d="M3 9a9 9 0 0 1 9-9 9 9 0 0 1 9 9"></path></svg>';
      } else if (language === 'bash' || language === 'sh') {
          langIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 5px;"><rect x="2" y="4" width="20" height="16" rx="2"></rect><path d="m8 10-2 2 2 2"></path><path d="M11 13h5"></path></svg>';
      } else {
          langIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 5px;"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>';
      }
      
      // Create a clean, highly legible code block
      return `<div class="code-block" style="margin: 1.2em 0; border: 1px solid #d1d5db; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,0.07);">
          <div style="background-color: #f8f9fa; padding: 8px 12px; border-bottom: 1px solid #e5e7eb; display: flex; justify-content: space-between; align-items: center;">
              <div style="display: flex; align-items: center;">
                  ${langIcon}
                  <span style="font-weight: 500; font-size: 13px; color: #374151;">${language.toUpperCase() || 'CODE'}</span>
              </div>
              <button class="copy-btn" style="border: 1px solid #e5e7eb; background-color: white; cursor: pointer; color: #2563eb; font-size: 12px; display: flex; align-items: center; padding: 3px 8px; border-radius: 4px; transition: all 0.2s;">
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                  </svg>
                  Copy
              </button>
          </div>
          <pre style="margin: 0; padding: 16px; max-height: 400px; overflow: auto; font-size: 14px; line-height: 1.6; background-color: #ffffff; font-family: 'Consolas', 'Monaco', 'Courier New', monospace;"><code class="${hlLanguage}">${sanitizedCode}</code></pre>
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

      // Process domain variables for tooltip display with CDISC standard emphasis
      function formatVariables(varsString) {
          const varsList = varsString.split(', ');
          let varHtml = '';
          
          // List of REQUIRED variables by CDISC standards
          const coreVariables = [
              // General identifiers required in all domains
              "STUDYID", "DOMAIN", "USUBJID", "SUBJID", 
              
              // Demographics core variables
              "SITEID", "AGE", "SEX", "RACE", "ETHNIC", "COUNTRY", "DMDTC", "ARMCD", "ARM", 
              
              // AE core variables
              "AESEQ", "AETERM", "AEDECOD", "AESTDTC", "AEENDTC", "AESEV", "AESER", "AESOC", "AEACN",
              
              // LB core variables
              "LBSEQ", "LBTESTCD", "LBTEST", "LBCAT", "LBDTC", "LBORRES", "LBORRESU", "LBORNRLO", "LBORNRHI",
              
              // Other common core variables
              "VISIT", "VISITNUM", "EPOCH",
              
              // ADaM core variables
              "PARAMCD", "PARAM", "AVAL", "AVALC", "VISIT", "AVISIT", "AVISITN", "DTYPE", "TRTP", "TRTPN"
          ];
          
          // Format each variable with special emphasis on CORE variables
          varsList.forEach(variable => {
              const trimmedVar = variable.trim();
              if (coreVariables.includes(trimmedVar)) {
                  // CORE variable formatting
                  varHtml += `<span class="cdisc-core-var" title="CORE variable (required)">${trimmedVar}</span>`;
              } else {
                  // Regular variable formatting
                  varHtml += `<span>${trimmedVar}</span>`;
              }
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
                          const messagesContainer = document.querySelector('.messages');
                          messagesContainer.innerHTML = data.welcome_html;
                          
                          // Re-bind the example query click handlers
                          messagesContainer.querySelectorAll('.example-query').forEach(example => {
                              example.addEventListener('click', function() {
                                  document.getElementById('message-input').value = this.textContent.replace(/^\"|\"$/g, '');
                              });
                          });
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
                      alert('Error clearing chat context: ' + data.message);
                  }
              })
              .catch(error => {
                  console.error('Error clearing context:', error);
                  alert('Error clearing chat context. Please try again.');
              });
          }
      });
  }

  // Initialize the new tooltip and interactions here
  setupDomainInteractions();
  
  // Add event listener for clear chat button
  const clearChatBtn = document.getElementById('clear-chat-btn');
  if (clearChatBtn) {
      clearChatBtn.addEventListener('click', clearChatHistory);
  }

  // File upload handling
  document.getElementById('file-upload').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    // Show upload progress
    const uploadBanner = document.getElementById('upload-banner');
    uploadBanner.style.display = 'block';
    uploadBanner.style.backgroundColor = '#1a73e8';
    uploadBanner.textContent = 'Uploading file...';

    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Show success message
            uploadBanner.style.backgroundColor = '#4caf50';
            uploadBanner.textContent = data.message;

            // Add the new file to the list
            const filesList = document.getElementById('filesList');
            const filesPlaceholder = document.getElementById('filesPlaceholder');
            
            if (filesPlaceholder) {
                filesPlaceholder.remove();
            }

            const fileEntry = document.createElement('div');
            fileEntry.className = 'file-entry';
            fileEntry.innerHTML = `
                <div class="file-info">
                    <span class="file-name">${data.fileInfo.name}</span>
                    <span class="file-type">${data.fileInfo.type}</span>
                </div>
            `;
            filesList.appendChild(fileEntry);

            // Clear the file input
            e.target.value = '';

            // Hide the banner after 3 seconds
            setTimeout(() => {
                uploadBanner.style.display = 'none';
            }, 3000);
        } else {
            // Show error message
            uploadBanner.style.backgroundColor = '#e53935';
            uploadBanner.textContent = data.message;

            // Hide the banner after 5 seconds
            setTimeout(() => {
                uploadBanner.style.display = 'none';
            }, 5000);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        uploadBanner.style.backgroundColor = '#e53935';
        uploadBanner.textContent = 'Error uploading file. Please try again.';

        // Hide the banner after 5 seconds
        setTimeout(() => {
            uploadBanner.style.display = 'none';
        }, 5000);
    });
  });
});

// Function to handle clearing chat history
async function clearChatHistory() {
    try {
        const response = await fetch('/clear_chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        if (data.success) {
            const messagesContainer = document.querySelector('.messages');
            
            // Use welcome HTML from server if available
            if (data.welcome_html) {
                messagesContainer.innerHTML = data.welcome_html;
            } else {
                // Fallback welcome message
                messagesContainer.innerHTML = `
                    <div class="welcome-message">
                        <h3>Welcome to the CDISC Standards Assistant</h3>
                        <p>Chat history has been cleared. You can start a new conversation.</p>
                        <div class="example-queries">
                            <div class="example-query" id="ex-1">"Tell me about the DM domain structure and purpose"</div>
                            <div class="example-query" id="ex-2">"Explain the key variables in the ADSL domain"</div>
                            <div class="example-query" id="ex-3">"Generate code to map lab data to SDTM LB domain with explanation"</div>
                        </div>
                    </div>
                `;
            }
            
            // Re-bind example query click handlers
            document.querySelectorAll('.example-query').forEach(example => {
                example.addEventListener('click', function() {
                    document.getElementById('message-input').value = this.textContent.replace(/^\"|\"$/g, '');
                });
            });
            
            // Clear the input field
            document.getElementById('message-input').value = '';
            
            // Show success message
            const banner = document.getElementById('upload-banner');
            banner.textContent = 'Chat history cleared successfully';
            banner.style.backgroundColor = '#4caf50';
            banner.style.display = 'block';
            setTimeout(() => {
                banner.style.display = 'none';
            }, 3000);
        } else {
            throw new Error(data.message || 'Failed to clear chat history');
        }
    } catch (error) {
        console.error('Error clearing chat history:', error);
        const banner = document.getElementById('upload-banner');
        banner.textContent = 'Failed to clear chat history. Please try again.';
        banner.style.backgroundColor = '#f44336';
        banner.style.display = 'block';
        setTimeout(() => {
            banner.style.display = 'none';
        }, 3000);
    }
}

// Add this function to handle chat clearing
async function clearChat() {
    try {
        const response = await fetch('/clear_chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        if (data.success) {
            const messagesContainer = document.querySelector('.messages');
            // Use welcome HTML from server if available
            if (data.welcome_html) {
                messagesContainer.innerHTML = data.welcome_html;
            } else {
                messagesContainer.innerHTML = `
                    <div class="welcome-message">
                        <h3>Welcome to the CDISC Standards Assistant</h3>
                        <p>I can help you with:</p>
                        <ul>
                            <li>Converting source data into SDTM/ADaM standards</li>
                            <li>Creating dbt models and SQL transformations for clinical data</li>
                            <li>Implementing RECIST criteria and oncology-specific analyses</li>
                            <li>Designing ADaM datasets for efficacy and safety analysis</li>
                        </ul>
                        <div class="example-queries">
                            <div class="example-query">"Tell me about the DM domain structure and purpose"</div>
                            <div class="example-query">"Explain the key variables in the ADSL domain"</div>
                            <div class="example-query">"Generate code to map lab data to SDTM LB domain with explanation"</div>
                        </div>
                        <p class="prompt-tip">For best results, ask for explanations about domains before requesting code.</p>
                    </div>
                `;
            }
            
            // Re-bind example query click handlers
            bindExampleQueryHandlers();
            
            // Clear the input field
            document.getElementById('message-input').value = '';
            
        } else {
            console.error('Failed to clear chat history:', data.message);
        }
    } catch (error) {
        console.error('Error clearing chat history:', error);
    }
}

// Helper function to bind example query handlers
function bindExampleQueryHandlers() {
    document.querySelectorAll('.example-query').forEach(example => {
        example.addEventListener('click', function() {
            document.getElementById('message-input').value = this.textContent.replace(/^\"|\"$/g, '');
        });
    });
}

// Add this event listener when the document loads
document.addEventListener('DOMContentLoaded', function() {
    // ...existing code...
    
    // Set up clear chat button handler
    const clearChatBtn = document.getElementById('clear-chat-btn');
    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', clearChat);
    }
    
    // Initial binding of example query handlers
    bindExampleQueryHandlers();
});