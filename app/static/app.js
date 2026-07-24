"use strict";

const card = document.querySelector(".card");
const form = document.querySelector("#upload-form");
const fileInput = document.querySelector("#image");
const preview = document.querySelector("#preview");
const submitButton = document.querySelector("#submit-button");
const statusBox = document.querySelector("#status");
const attemptCount = document.querySelector("#attempt-count");

function showStatus(message, kind = "info") {
    statusBox.textContent = message;
    statusBox.className = `status visible ${kind}`;
}

function setFormEnabled(enabled) {
    fileInput.disabled = !enabled;
    submitButton.disabled = !enabled;
}

function applyServerStatus(data) {
    attemptCount.textContent = String(data.attempt_count ?? "-");

    if (data.state === "solved" || data.solved === true) {
        showStatus(data.reason || "Task completed!", "success");
        setFormEnabled(false);
        return;
    }

    if (data.state === "expired") {
        showStatus("This task has expired.", "error");
        setFormEnabled(false);
        return;
    }

    if (data.state === "checking") {
        showStatus("The photo is being verified…", "info");
        setFormEnabled(false);
        return;
    }

    if (data.state === "rejected") {
        showStatus(data.reason || "The task is not yet clearly fulfilled in this photo.", "error");
    } else if (data.state === "error") {
        showStatus(data.reason || "Verification failed. Please try again.", "error");
    }

    if (data.attempt_count >= data.max_attempts) {
        showStatus("No more attempts available.", "error");
        setFormEnabled(false);
    }
}

async function refreshStatus() {
    try {
        const response = await fetch(card.dataset.statusUrl, {
            headers: { Accept: "application/json" },
            cache: "no-store",
        });
        if (!response.ok) return;
        applyServerStatus(await response.json());
    } catch (_) {
        // temporary status-fetch failure
    }
}

fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) {
        preview.hidden = true;
        preview.removeAttribute("src");
        return;
    }

    const oldUrl = preview.dataset.objectUrl;
    if (oldUrl) URL.revokeObjectURL(oldUrl);

    const objectUrl = URL.createObjectURL(file);
    preview.dataset.objectUrl = objectUrl;
    preview.src = objectUrl;
    preview.hidden = false;
});

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = fileInput.files?.[0];
    if (!file) {
        showStatus("Please select a photo first.", "error");
        return;
    }

    setFormEnabled(false);
    showStatus("Preparing and verifying photo…", "info");

    try {
        const jpegBlob = await resizeToJpeg(file, 1600, 0.85);
        const body = new FormData();
        body.append("image", jpegBlob, "photo.jpg");

        const response = await fetch(form.action, {
            method: "POST",
            body,
            headers: { Accept: "application/json" },
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = typeof data.detail === "string"
                ? data.detail
                : data.detail?.message || "Verification could not be performed.";
            throw new Error(detail);
        }

        applyServerStatus(data);
        if (!data.solved && data.attempt_count < data.max_attempts) {
            setFormEnabled(true);
        }
    } catch (error) {
        showStatus(error instanceof Error ? error.message : "Unknown error", "error");
        setFormEnabled(true);
    }
});

async function resizeToJpeg(file, maxDimension, quality) {
    const image = await loadImage(file);
    const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("The browser cannot process the photo.");

    context.fillStyle = "white";
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);

    return await new Promise((resolve, reject) => {
        canvas.toBlob(
            (blob) => blob ? resolve(blob) : reject(new Error("The photo could not be converted.")),
            "image/jpeg",
            quality,
        );
    });
}

function loadImage(file) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        const objectUrl = URL.createObjectURL(file);
        image.onload = () => {
            URL.revokeObjectURL(objectUrl);
            resolve(image);
        };
        image.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            reject(new Error("This image format is not supported by the browser."));
        };
        image.src = objectUrl;
    });
}

applyServerStatus({
    state: card.dataset.state,
    solved: card.dataset.state === "solved",
    attempt_count: Number(attemptCount.textContent),
    max_attempts: Number(attemptCount.parentElement.textContent.split("/").pop()),
});
refreshStatus();
