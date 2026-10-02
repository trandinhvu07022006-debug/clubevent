/*
 * F5.3 + F5.4 - Quét QR bằng camera và bảng điểm danh cập nhật liên tục.
 *
 * Nguyên tắc: camera là lớp TĂNG CƯỜNG. Ô gõ tay luôn còn và luôn dùng được;
 * camera không khả dụng thì im lặng rơi về gõ tay.
 *
 * Bảo mật: mọi dữ liệu từ server (tên người dùng, thông báo) được gán bằng
 * textContent, KHÔNG ghép vào innerHTML - tên người dùng do họ tự đặt, ghép
 * thẳng vào HTML là lỗ hổng XSS nhắm vào máy của BTC.
 */
(function () {
  "use strict";

  var root = document.getElementById("checkin-app");
  if (!root) return;

  var scanUrl = root.dataset.scanUrl;
  var progressUrl = root.dataset.progressUrl;
  var csrfToken = root.querySelector("[name=csrfmiddlewaretoken]").value;

  var video = document.getElementById("qr-video");
  var canvasEl = document.getElementById("qr-canvas");
  var ctx = canvasEl.getContext("2d", { willReadFrequently: true });
  var btnCamera = document.getElementById("btn-camera");
  var cameraNote = document.getElementById("camera-note");
  var cameraBox = document.getElementById("camera-box");
  var resultBox = document.getElementById("scan-result");
  var form = document.getElementById("manual-form");
  var input = document.getElementById("code-input");

  var CODE_RE = /^[0-9A-F]{12}$/;
  var SCAN_EVERY_MS = 120;          // ~8 lần/giây: đủ nhanh, đỡ nóng máy
  var DEDUPE_MS = 3000;             // camera đọc 1 vé nhiều lần/giây -> bỏ qua lặp
  var RESULT_HOLD_MS = 1800;

  var state = "IDLE";               // IDLE | SCANNING | BUSY
  var stream = null;
  var detector = null;
  var lastCode = "", lastTime = 0, lastDecode = 0;
  var wantCamera = false;           // để bật lại khi tab hiện trở lại
  var audioCtx = null;

  // ---------------------------------------------------------------- tiện ích
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function beep(ok) {
    if (!audioCtx) return;
    try {
      var o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.frequency.value = ok ? 880 : 220;
      g.gain.value = 0.15;
      o.connect(g); g.connect(audioCtx.destination);
      o.start(); o.stop(audioCtx.currentTime + (ok ? 0.12 : 0.3));
    } catch (e) {}
  }

  function feedback(result) {
    var ok = result === "OK";
    if (navigator.vibrate) navigator.vibrate(ok ? 120 : [80, 60, 80]);
    beep(ok);
  }

  // ----------------------------------------------------------- hiện kết quả
  var VERDICT = {
    OK: { cls: "success", icon: "bi-check-circle-fill", label: "HỢP LỆ" },
    USED: { cls: "warning", icon: "bi-exclamation-triangle-fill", label: "ĐÃ SỬ DỤNG" },
    INVALID: { cls: "danger", icon: "bi-x-circle-fill", label: "KHÔNG HỢP LỆ" }
  };

  function renderResult(result, message, ticket) {
    var v = VERDICT[result] || VERDICT.INVALID;
    var card = el("div", "card shadow-sm mb-4 border-0 text-center checkin-result bg-" +
                  v.cls + "-subtle text-" + v.cls + "-emphasis");
    card.setAttribute("role", "status");
    var body = el("div", "card-body p-4");
    var h = el("h2", "fw-bold mb-2 checkin-verdict");
    h.appendChild(el("i", "bi " + v.icon));
    h.appendChild(document.createTextNode(" " + v.label));
    body.appendChild(h);
    body.appendChild(el("div", "fs-5 mb-3", message));
    if (ticket) {
      var box = el("div", "bg-body bg-opacity-50 p-3 rounded-3 text-start");
      box.appendChild(el("div", "text-muted small mb-1", "Mã vé"));
      box.appendChild(el("div", "checkin-code fs-4 mb-2", ticket.code));
      box.appendChild(el("div", "fw-bold fs-5", ticket.user_name));
      if (ticket.mssv) box.appendChild(el("div", "text-muted mb-2", "MSSV: " + ticket.mssv));
      box.appendChild(el("span", "badge bg-secondary px-3 py-2 fs-6", ticket.ticket_type));
      body.appendChild(box);
    }
    card.appendChild(body);
    resultBox.replaceChildren(card);
  }

  // --------------------------------------------------------- gửi mã lên server
  function submitCode(code, fromCamera) {
    state = "BUSY";
    return fetch(scanUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ code: code }),
      credentials: "same-origin"
    }).then(function (res) {
      if (!res.ok && res.status !== 400) throw new Error("HTTP " + res.status);
      return res.json();
    }).then(function (data) {
      renderResult(data.result, data.note || data.error, data.ticket);
      feedback(data.result);
      refreshProgress();
    }).catch(function () {
      renderResult("INVALID", "Mất kết nối, thử lại.", null);
      feedback("INVALID");
    }).then(function () {
      // Không bao giờ kẹt ở BUSY, kể cả khi lỗi mạng
      setTimeout(function () {
        state = stream ? "SCANNING" : "IDLE";
        if (!fromCamera && input) input.focus();
      }, fromCamera ? RESULT_HOLD_MS : 0);
    });
  }

  // Ô gõ tay: gửi qua JSON để không tải lại trang. Lỗi JS thì form vẫn POST
  // như cũ (không chặn submit trước khi chắc chắn xử lý được).
  if (form && window.fetch) {
    form.addEventListener("submit", function (e) {
      var code = (input.value || "").trim().toUpperCase();
      if (!code) return;
      e.preventDefault();
      // Đang chờ kết quả lần trước (nhấn Enter 2 lần) -> bỏ qua. Không có dòng
      // này thì mã bị gửi 2 lần và lần sau báo nhầm "Đã sử dụng".
      if (state === "BUSY") return;
      submitCode(code, false);
      input.value = "";
    });
    input.addEventListener("input", function () {
      input.value = input.value.toUpperCase();
    });
  }

  // ------------------------------------------------------------------ camera
  var canUseCamera = window.isSecureContext && navigator.mediaDevices &&
                     navigator.mediaDevices.getUserMedia;
  if (!canUseCamera) {
    if (btnCamera) btnCamera.hidden = true;
    if (cameraNote) {
      cameraNote.hidden = false;
      cameraNote.textContent = "Camera cần kết nối HTTPS. Đang dùng chế độ nhập mã.";
    }
  }

  function setCameraButton(on) {
    btnCamera.replaceChildren(el("i", on ? "bi bi-camera-video-off" : "bi bi-camera"),
      document.createTextNode(on ? " Tắt camera" : " Bật camera quét QR"));
  }

  function pickDecoder() {
    if ("BarcodeDetector" in window) {
      return window.BarcodeDetector.getSupportedFormats().then(function (f) {
        if (f.indexOf("qr_code") >= 0) detector = new window.BarcodeDetector({ formats: ["qr_code"] });
      }).catch(function () {});
    }
    return Promise.resolve();
  }

  function decodeFrame() {
    if (detector) {
      return detector.detect(video).then(function (codes) {
        return codes.length ? codes[0].rawValue : null;
      }).catch(function () { return null; });
    }
    if (typeof window.jsQR !== "function") return Promise.resolve(null);
    // Thu nhỏ khung hình còn rộng tối đa 640px cho nhanh
    var scale = Math.min(1, 640 / (video.videoWidth || 640));
    var w = Math.round(video.videoWidth * scale), h = Math.round(video.videoHeight * scale);
    if (!w || !h) return Promise.resolve(null);
    canvasEl.width = w; canvasEl.height = h;
    ctx.drawImage(video, 0, 0, w, h);
    var img = ctx.getImageData(0, 0, w, h);
    var r = window.jsQR(img.data, w, h, { inversionAttempts: "dontInvert" });
    return Promise.resolve(r ? r.data : null);
  }

  function loop(ts) {
    if (!stream) return;
    requestAnimationFrame(loop);
    if (state !== "SCANNING" || ts - lastDecode < SCAN_EVERY_MS) return;
    if (video.readyState < video.HAVE_ENOUGH_DATA) return;
    lastDecode = ts;
    state = "BUSY";
    decodeFrame().then(function (raw) {
      if (!raw) { if (state === "BUSY") state = "SCANNING"; return; }
      var code = String(raw).trim().toUpperCase();
      var now = Date.now();
      if (code === lastCode && now - lastTime < DEDUPE_MS) { state = "SCANNING"; return; }
      lastCode = code; lastTime = now;
      if (!CODE_RE.test(code)) {
        // Hay gặp: đưa nhầm QR chuyển khoản, link Zalo... -> không gọi server
        renderResult("INVALID", "Đây không phải mã vé KMG Club.", null);
        feedback("INVALID");
        state = "SCANNING";
        return;
      }
      submitCode(code, true);
    });
  }

  function startCamera() {
    if (!audioCtx) {
      try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}
    }
    return pickDecoder().then(function () {
      return navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } }, audio: false
      });
    }).then(function (s) {
      stream = s;
      video.srcObject = s;
      video.setAttribute("playsinline", "");   // thiếu thì iPhone mở toàn màn hình
      video.muted = true;
      return video.play();
    }).then(function () {
      wantCamera = true;
      state = "SCANNING";
      cameraBox.hidden = false;
      setCameraButton(true);
      requestAnimationFrame(loop);
    }).catch(function (err) {
      stopCamera();
      var msg = "Không bật được camera.";
      if (err && err.name === "NotAllowedError")
        msg = "Bạn đã chặn quyền camera. Mở cài đặt trình duyệt để cho phép.";
      else if (err && err.name === "NotFoundError") msg = "Không tìm thấy camera.";
      cameraNote.hidden = false;
      cameraNote.textContent = msg + " Bạn vẫn có thể nhập mã bên dưới.";
    });
  }

  function stopCamera() {
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
    state = "IDLE";
    if (cameraBox) cameraBox.hidden = true;
    if (btnCamera) setCameraButton(false);
  }

  if (btnCamera && canUseCamera) {
    btnCamera.addEventListener("click", function () {
      if (stream) { wantCamera = false; stopCamera(); }
      else { cameraNote.hidden = true; startCamera(); }
    });
  }

  // ------------------------------------------------ F5.4 tiến độ (polling 5s)
  var progressText = document.getElementById("progress-text");
  var progressBar = document.getElementById("progress-bar");
  var progressWrap = document.getElementById("progress-wrap");
  var byTypeBox = document.getElementById("progress-by-type");
  var recentBox = document.getElementById("recent-checkins");
  var pollTimer = null;

  function renderProgress(d) {
    progressText.textContent = d.done + " / " + d.total;
    progressBar.style.width = d.percent + "%";
    progressWrap.setAttribute("aria-valuenow", d.percent);
    if (byTypeBox && d.by_type) {
      byTypeBox.replaceChildren.apply(byTypeBox, d.by_type.map(function (t) {
        var row = el("div", "d-flex justify-content-between small");
        row.appendChild(el("span", "text-truncate me-2", t.name));
        row.appendChild(el("span", "fw-semibold", t.done + "/" + t.total));
        return row;
      }));
    }
    if (recentBox && d.recent) {
      if (!d.recent.length) {
        recentBox.replaceChildren(el("li", "list-group-item text-muted small", "Chưa có ai check-in."));
      } else {
        recentBox.replaceChildren.apply(recentBox, d.recent.map(function (r) {
          var li = el("li", "list-group-item d-flex justify-content-between small");
          li.appendChild(el("span", "text-truncate me-2", r.name));
          li.appendChild(el("span", "text-muted", r.at));
          return li;
        }));
      }
    }
  }

  function refreshProgress() {
    if (document.hidden) return;
    fetch(progressUrl, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) renderProgress(d); })
      .catch(function () {});
  }

  function startPolling() {
    if (!pollTimer) pollTimer = setInterval(refreshProgress, 5000);
  }
  function stopPolling() {
    clearInterval(pollTimer); pollTimer = null;
  }

  // Tab ẩn: tắt camera (tắt đèn) + ngừng polling. Hiện lại: bật lại nếu trước đó đang bật.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
      if (stream) { var keep = wantCamera; stopCamera(); wantCamera = keep; }
    } else {
      refreshProgress();
      startPolling();
      if (wantCamera && !stream) startCamera();
    }
  });
  window.addEventListener("pagehide", function () { stopCamera(); });

  startPolling();
  if (input) setTimeout(function () { input.focus(); }, 100);
})();
