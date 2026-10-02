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

    function ask(question) {
        question = (question || "").trim();
        if (!question || busy) return;          // chặn gửi trùng
        setBusy(true);
        addMessage(question, "user");
        input.value = "";
        const waiting = addTyping();

        fetch(apiUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
            body: JSON.stringify({ question: question }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                waiting.remove();
                // data.error: server từ chối (gửi quá nhanh, dữ liệu lỗi) -
                // hiện đúng lý do thay vì "Không có kết quả." chung chung.
                addMessage(data.text || data.error || "Không có kết quả.", "bot",
                           data.links, data.source);
            })
            .catch(function () {
                waiting.remove();
                addMessage("Không kết nối được máy chủ. Bạn thử lại nhé.", "bot");
            })
            .finally(function () {
                setBusy(false);
                input.focus();
            });
    }

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        ask(input.value);
    });

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
