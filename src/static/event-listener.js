document.addEventListener("DOMContentLoaded", function() {
    // File upload handling
    document.getElementById("file-upload").addEventListener("change", function (event) {
        const file = event.target.files[0];
        if (!file) {
            return;
        }
        
        // Show loading state
        const banner = document.getElementById("upload-banner");
        banner.textContent = "Uploading file...";
        banner.style.display = "block";
        banner.style.backgroundColor = "#1a73e8";
        
        const formData = new FormData();
        formData.append("file", file);

        fetch("/upload", {
            method: "POST",
            body: formData,
        })
        .then((response) => response.json())
        .then((data) => {
            if (data.success) {
                // Update banner with success message
                banner.textContent = data.message;
                banner.style.backgroundColor = "#4caf50";
                
                // If it's an EDC or SDTM file, add a special indication
                if (data.filename.toLowerCase().includes("edc") || 
                    data.filename.toLowerCase().includes("sdtm")) {
                    banner.textContent += " - Ready for enhanced chat context!";
                }

                // Hide the banner after 3 seconds
                setTimeout(() => {
                    banner.style.display = "none";
                }, 3000);

                // Reset the file input to allow selecting the same file again
                document.getElementById("file-upload").value = "";

                // Update file list
                fetch("/get_files")
                    .then((response) => response.json())
                    .then((data) => {
                        populateFiles(data.assistant_files);
                    })
                    .catch(error => {
                        console.error("Error fetching updated file list:", error);
                    });
            } else {
                console.error("Upload failed:", data.message);
                // Update banner with error message
                banner.textContent = data.message;
                banner.style.backgroundColor = "#f44336";
                banner.style.color = "white";

                // Hide the banner after 4 seconds
                setTimeout(() => {
                    banner.style.display = "none";
                }, 4000);
                
                // Reset the file input
                document.getElementById("file-upload").value = "";
            }
        })
        .catch((error) => {
            console.error("Error uploading file:", error);
            banner.textContent = "Error uploading file. Please try again.";
            banner.style.backgroundColor = "#f44336";
            banner.style.color = "white";
            
            setTimeout(() => {
                banner.style.display = "none";
            }, 4000);
            
            // Reset the file input
            document.getElementById("file-upload").value = "";
        });
    });

    // Clear chat history handling
    document.getElementById('clear-chat-btn')?.addEventListener('click', function() {
        fetch('/clear_chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin'
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const messagesContainer = document.querySelector('.messages');
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
                            <p>Try asking:</p>
                            <div class="example-queries">
                                <div class="example-query" id="ex-1">"Tell me about the DM domain structure and purpose"</div>
                                <div class="example-query" id="ex-2">"Explain the key variables in the ADSL domain"</div>
                                <div class="example-query" id="ex-3">"Generate code to map lab data to SDTM LB domain with explanation"</div>
                            </div>
                            <p class="prompt-tip">For best results, ask for explanations about domains before requesting code.</p>
                        </div>
                    `;
                }

                // Re-bind example query click handlers
                document.querySelectorAll('.example-query').forEach(example => {
                    example.addEventListener('click', function() {
                        document.getElementById('message-input').value = this.textContent.replace(/^\"|\"$/g, '');
                    });
                });

                // Show success message
                const banner = document.getElementById("upload-banner");
                banner.textContent = "Chat history cleared successfully!";
                banner.style.backgroundColor = "#4caf50";
                banner.style.display = "block";

                setTimeout(() => {
                    banner.style.display = "none";
                }, 3000);
            } else {
                console.error('Failed to clear chat history:', data.message);
                const banner = document.getElementById("upload-banner");
                banner.textContent = "Failed to clear chat history. Please try again.";
                banner.style.backgroundColor = "#f44336";
                banner.style.display = "block";

                setTimeout(() => {
                    banner.style.display = "none";
                }, 4000);
            }
        })
        .catch(error => {
            console.error('Error clearing chat history:', error);
            const banner = document.getElementById("upload-banner");
            banner.textContent = "Error clearing chat history. Please try again.";
            banner.style.backgroundColor = "#f44336";
            banner.style.display = "block";

            setTimeout(() => {
                banner.style.display = "none";
            }, 4000);
        });
    });
});