(function () {
    "use strict";

    var HEARTBEAT_INTERVAL_MS = 5000;
    var INDEX_PATH = "/";
    var SHORTCUT_KEY_SIZE = "s";
    var SHORTCUT_KEY_NEXT = "n";
    var SHORTCUT_KEY_PREVIOUS = "p";
    var SHORTCUT_KEY_INDEX = "i";
    var SHORTCUT_KEY_QUIT = "q";
    var SHORTCUT_KEY_FOCUS_COMMENT = "/";
    var SHORTCUT_KEY_ENTER = "Enter";
    var SHORTCUT_KEY_GO_TO = "g";
    var DIGIT_KEYS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

    var isIndex = !!window.__BUGSHOT_IMAGES__;
    var isDetail = !!window.__BUGSHOT_DETAIL__;
    var detail = window.__BUGSHOT_DETAIL__ || null;
    var isInternalNavigation = false;
    var jumpModal = null;
    var jumpModalInput = null;
    var jumpModalError = null;
    var serverStatusBanner = null;
    var serverStatusText = null;
    var isServerReachable = true;
    var serverActionButtons = [];

    initServerStatusBanner();
    checkServerHeartbeat();
    setInterval(checkServerHeartbeat, HEARTBEAT_INTERVAL_MS);

    window.addEventListener("beforeunload", function () {
        if (!isInternalNavigation) {
            navigator.sendBeacon("/api/closed");
        }
    });

    bindDoneButton(document.getElementById("done-btn"));
    bindDoneButton(document.getElementById("detail-done-btn"));

    if (isIndex) {
        initIndex();
    }

    if (isDetail) {
        initDetail();
    }

    initJumpModal();

    document.addEventListener("keydown", function (event) {
        if (isJumpModalOpen()) {
            handleJumpModalKeydown(event);
            return;
        }

        var activeElement = document.activeElement;
        var isTyping = activeElement &&
            (activeElement.tagName === "INPUT" || activeElement.tagName === "TEXTAREA");

        if (isTyping) {
            if (event.key === "Escape") {
                activeElement.blur();
                event.preventDefault();
            }
            return;
        }

        if (event.key === SHORTCUT_KEY_SIZE && isIndex) {
            toggleIndexSize();
            event.preventDefault();
        } else if (DIGIT_KEYS.indexOf(event.key) !== -1) {
            navigateToImageByShortcut(event.key);
            event.preventDefault();
        } else if ((event.key === SHORTCUT_KEY_NEXT || event.key === SHORTCUT_KEY_ENTER) && isIndex) {
            navigateToFirstImage();
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_PREVIOUS && isIndex) {
            navigateToLastImage();
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_NEXT && isDetail && detail.nav.next) {
            navigateTo(detail.nav.next);
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_PREVIOUS && isDetail && detail.nav.prev) {
            navigateTo(detail.nav.prev);
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_GO_TO) {
            openJumpModal();
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_INDEX) {
            navigateTo(INDEX_PATH);
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_QUIT) {
            if (!isServerReachable) {
                showServerDown("Bugshot server is unreachable. Reconnect before finishing review.");
                event.preventDefault();
                return;
            }
            if (confirm("Done reviewing? This will end the session.")) {
                completeSession();
            }
            event.preventDefault();
        } else if (event.key === SHORTCUT_KEY_FOCUS_COMMENT && isDetail) {
            focusCommentInput();
            event.preventDefault();
        }
    });

    function bindDoneButton(button) {
        if (!button) {
            return;
        }

        serverActionButtons.push(button);
        button.addEventListener("click", function () {
            if (!isServerReachable) {
                showServerDown("Bugshot server is unreachable. Reconnect before finishing review.");
                return;
            }
            if (confirm("Done reviewing? This will end the session.")) {
                completeSession();
            }
        });
    }

    function initServerStatusBanner() {
        serverStatusBanner = document.createElement("div");
        serverStatusBanner.className = "server-status-banner is-hidden";
        serverStatusBanner.setAttribute("role", "status");

        serverStatusText = document.createElement("span");
        serverStatusBanner.appendChild(serverStatusText);
        document.body.insertBefore(serverStatusBanner, document.body.firstChild);
    }

    function checkServerHeartbeat() {
        fetch("/api/heartbeat", { method: "POST" })
            .then(requireOkResponse)
            .then(function () {
                setServerReachable(true);
            })
            .catch(function () {
                showServerDown("Bugshot server is unreachable. New comments cannot be saved until it responds again.");
            });
    }

    function setServerReachable(isReachable) {
        isServerReachable = isReachable;
        serverActionButtons.forEach(function (button) {
            button.disabled = !isReachable;
        });

        if (isReachable) {
            serverStatusBanner.classList.add("is-hidden");
            serverStatusText.textContent = "";
        }
    }

    function showServerDown(message) {
        setServerReachable(false);
        serverStatusText.textContent = message;
        serverStatusBanner.classList.remove("is-hidden");
    }

    function requireOkResponse(response) {
        if (!response.ok) {
            throw new Error("Request failed with status " + response.status);
        }
        return response;
    }

    function fetchJson(url, options) {
        return fetch(url, options)
            .then(requireOkResponse)
            .then(function (response) {
                setServerReachable(true);
                return response.json();
            });
    }

    function initJumpModal() {
        jumpModal = document.createElement("div");
        jumpModal.className = "jump-modal is-hidden";
        jumpModal.innerHTML =
            '<div class="jump-modal-card" role="dialog" aria-modal="true" aria-labelledby="jump-modal-title">' +
            '<div class="jump-modal-title" id="jump-modal-title">Go to image</div>' +
            '<div class="jump-modal-copy">Type any image number and press Enter.</div>' +
            '<form class="jump-modal-form" id="jump-modal-form">' +
            '<input class="jump-modal-input" id="jump-modal-input" inputmode="numeric" autocomplete="off" />' +
            '<button type="submit" class="btn">Go</button>' +
            "</form>" +
            '<div class="jump-modal-error" id="jump-modal-error"></div>' +
            "</div>";
        document.body.appendChild(jumpModal);

        jumpModalInput = document.getElementById("jump-modal-input");
        jumpModalError = document.getElementById("jump-modal-error");

        jumpModal.addEventListener("click", function (event) {
            if (event.target === jumpModal) {
                closeJumpModal();
            }
        });

        document.getElementById("jump-modal-form").addEventListener("submit", function (event) {
            event.preventDefault();
            submitJumpModal();
        });
    }

    function completeSession() {
        fetch("/api/done", { method: "POST" })
            .then(requireOkResponse)
            .then(function () {
                setServerReachable(true);
                window.close();

                document.body.textContent = "";
                var message = document.createElement("div");
                message.style.cssText =
                    "display:flex;align-items:center;justify-content:center;" +
                    "height:100vh;color:#e0e0e0;font-size:18px;";
                message.textContent = "Session complete. You can close this tab.";
                document.body.appendChild(message);
            })
            .catch(function () {
                showServerDown("Bugshot server is unreachable. Review was not marked complete.");
            });
    }

    function initIndex() {
        var images = window.__BUGSHOT_IMAGES__;
        var gallery = document.getElementById("gallery");

        images.forEach(function (imageInfo) {
            var item = document.createElement("a");
            item.className = "gallery-item";
            item.href = "/view/" + imageInfo.encoded_name;
            bindInternalNavigation(item);

            if (imageInfo.type === "image") {
                var imageElement = document.createElement("img");
                imageElement.src = imageInfo.src;
                imageElement.alt = imageInfo.name;
                item.appendChild(imageElement);
            } else {
                var previewDiv = document.createElement("div");
                previewDiv.className = "ansi-preview";
                var previewPre = document.createElement("pre");
                previewPre.innerHTML = imageInfo.preview_html;
                previewDiv.appendChild(previewPre);
                item.appendChild(previewDiv);
            }

            var label = document.createElement("div");
            label.className = "item-label";
            label.textContent = imageInfo.name;
            item.appendChild(label);

            gallery.appendChild(item);
        });
    }

    function navigateToFirstImage() {
        var images = getAvailableImages();
        if (!images.length) {
            return;
        }
        navigateTo("/view/" + images[0].encoded_name);
    }

    function navigateToLastImage() {
        var images = getAvailableImages();
        if (!images.length) {
            return;
        }

        navigateTo("/view/" + images[images.length - 1].encoded_name);
    }

    function initDetail() {
        var container = document.getElementById("image-container");
        var previousSlot = document.getElementById("prev-slot");
        var nextSlot = document.getElementById("next-slot");
        var indexButton = document.getElementById("index-btn");

        if (detail.contentType === "image") {
            var imageElement = document.createElement("img");
            imageElement.src = detail.imageSrc;
            imageElement.alt = detail.filename;
            container.appendChild(imageElement);
        } else {
            var ansiDiv = document.createElement("div");
            ansiDiv.className = "ansi-rendered";
            var ansiPre = document.createElement("pre");
            ansiPre.innerHTML = detail.ansiHtml;
            ansiDiv.appendChild(ansiPre);
            container.appendChild(ansiDiv);
        }

        previousSlot.appendChild(
            createNavigationButton({
                id: "prev-btn",
                label: "Previous",
                destination: detail.nav.prev,
                detailName: detail.nav.prev_name,
                direction: "previous",
            })
        );

        nextSlot.appendChild(
            createNavigationButton({
                id: "next-btn",
                label: "Next",
                destination: detail.nav.next,
                detailName: detail.nav.next_name,
                direction: "next",
            })
        );

        if (indexButton) {
            bindInternalNavigation(indexButton);
        }

        var commentForm = document.getElementById("comment-form");
        var commentInput = document.getElementById("comment-input");
        var commentSubmit = commentForm.querySelector("button[type='submit']");
        var commentsList = document.getElementById("comments-list");
        var commentStatus = document.createElement("div");
        commentStatus.className = "comment-status";
        commentForm.insertAdjacentElement("afterend", commentStatus);

        if (commentSubmit) {
            serverActionButtons.push(commentSubmit);
            commentSubmit.disabled = !isServerReachable;
        }

        loadComments();

        commentForm.addEventListener("submit", function (event) {
            event.preventDefault();
            commentStatus.textContent = "";
            if (!isServerReachable) {
                showServerDown("Bugshot server is unreachable. This comment was not saved.");
                commentStatus.textContent = "Comment was not saved because the server is unreachable.";
                return;
            }

            var body = commentInput.value.trim();
            if (!body) {
                return;
            }

            fetchJson("/api/comments", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: detail.filename, body: body }),
            })
                .then(function (comment) {
                    commentInput.value = "";
                    commentStatus.textContent = "";
                    appendComment(comment);
                })
                .catch(function () {
                    showServerDown("Bugshot server is unreachable. This comment was not saved.");
                    commentStatus.textContent = "Comment was not saved. Keep the text here and try again after reconnecting.";
                });
        });

        function loadComments() {
            fetchJson("/api/comments?image=" + encodeURIComponent(detail.filename))
                .then(function (comments) {
                    commentsList.textContent = "";
                    commentStatus.textContent = "";
                    comments.forEach(appendComment);
                })
                .catch(function () {
                    showServerDown("Bugshot server is unreachable. Existing comments could not be loaded.");
                    commentStatus.textContent = "Existing comments could not be loaded.";
                });
        }

        function appendComment(comment) {
            var item = document.createElement("div");
            item.className = "comment-item";
            item.dataset.id = comment.id;

            var bodyElement = document.createElement("span");
            bodyElement.className = "comment-body";
            bodyElement.textContent = comment.body;

            var actions = document.createElement("span");
            actions.className = "comment-actions";

            var editButton = document.createElement("button");
            editButton.textContent = "edit";
            editButton.addEventListener("click", function () {
                var nextBody = prompt("Edit comment:", comment.body);
                if (nextBody !== null && nextBody.trim()) {
                    fetchJson("/api/comments/" + comment.id, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ body: nextBody.trim() }),
                    })
                        .then(function (updated) {
                            commentStatus.textContent = "";
                            bodyElement.textContent = updated.body;
                            comment.body = updated.body;
                        })
                        .catch(function () {
                            showServerDown("Bugshot server is unreachable. Comment edit was not saved.");
                            commentStatus.textContent = "Comment edit was not saved.";
                        });
                }
            });

            var deleteButton = document.createElement("button");
            deleteButton.textContent = "delete";
            deleteButton.addEventListener("click", function () {
                if (confirm("Delete this comment?")) {
                    fetch("/api/comments/" + comment.id, { method: "DELETE" })
                        .then(requireOkResponse)
                        .then(function () {
                            setServerReachable(true);
                            commentStatus.textContent = "";
                            item.remove();
                        })
                        .catch(function () {
                            showServerDown("Bugshot server is unreachable. Comment was not deleted.");
                            commentStatus.textContent = "Comment was not deleted.";
                        });
                }
            });

            actions.appendChild(editButton);
            actions.appendChild(deleteButton);
            item.appendChild(bodyElement);
            item.appendChild(actions);
            commentsList.appendChild(item);
        }
    }

    function bindInternalNavigation(link) {
        link.addEventListener("click", function () {
            isInternalNavigation = true;
        });
    }

    function createNavigationButton(config) {
        if (!config.destination) {
            var disabledButton = document.createElement("span");
            disabledButton.className = "btn btn-disabled";
            disabledButton.id = config.id;
            disabledButton.textContent = config.label;
            disabledButton.setAttribute("aria-disabled", "true");
            return disabledButton;
        }

        var link = document.createElement("a");
        link.href = config.destination;
        link.className = "btn";
        link.id = config.id;

        if (config.direction === "previous") {
            link.textContent = "\u2190 " + config.detailName;
        } else {
            link.textContent = config.detailName + " \u2192";
        }

        bindInternalNavigation(link);
        return link;
    }

    function navigateTo(path) {
        isInternalNavigation = true;
        window.location.href = path;
    }

    function getAvailableImages() {
        if (isIndex) {
            return window.__BUGSHOT_IMAGES__ || [];
        }
        if (isDetail) {
            return detail.images || [];
        }
        return [];
    }

    function navigateToImageByShortcut(key) {
        var images = getAvailableImages();
        if (!images.length) {
            return;
        }

        if (key === "0") {
            navigateTo("/view/" + images[images.length - 1].encoded_name);
            return;
        }

        var imageNumber = parseInt(key, 10);
        navigateToImageNumber(imageNumber);
    }

    function navigateToImageNumber(imageNumber) {
        var images = getAvailableImages();
        if (!images.length) {
            return false;
        }
        if (!Number.isInteger(imageNumber) || imageNumber < 1 || imageNumber > images.length) {
            return false;
        }

        navigateTo("/view/" + images[imageNumber - 1].encoded_name);
        return true;
    }

    function isJumpModalOpen() {
        return jumpModal && !jumpModal.classList.contains("is-hidden");
    }

    function openJumpModal() {
        if (!jumpModal) {
            return;
        }
        jumpModal.classList.remove("is-hidden");
        jumpModalInput.value = "";
        jumpModalError.textContent = "";
        jumpModalInput.focus();
        jumpModalInput.select();
    }

    function closeJumpModal() {
        if (!jumpModal) {
            return;
        }
        jumpModal.classList.add("is-hidden");
        jumpModalError.textContent = "";
    }

    function submitJumpModal() {
        var rawValue = jumpModalInput.value.trim();
        var imageNumber = parseInt(rawValue, 10);

        if (!rawValue || !/^\d+$/.test(rawValue)) {
            jumpModalError.textContent = "Enter a valid image number.";
            return;
        }

        if (!navigateToImageNumber(imageNumber)) {
            jumpModalError.textContent = "That image number does not exist.";
            return;
        }
    }

    function handleJumpModalKeydown(event) {
        if (event.key === "Escape") {
            closeJumpModal();
            event.preventDefault();
            return;
        }

        if (event.key !== SHORTCUT_KEY_ENTER) {
            return;
        }

        submitJumpModal();
        event.preventDefault();
    }

    function toggleIndexSize() {
        if (!isIndex) {
            return;
        }

        var gallery = document.getElementById("gallery");
        var sizeToggle = document.getElementById("size-toggle");
        var isFullSize = gallery.classList.contains("fullsize-mode");
        var nextFullSizeState = !isFullSize;

        gallery.classList.toggle("thumbnail-mode", !nextFullSizeState);
        gallery.classList.toggle("fullsize-mode", nextFullSizeState);
        sizeToggle.textContent = nextFullSizeState ? "Thumbnails" : "Full Size";
    }

    function focusCommentInput() {
        var input = document.getElementById("comment-input");
        if (input) {
            input.focus();
        }
    }
})();
