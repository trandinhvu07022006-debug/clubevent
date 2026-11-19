/*
 * Giao diện chat cho trợ lý tra cứu.
 *
 * Gửi câu hỏi lên server bằng fetch, nhận JSON rồi hiện ra. Toàn bộ phần
 * "hiểu câu hỏi" nằm ở server (aiassist/chatbot.py), file này chỉ lo giao diện.
 *
 * MỘT CHỖ DUY NHẤT xử lý gửi câu hỏi. Lỗi cũ: nút câu mẫu vừa có onclick
 * trong template (bắn sự kiện submit) vừa có click listener ở đây -> mỗi lần
 * bấm gửi 2 câu, câu sau dính "Bạn gửi quá nhanh". Giờ template không gắn
 * JS nào nữa, và có cờ `busy`: đang chờ trả lời thì mọi cách gửi đều bị chặn.
 */
(function () {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    const log = document.getElementById("chat-log");
    if (!form || !input || !log) return;

    const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
    const apiUrl = form.dataset.api || "/troly/hoi/";
    const streamUrl = form.dataset.streamApi || "/troly/stream/";
    const sendBtn = form.querySelector("button[type=submit]");
    const suggestions = document.getElementById("chat-suggestions");
    let busy = false;

    /** Thêm một bong bóng chat vào khung hội thoại. */
    function addMessage(text, who, links, source) {
        const div = document.createElement("div");
        div.className = "chat-msg chat-" + who;
        // Dùng textContent chứ KHÔNG dùng innerHTML: nếu người dùng gõ thẻ
        // HTML thì nó hiện ra dạng chữ, không chạy được mã độc (chống XSS).
        // Câu trả lời của AI cũng đi đường này nên AI có trả về HTML cũng vô hại.
        div.textContent = text;

        // Câu trả lời từ AI: gắn nhãn để người dùng biết nó có thể chưa chính
        // xác (khác với câu trả lời tra thẳng từ CSDL).
        if (source === "ai") {
            const tag = document.createElement("div");
            tag.className = "chat-ai-tag";
            tag.textContent = "✨ Trả lời bởi AI · có thể chưa chính xác";
            div.appendChild(tag);
        }

        if (links && links.length) {
            const box = document.createElement("div");
            box.className = "chat-links";
            links.slice(0, 4).forEach(function (l) {
                const a = document.createElement("a");
                a.href = l.url;
                a.className = "btn btn-sm btn-outline-primary";
                a.textContent = l.label;
                box.appendChild(a);
            });
            div.appendChild(box);
        }
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    /** Bong bóng "đang gõ" (3 chấm) thay cho dòng chữ chờ. */
    function addTyping() {
        const div = document.createElement("div");
        div.className = "chat-msg chat-bot chat-typing";
        div.setAttribute("aria-label", "Đang tra cứu");
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement("span");
            dot.className = "typing-dot";
            div.appendChild(dot);
        }
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    /** Khoá / mở ô nhập, nút gửi và các câu mẫu trong lúc chờ trả lời. */
    function setBusy(value) {
        busy = value;
        input.disabled = value;
        if (sendBtn) sendBtn.disabled = value;
        if (suggestions) {
            suggestions.querySelectorAll("button").forEach(function (b) { b.disabled = value; });
        }
        log.setAttribute("aria-busy", value ? "true" : "false");
    }

    async function ask(question) {
        question = (question || "").trim();
        if (!question || busy) return;          // chặn gửi trùng
        setBusy(true);
        addMessage(question, "user");
        input.value = "";
        const waiting = addTyping();

        try {
            const resp = await fetch(streamUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
                body: JSON.stringify({ question: question }),
            });

            if (!resp.ok) {
                const data = await resp.json().catch(function () { return {}; });
                waiting.remove();
                addMessage(data.error || "Có lỗi xảy ra khi xử lý yêu cầu.", "bot");
                return;
            }

            const ctype = resp.headers.get("content-type") || "";
            if (!ctype.includes("text/event-stream") || !resp.body || !window.ReadableStream) {
                const data = await resp.json();
                waiting.remove();
                addMessage(data.text || data.error || "Không có kết quả.", "bot",
                           data.links, data.source);
                return;
            }

            waiting.remove();
            const botBubble = document.createElement("div");
            botBubble.className = "chat-msg chat-bot";
            log.appendChild(botBubble);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let accumulated = "";
            let finalData = null;
            let buffer = "";

            while (true) {
                const chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].trim();
                    if (line.startsWith("data:")) {
                        const jsonStr = line.slice(5).trim();
                        if (!jsonStr) continue;
                        try {
                            const parsed = JSON.parse(jsonStr);
                            if (parsed.token) {
                                accumulated += parsed.token;
                                botBubble.textContent = accumulated;
                                log.scrollTop = log.scrollHeight;
                            }
                            if (parsed.done) {
                                finalData = parsed;
                            }
                        } catch (e) {
                            // Bỏ qua lỗi parse từng chunk
                        }
                    }
                }
            }

            if (finalData) {
                botBubble.textContent = finalData.text || accumulated;
                if (finalData.source === "ai") {
                    const tag = document.createElement("div");
                    tag.className = "chat-ai-tag";
                    tag.textContent = "✨ Trả lời bởi AI · có thể chưa chính xác";
                    botBubble.appendChild(tag);
                }
                if (finalData.links && finalData.links.length) {
                    const box = document.createElement("div");
                    box.className = "chat-links";
                    finalData.links.slice(0, 4).forEach(function (l) {
                        const a = document.createElement("a");
                        a.href = l.url;
                        a.className = "btn btn-sm btn-outline-primary";
                        a.textContent = l.label;
                        box.appendChild(a);
                    });
                    botBubble.appendChild(box);
                }
            } else if (!accumulated) {
                botBubble.textContent = "Không có kết quả.";
            }
            log.scrollTop = log.scrollHeight;
        } catch (err) {
            waiting.remove();
            addMessage("Không kết nối được máy chủ. Bạn thử lại nhé.", "bot");
        } finally {
            setBusy(false);
            input.focus();
        }
    }

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        ask(input.value);
    });

    const clearBtn = document.getElementById("chat-clear-btn");
    if (clearBtn) {
        clearBtn.addEventListener("click", function () {
            if (busy) return;
            fetch(apiUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
                body: JSON.stringify({ action: "clear" }),
            }).then(function () {
                log.innerHTML = '<div class="chat-msg chat-bot"><i class="bi bi-robot"></i> Chào bạn. Mình là trợ lý sự kiện KMG.<br>Bạn có thể hỏi mình về lịch trình sự kiện sắp tới, số chỗ còn lại, vé của bạn, công việc được giao, hoặc cách thức đăng ký/check-in.</div>';
            });
        });
    }

    // Bấm câu gợi ý thì hỏi luôn. Ủy quyền sự kiện (1 listener cho cả khối)
    // và đọc câu hỏi từ data-question, không phụ thuộc khoảng trắng/icon.
    if (suggestions) {
        suggestions.addEventListener("click", function (e) {
            const btn = e.target.closest("button[data-question]");
            if (btn) ask(btn.dataset.question);
        });
    }

    input.focus();
})();
