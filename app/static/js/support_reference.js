(() => {
    "use strict";

    function fallbackCopy(value) {
        const input = document.createElement("textarea");
        input.value = value;
        input.setAttribute("readonly", "");
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        input.select();
        const copied = document.execCommand("copy");
        input.remove();
        if (!copied) {
            throw new Error("Copy command was rejected");
        }
    }

    async function copyValue(value) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(value);
                return;
            } catch (_error) {
                fallbackCopy(value);
                return;
            }
        }
        fallbackCopy(value);
    }

    async function activateCopy(control) {
        const value = control.dataset.copyValue;
        if (!value) {
            return;
        }

        try {
            await copyValue(value);
            const status = document.getElementById(
                control.getAttribute("aria-describedby")
            );
            if (status) {
                status.textContent = control.dataset.copySuccess || "";
            }
        } catch (_error) {
            // The visible reference remains available for manual selection.
        }
    }

    document.addEventListener("click", (event) => {
        const control = event.target.closest("[data-support-reference-copy]");
        if (control) {
            activateCopy(control);
        }
    });

    document.addEventListener("keydown", (event) => {
        const control = event.target.closest("[data-support-reference-copy]");
        if (control && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            activateCopy(control);
        }
    });
})();
