(() => {
  "use strict";

  const createForm = document.getElementById("create-form");
  const urlInput = document.getElementById("youtube-url");
  const titleInput = document.getElementById("custom-title");
  const formatSelect = document.getElementById("format");
  const coverInput = document.getElementById("cover-input");
  const dropzone = document.getElementById("cover-dropzone");
  const coverPlaceholder = document.getElementById("cover-placeholder");
  const coverPreview = document.getElementById("cover-preview");
  const coverReset = document.getElementById("cover-reset");
  const submitButton = document.getElementById("create-submit");
  const submitSpinner = document.getElementById("create-spinner");
  const submitLabel = document.getElementById("create-label");

  const tracksGrid = document.getElementById("tracks-grid");
  const emptyState = document.getElementById("empty-state");
  const storageTotal = document.getElementById("storage-total");
  const cardTemplate = document.getElementById("track-card-template");

  const qrModal = document.getElementById("qr-modal");
  const qrBackdrop = document.getElementById("qr-backdrop");
  const qrClose = document.getElementById("qr-close");
  const qrContent = document.getElementById("qr-content");
  const qrLink = document.getElementById("qr-link");
  const qrCopy = document.getElementById("qr-copy");

  const toastContainer = document.getElementById("toast-container");

  let previewUrl = null;
  let isCreating = false;
  let activeQrId = null;
  const deletingIds = new Set();

  const formatDuration = (seconds) => {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    const remainder = total % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  };

  const formatMb = (bytes) => {
    const megabytes = Math.max(0, Number(bytes) || 0) / (1024 * 1024);
    return `${megabytes.toFixed(1)} MB`;
  };

  const trackBase = (id) => `/api/tracks/${encodeURIComponent(id)}`;
  const trackUrl = (id, suffix) => `${trackBase(id)}/${suffix}`;

  const showToast = (message, type = "success") => {
    const palette =
      type === "error"
        ? "border-red-500/40 bg-red-500/10 text-red-200"
        : "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
    const toast = document.createElement("div");
    toast.className = `pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-lg backdrop-blur transition duration-300 ${palette}`;
    toast.setAttribute("role", "status");
    toast.textContent = message;
    toastContainer.appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add("opacity-0", "translate-y-2");
    }, 3200);
    window.setTimeout(() => {
      toast.remove();
    }, 3700);
  };

  const requestJson = async (response) => {
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail =
        data && typeof data.detail === "string"
          ? data.detail
          : `Request failed (${response.status})`;
      throw new Error(detail);
    }
    return data;
  };

  const renderTrack = (track) => {
    const fragment = cardTemplate.content.cloneNode(true);
    const card = fragment.querySelector("article");
    const cover = fragment.querySelector('[data-role="cover"]');
    const title = fragment.querySelector('[data-role="title"]');
    const duration = fragment.querySelector('[data-role="duration"]');
    const size = fragment.querySelector('[data-role="size"]');
    const qrButton = fragment.querySelector('[data-action="qr"]');
    const downloadLink = fragment.querySelector('[data-action="download"]');
    const deleteButton = fragment.querySelector('[data-action="delete"]');

    cover.src = trackUrl(track.id, "cover");
    cover.alt = track.title;
    title.textContent = track.title;
    duration.textContent = formatDuration(track.duration_sec);
    size.textContent = formatMb(track.file_size_bytes);
    downloadLink.href = trackUrl(track.id, "download");
    qrButton.addEventListener("click", () => openQr(track.id));
    deleteButton.addEventListener("click", () => deleteTrack(track.id));

    return card;
  };

  const loadTracks = async () => {
    emptyState.classList.add("hidden");
    try {
      const response = await fetch("/api/tracks", {
        headers: { Accept: "application/json" },
      });
      const data = await requestJson(response);
      const tracks = Array.isArray(data.tracks) ? data.tracks : [];

      tracksGrid.replaceChildren();
      tracks.forEach((track) => {
        tracksGrid.appendChild(renderTrack(track));
      });
      emptyState.classList.toggle("hidden", tracks.length > 0);
      storageTotal.textContent = formatMb(data.total_size_bytes);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to load library";
      showToast(message, "error");
    }
  };

  const deleteTrack = async (id) => {
    if (deletingIds.has(id)) {
      return;
    }
    deletingIds.add(id);
    try {
      const response = await fetch(trackBase(id), {
        method: "DELETE",
      });
      if (!response.ok) {
        const message =
          response.status === 404
            ? "Track not found"
            : `Delete failed (${response.status})`;
        throw new Error(message);
      }
      if (activeQrId === id) {
        closeQr();
      }
      await loadTracks();
      showToast("Track deleted");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete track";
      showToast(message, "error");
    } finally {
      deletingIds.delete(id);
    }
  };

  const closeQr = () => {
    activeQrId = null;
    qrModal.classList.add("hidden");
    qrModal.classList.remove("flex");
    qrContent.replaceChildren();
  };

  const openQr = async (id) => {
    activeQrId = id;
    qrContent.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "text-sm font-medium text-zinc-400";
    loading.textContent = "Loading...";
    qrContent.appendChild(loading);
    qrLink.value = `${window.location.origin}${trackUrl(id, "download")}`;
    qrModal.classList.remove("hidden");
    qrModal.classList.add("flex");

    try {
      const response = await fetch(trackUrl(id, "qr"), {
        headers: { Accept: "image/svg+xml" },
      });
      if (!response.ok) {
        const message =
          response.status === 404
            ? "Track not found"
            : `QR request failed (${response.status})`;
        throw new Error(message);
      }
      const svg = await response.text();
      if (activeQrId !== id) {
        return;
      }
      qrContent.innerHTML = svg;
    } catch (error) {
      if (activeQrId !== id) {
        return;
      }
      const message =
        error instanceof Error ? error.message : "Failed to load QR code";
      closeQr();
      showToast(message, "error");
    }
  };

  const copyLink = async () => {
    const value = qrLink.value;
    if (!value) {
      return;
    }

    let copied = false;
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        copied = true;
      } catch {
        copied = false;
      }
    }

    if (!copied) {
      qrLink.focus();
      qrLink.select();
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
    }

    if (copied) {
      showToast("Link copied");
    } else {
      qrLink.focus();
      qrLink.select();
      showToast("Press Ctrl+C to copy the link", "error");
    }
  };

  const clearPreview = () => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    coverPreview.removeAttribute("src");
    coverPreview.classList.add("hidden");
    coverPlaceholder.classList.remove("hidden");
    coverReset.classList.add("hidden");
  };

  const setCover = (file) => {
    if (!file) {
      clearPreview();
      return false;
    }
    if (!file.type.startsWith("image/")) {
      showToast("Please choose an image file", "error");
      return false;
    }
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    previewUrl = URL.createObjectURL(file);
    coverPreview.src = previewUrl;
    coverPreview.classList.remove("hidden");
    coverPlaceholder.classList.add("hidden");
    coverReset.classList.remove("hidden");
    return true;
  };

  const setCreating = (active) => {
    isCreating = active;
    submitButton.disabled = active;
    submitSpinner.classList.toggle("hidden", !active);
    submitLabel.textContent = active ? "Creating..." : "Create file";
  };

  const resetForm = () => {
    createForm.reset();
    coverInput.value = "";
    clearPreview();
  };

  dropzone.addEventListener("click", (event) => {
    if (event.target === coverInput) {
      return;
    }
    coverInput.click();
  });

  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      coverInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.add("border-accent", "bg-accent/5");
    });
  });

  ["dragleave", "drop"].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.remove("border-accent", "bg-accent/5");
    });
  });

  dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (!file || !setCover(file)) {
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    coverInput.files = transfer.files;
  });

  coverInput.addEventListener("change", () => {
    const file = coverInput.files?.[0] ?? null;
    if (!setCover(file)) {
      coverInput.value = "";
      clearPreview();
    }
  });

  coverReset.addEventListener("click", () => {
    coverInput.value = "";
    clearPreview();
  });

  createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isCreating) {
      return;
    }

    const url = urlInput.value.trim();
    if (!url) {
      showToast("Paste a YouTube link first", "error");
      urlInput.focus();
      return;
    }

    const body = new FormData();
    body.append("url", url);
    body.append("format", formatSelect.value);
    const title = titleInput.value.trim();
    if (title) {
      body.append("custom_title", title);
    }
    const file = coverInput.files?.[0];
    if (file) {
      body.append("cover", file, file.name);
    }

    setCreating(true);
    try {
      const response = await fetch("/api/tracks", {
        method: "POST",
        body,
      });
      const track = await requestJson(response);
      const extension = (track.file_path.split(".").pop() || "").toUpperCase();
      showToast(`${extension || "File"} created`);
      resetForm();
      await loadTracks();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to create file";
      showToast(message, "error");
    } finally {
      setCreating(false);
    }
  });

  qrClose.addEventListener("click", closeQr);
  qrBackdrop.addEventListener("click", closeQr);
  qrCopy.addEventListener("click", copyLink);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !qrModal.classList.contains("hidden")) {
      closeQr();
    }
  });

  loadTracks();
})();
