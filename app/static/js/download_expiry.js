(() => {
    const expiry = document.getElementById("download-expiry");
    if (!expiry) return;

    try {
        const { timeZone } = new Intl.DateTimeFormat().resolvedOptions();
        if (!timeZone) return;

        const formatter = new Intl.DateTimeFormat(document.documentElement.lang, {
            timeZone,
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hourCycle: "h23",
            timeZoneName: "longOffset",
        });
        const parts = formatter.formatToParts(new Date(expiry.dateTime));
        if (!parts.some((part) => part.type === "timeZoneName")) return;

        expiry.textContent = `${parts.map((part) => part.value).join("")} (${timeZone})`;
    } catch {
        // Keep the server-rendered UTC timestamp if local formatting fails.
    }
})();
