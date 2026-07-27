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
    let purchaseCheckSequence = 0;

    function setLiveMessage(element, message, { isError = false } = {}) {
        element.setAttribute("role", isError ? "alert" : "status");
        element.setAttribute("aria-atomic", "true");
        element.replaceChildren(document.createTextNode(message));
    }

    function resetLiveRegion(element) {
        element.setAttribute("role", "status");
        element.setAttribute("aria-atomic", "true");
        element.replaceChildren();
    }

    function rateLimitMessage(response) {
        const retryAfter = Number.parseInt(
            response.headers.get("Retry-After") || "",
            10
        );
        if (Number.isInteger(retryAfter) && retryAfter > 0) {
            return texts.rateLimitedRetry.replace("{seconds}", String(retryAfter));
        }
        return texts.rateLimited;
    }

    function clearControlValidation(control) {
        control.removeAttribute("aria-invalid");
        control.setCustomValidity("");
    }

    function setControlGroupVisible(group, controls, isVisible) {
        group.hidden = !isVisible;
        controls.forEach((control) => {
            control.disabled = !isVisible;
            if (!isVisible) {
                control.required = false;
                clearControlValidation(control);
            }
        });
    }

    function clearPurchaseStatus() {
        purchaseStatus.hidden = true;
        purchaseStatus.style.display = "none";
        purchaseStatus.className = "feedback-purchase-status";
        resetLiveRegion(purchaseStatus);
        emailInput.setAttribute("aria-describedby", "email-hint");
        emailInput.removeAttribute("aria-busy");
        clearControlValidation(emailInput);
    }

    function setPurchaseStatus(message, { isError = false, isBusy = false } = {}) {
        purchaseStatus.hidden = false;
        purchaseStatus.style.display = "block";
        purchaseStatus.className = isError
            ? "feedback-purchase-status error"
            : "feedback-purchase-status";
        setLiveMessage(purchaseStatus, message, { isError });
        emailInput.setAttribute("aria-describedby", "email-hint purchase-status");
        if (isBusy) {
            emailInput.setAttribute("aria-busy", "true");
        } else {
            emailInput.removeAttribute("aria-busy");
        }
    }

    function clearSubmissionStatus() {
        status.className = "feedback-form__status";
        resetLiveRegion(status);
    }

    function clearPurchaseSelection() {
        purchaseSelect.replaceChildren();

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = texts.purchasePlaceholder;
        purchaseSelect.appendChild(placeholder);

        purchaseSelect.value = "";
        purchaseSelect.disabled = true;
        purchaseSelect.required = false;
        purchaseSelect.removeAttribute("aria-describedby");
        clearControlValidation(purchaseSelect);
        purchaseSelectorGroup.hidden = true;
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
        purchaseSelect.setAttribute("aria-describedby", "purchase-status");
        purchaseSelectorGroup.hidden = false;
    }

    function updateSupportReferenceState() {
        if (!supportReferenceGroup || !supportReferenceInput) {
            return;
        }

        const shouldIncludeReference =
            typeSelect.value === "purchase_or_download_issue" &&
            supportReferenceInput.value !== "";

        setControlGroupVisible(
            supportReferenceGroup,
            [supportReferenceInput],
            shouldIncludeReference,
        );
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

        setLiveMessage(selectedFilesText, texts.noFiles);
        clearControlValidation(attachmentsInput);
        feedbackDropzone.classList.remove("is-dragover");

        clearPurchaseStatus();
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
        const attachmentWasInvalid =
            attachmentsInput.getAttribute("aria-invalid") === "true";
        setControlGroupVisible(subjectGroup, [subjectInput], isVisible);
        setControlGroupVisible(messageGroup, [messageInput], isVisible);
        setControlGroupVisible(attachmentsGroup, [attachmentsInput], isVisible);

        subjectInput.required = isVisible;
        messageInput.required = isVisible;

        if (!isVisible && attachmentWasInvalid) {
            attachmentsInput.value = "";
            setLiveMessage(selectedFilesText, texts.noFiles);
        }

        updateSubmitState();
    }

    async function updatePurchaseStatus({ focusRequiredSelection = false } = {}) {
        const checkSequence = ++purchaseCheckSequence;
        clearPurchaseStatus();
        clearPurchaseSelection();

        const type = typeSelect.value;
        const email = emailInput.value.trim().toLowerCase();

        if (type !== "product_feedback") {
            updateFormVisibility(true);
            return;
        }

        if (!email) {
            updateFormVisibility(false);
            return;
        }

        setPurchaseStatus(texts.checkingPurchase, { isBusy: true });

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

            if (checkSequence !== purchaseCheckSequence) {
                return;
            }

            if (response.status === 429) {
                setPurchaseStatus(rateLimitMessage(response), { isError: true });
                updateFormVisibility(false);
                return;
            }

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
                setPurchaseStatus(texts.purchaseConfirmed);
                purchaseStatus.className = "feedback-purchase-status success";
                clearControlValidation(emailInput);

                updateFormVisibility(true);
                if (result.purchases.length > 1 && focusRequiredSelection) {
                    purchaseSelect.focus();
                }
            } else {
                setPurchaseStatus(texts.noPurchaseFound, { isError: true });
                emailInput.setAttribute("aria-invalid", "true");

                updateFormVisibility(false);
            }
        } catch (error) {
            if (checkSequence !== purchaseCheckSequence) {
                return;
            }
            console.error("CHECK PURCHASE ERROR:", error);

            setPurchaseStatus(texts.purchaseCheckFailed, { isError: true });

            updateFormVisibility(false);
        }
    }

    updateEmailVisibility();
    updateSupportReferenceState();
    updatePurchaseStatus();
    updateSubmitState();

    emailInput.addEventListener("blur", (event) => {
        if (event.relatedTarget === purchaseSelect) {
            return;
        }
        updatePurchaseStatus();
    });

    emailInput.addEventListener("input", () => {
        if (typeSelect.value !== "product_feedback") {
            return;
        }

        purchaseCheckSequence += 1;
        clearPurchaseStatus();
        clearPurchaseSelection();
        updateFormVisibility(false);
    });

    emailInput.addEventListener("keydown", async (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            await updatePurchaseStatus({ focusRequiredSelection: true });
        }
    });

    if (messageInput && messageCounter) {
        messageInput.addEventListener("input", updateMessageCounter);
        updateMessageCounter();
    }

    typeSelect.addEventListener("change", () => {
        clearSubmissionStatus();
        updateEmailVisibility();
        updateSupportReferenceState();
        updatePurchaseStatus();
    });

    purchaseSelect.addEventListener("change", () => {
        if (purchaseSelect.validity.valid) {
            clearControlValidation(purchaseSelect);
        }
        updateSubmitState();
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        status.className = "feedback-form__status";
        setLiveMessage(status, texts.sending);
        form.setAttribute("aria-busy", "true");
        submitButton.disabled = true;

        try {
            const formData = new FormData(form);

            const response = await fetch("/v1/feedback", {
                method: "POST",
                body: formData,
            });

            if (response.status === 429) {
                status.className = "feedback-form__status feedback-form__status--error";
                setLiveMessage(status, rateLimitMessage(response), { isError: true });
                form.removeAttribute("aria-busy");
                updateSubmitState();
                return;
            }

            if (!response.ok) {
                throw new Error("Request failed");
            }

            const result = await response.json();

            status.className = "feedback-form__status feedback-form__status--success";
            setLiveMessage(status, `${texts.sentSuccessPrefix} ${result.id}`);

            form.removeAttribute("aria-busy");
            resetAfterSuccessfulSubmission();
        } catch (error) {
            status.className = "feedback-form__status feedback-form__status--error";
            setLiveMessage(status, texts.sendFailed, { isError: true });
            form.removeAttribute("aria-busy");
            updateSubmitState();
        }
    });

    attachmentsInput.addEventListener("change", () => {
        const allowedExtensions = [".png", ".jpg", ".jpeg", ".webp", ".pdf"];

        const files = Array.from(attachmentsInput.files || []);

        if (!files.length) {
            clearControlValidation(attachmentsInput);
            setLiveMessage(selectedFilesText, texts.noFiles);
            return;
        }

        const invalidFiles = files.filter((file) => {
            const dotIndex = file.name.lastIndexOf(".");
            const extension = dotIndex >= 0 ? file.name.slice(dotIndex).toLowerCase() : "";
            return !allowedExtensions.includes(extension);
        });

        if (invalidFiles.length > 0) {
            attachmentsInput.value = "";
            attachmentsInput.setAttribute("aria-invalid", "true");
            setLiveMessage(selectedFilesText, texts.invalidFileType, {
                isError: true,
            });
            return;
        }

        const names = files.map((file) => {
            const pathParts = file.name.split(/[\\/]/);
            return pathParts[pathParts.length - 1];
        });
        clearControlValidation(attachmentsInput);
        setLiveMessage(selectedFilesText, names.join(", "));
    });

    form.addEventListener(
        "invalid",
        (event) => {
            const control = event.target;
            if (control instanceof HTMLInputElement ||
                control instanceof HTMLSelectElement ||
                control instanceof HTMLTextAreaElement) {
                control.setAttribute("aria-invalid", "true");
            }
        },
        true,
    );

    form.addEventListener("input", (event) => {
        const control = event.target;
        if ((control instanceof HTMLInputElement ||
            control instanceof HTMLSelectElement ||
            control instanceof HTMLTextAreaElement) &&
            control.validity.valid) {
            clearControlValidation(control);
        }
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
