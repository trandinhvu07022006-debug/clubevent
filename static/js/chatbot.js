/*
 * Giao diện chat cho trợ lý tra cứu.
 *
 * Gửi câu hỏi lên server bằng fetch, nhận JSON rồi hiện ra. Toàn bộ phần
 * "hiểu câu hỏi" nằm ở server (aiassist/chatbot.py), file này chỉ lo giao diện.
 */
(function () {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    const log = document.getElementById("chat-log");
    if (!form || !input || !log) return;

    const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;

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

    function ask(question) {
        if (!question.trim()) return;
        addMessage(question, "user");
        input.value = "";

        const waiting = addMessage("Đang tra cứu...", "bot");

        fetch("/troly/hoi/", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
            body: JSON.stringify({ question: question }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                waiting.remove();
                // data.error: server từ chối (gửi quá nhanh, dữ liệu lỗi) —
                // hiện đúng lý do thay vì "Không có kết quả." chung chung.
                addMessage(data.text || data.error || "Không có kết quả.", "bot",
                           data.links, data.source);
            })
            .catch(function () {
                waiting.remove();
                addMessage("Không kết nối được máy chủ. Bạn thử lại nhé.", "bot");
            });
    }

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        ask(input.value);
    });

    // Bấm vào câu gợi ý thì hỏi luôn
    document.querySelectorAll("#chat-suggestions .chip").forEach(function (btn) {
        btn.addEventListener("click", function () {
            ask(btn.textContent.trim());
        });
    });

    input.focus();
})();
