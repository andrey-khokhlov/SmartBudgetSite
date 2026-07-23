document.addEventListener("DOMContentLoaded", () => {
    const texts = window.feedbackTexts;

    const form = document.getElementById("feedback-form");
    const status = document.getElementById("feedback-status");

    const typeSelect = document.getElementById("message_type");
    const nameInput = document.getElementById("name");
    const emailInput = document.getElementById("email");
    const emailLabel = document.querySelector('label[for="email"]');
    const emailHint = document.getElementById("email-hint");

    const purchaseStatus = document.getElementById("purchase-status");
    const purchaseSelectorGroup = document.getElementById("purchaseSelectorGroup");
    const purchaseSelect = document.getElementById("purchase_select");
    const supportReferenceGroup = document.getElementById("supportReferenceGroup");
    const supportReferenceInput = document.getElementById("support_reference");

    const subjectGroup = document.getElementById("subjectGroup");
    const messageGroup = document.getElementById("messageGroup");

    const submitButton = form.querySelector('button[type="submit"]');

    const messageInput = document.getElementById("message");
    const messageCounter = document.getElementById("messageCounter");

    const subjectInput = document.getElementById("subject");
    const attachmentsGroup = document.getElementById("attachmentsGroup");

    const attachmentsInput = document.getElementById("attachments");
    const selectedFilesText = document.getElementById("selectedFilesText");

    const feedbackDropzone = document.getElementById("feedbackDropzone");

    function clearPurchaseSelection() {
        purchaseSelect.replaceChildren();

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = texts.purchasePlaceholder;
        purchaseSelect.appendChild(placeholder);

        purchaseSelect.value = "";
        purchaseSelect.disabled = true;
        purchaseSelect.required = false;
        purchaseSelectorGroup.style.display = "none";
    }

    function setPurchaseSelection(purchases) {
        clearPurchaseSelection();

        purchases.forEach((purchase) => {
            const option = document.createElement("option");
            option.value = purchase.purchase_reference;
            option.textContent = `${purchase.product_name} — ${purchase.edition}`;
            purchaseSelect.appendChild(option);
        });

        purchaseSelect.disabled = false;

        if (purchases.length === 1) {
            purchaseSelect.value = purchases[0].purchase_reference;
            return;
        }

        purchaseSelect.required = true;
        purchaseSelectorGroup.style.display = "block";
    }

    function updateSupportReferenceState() {
        if (!supportReferenceGroup || !supportReferenceInput) {
            return;
        }

        const shouldIncludeReference =
            typeSelect.value === "purchase_or_download_issue" &&
            supportReferenceInput.value !== "";

        supportReferenceGroup.style.display = shouldIncludeReference ? "block" : "none";
        supportReferenceInput.disabled = !shouldIncludeReference;
    }

    function updateMessageCounter() {
        if (!messageInput || !messageCounter) {
            return;
        }

        messageCounter.textContent =
            `${messageInput.value.length} / ${messageInput.maxLength}`;
    }

    function resetAfterSuccessfulSubmission() {
        typeSelect.value = "site_issue";
        Array.from(typeSelect.options).forEach((option) => {
            option.defaultSelected = option.value === "site_issue";
        });

        [nameInput, emailInput, subjectInput, messageInput].forEach((input) => {
            input.value = "";
            input.defaultValue = "";
        });

        if (supportReferenceInput) {
            supportReferenceInput.value = "";
            supportReferenceInput.defaultValue = "";
        }

        attachmentsInput.value = "";
        form.page_url.value = window.location.pathname;

        selectedFilesText.textContent = texts.noFiles || "No files selected";
        feedbackDropzone.classList.remove("is-dragover");

        purchaseStatus.style.display = "none";
        purchaseStatus.textContent = "";
        purchaseStatus.className = "feedback-purchase-status";
        clearPurchaseSelection();

        updateSupportReferenceState();
        updateFormVisibility(true);
        updateEmailVisibility();
        updateMessageCounter();
        updateSubmitState();
    }

    function updateEmailVisibility() {
        const type = typeSelect.value;

        if (type === "product_feedback") {
            emailLabel.style.display = "block";
            emailInput.style.display = "block";
            emailHint.style.display = "block";
            emailHint.textContent = texts.productEmailHint;
            emailInput.required = true;
        } else {
            emailLabel.style.display = "block";
            emailInput.style.display = "block";
            emailHint.style.display = "block";
            emailHint.textContent = texts.contactEmailHint;
            emailInput.required = false;
        }
    }

    function updateSubmitState() {
        const type = typeSelect.value;

        if (type !== "product_feedback") {
            submitButton.disabled = false;
            return;
        }

        const hasVerifiedPurchase =
            purchaseStatus.classList.contains("success") &&
            purchaseSelect.value !== "";

        submitButton.disabled = !hasVerifiedPurchase;
    }

    function updateFormVisibility(isVisible) {
        if (isVisible) {
            subjectGroup.style.display = "block";
            messageGroup.style.display = "block";
            attachmentsGroup.style.display = "block";
        } else {
            subjectGroup.style.display = "none";
            messageGroup.style.display = "none";
            attachmentsGroup.style.display = "none";
        }

        updateSubmitState();
    }

    async function updatePurchaseStatus() {
        purchaseStatus.style.display = "none";
        purchaseStatus.textContent = "";
        purchaseStatus.className = "feedback-purchase-status";
        clearPurchaseSelection();

        const type = typeSelect.value;
        const email = emailInput.value.trim().toLowerCase();

        if (type !== "product_feedback") {
            purchaseStatus.style.display = "none";
            purchaseStatus.textContent = "";
            purchaseStatus.className = "feedback-purchase-status";

            updateFormVisibility(true);
            return;
        }

        if (!email) {
            purchaseStatus.style.display = "none";
            purchaseStatus.textContent = "";
            purchaseStatus.className = "feedback-purchase-status";

            updateFormVisibility(false);
            return;
        }

        purchaseStatus.style.display = "block";
        purchaseStatus.className = "feedback-purchase-status";
        purchaseStatus.textContent = texts.checkingPurchase;

        try {
            const response = await fetch("/v1/check-purchase", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    email: email
                }),
            });

            if (!response.ok) {
                throw new Error("Purchase check failed");
            }

            const result = await response.json();

            if (
                result.verified === true &&
                Array.isArray(result.purchases) &&
                result.purchases.length > 0 &&
                result.purchases.every((purchase) =>
                    typeof purchase.purchase_reference === "string" &&
                    purchase.purchase_reference !== "" &&
                    typeof purchase.product_name === "string" &&
                    typeof purchase.edition === "string"
                )
            ) {
                setPurchaseSelection(result.purchases);
                purchaseStatus.style.display = "block";
                purchaseStatus.className = "feedback-purchase-status success";
                purchaseStatus.textContent = texts.purchaseConfirmed;

                updateFormVisibility(true);
                if (result.purchases.length === 1) {
                    subjectInput.focus();
                } else {
                    purchaseSelect.focus();
                }
            } else {
                purchaseStatus.style.display = "block";
                purchaseStatus.className = "feedback-purchase-status error";
                purchaseStatus.textContent = texts.noPurchaseFound;

                updateFormVisibility(false);
            }
        } catch (error) {
            console.error("CHECK PURCHASE ERROR:", error);

            purchaseStatus.style.display = "block";
            purchaseStatus.className = "feedback-purchase-status error";
            purchaseStatus.textContent = texts.purchaseCheckFailed;

            updateFormVisibility(false);
        }
    }

    updateEmailVisibility();
    updateSupportReferenceState();
    updatePurchaseStatus();
    updateSubmitState();

    emailInput.addEventListener("blur", updatePurchaseStatus);

    emailInput.addEventListener("keydown", async (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            await updatePurchaseStatus();
            emailInput.blur();
        }
    });

    if (messageInput && messageCounter) {
        messageInput.addEventListener("input", updateMessageCounter);
        updateMessageCounter();
    }

    typeSelect.addEventListener("change", () => {
        updateEmailVisibility();
        updateSupportReferenceState();
        updatePurchaseStatus();
    });

    purchaseSelect.addEventListener("change", updateSubmitState);

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        status.textContent = texts.sending;
        status.className = "feedback-form__status";

        try {
            const formData = new FormData(form);

            const response = await fetch("/v1/feedback", {
                method: "POST",
                body: formData,
            });

            if (!response.ok) {
                throw new Error("Request failed");
            }

            const result = await response.json();

            status.textContent = `${texts.sentSuccessPrefix} ${result.id}`;
            status.className = "feedback-form__status feedback-form__status--success";

            resetAfterSuccessfulSubmission();
        } catch (error) {
            status.textContent = texts.sendFailed;
            status.className = "feedback-form__status feedback-form__status--error";
        }
    });

    attachmentsInput.addEventListener("change", () => {
        const allowedExtensions = [".png", ".jpg", ".jpeg", ".webp", ".pdf"];

        const files = Array.from(attachmentsInput.files || []);

        if (!files.length) {
            selectedFilesText.textContent =
                window.feedbackTexts.noFiles || "No files selected";
            return;
        }

        const invalidFiles = files.filter((file) => {
            const dotIndex = file.name.lastIndexOf(".");
            const extension = dotIndex >= 0 ? file.name.slice(dotIndex).toLowerCase() : "";
            return !allowedExtensions.includes(extension);
        });

        if (invalidFiles.length > 0) {
            selectedFilesText.textContent =
                window.feedbackTexts.invalidFileType || "Invalid file type selected";
            attachmentsInput.value = "";
            return;
        }

        const names = files.map((f) => f.name);
        selectedFilesText.textContent = names.join(", ");
    });

    if (feedbackDropzone && attachmentsInput) {
        feedbackDropzone.addEventListener("dragover", (event) => {
            event.preventDefault();
            feedbackDropzone.classList.add("is-dragover");
        });

        feedbackDropzone.addEventListener("dragleave", () => {
            feedbackDropzone.classList.remove("is-dragover");
        });

        feedbackDropzone.addEventListener("drop", (event) => {
            event.preventDefault();
            feedbackDropzone.classList.remove("is-dragover");

            const droppedFiles = event.dataTransfer?.files;
            if (!droppedFiles || droppedFiles.length === 0) {
                return;
            }

            attachmentsInput.files = droppedFiles;
            attachmentsInput.dispatchEvent(new Event("change"));
        });
    }
});
