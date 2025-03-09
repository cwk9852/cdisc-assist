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