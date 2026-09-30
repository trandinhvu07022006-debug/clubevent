const video = document.getElementById("qr-video");
const canvasElement = document.getElementById("qr-canvas");
const canvas = canvasElement.getContext("2d", { willReadFrequently: true });
const btnCamera = document.getElementById("btn-camera");
const resultDiv = document.getElementById("scan-result");
const inputCode = document.getElementById("code-input");
let scanning = false;
let stream = null;

if (btnCamera) {
    btnCamera.addEventListener("click", () => {
        if (scanning) {
            stopScan();
            btnCamera.innerHTML = '<i class="bi bi-camera"></i> Mở camera';
            video.style.display = "none";
        } else {
            startScan();
            btnCamera.innerHTML = '<i class="bi bi-camera-video-off"></i> Tắt camera';
            video.style.display = "block";
        }
    });
}

function startScan() {
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function(s) {
        stream = s;
        video.srcObject = stream;
        video.setAttribute("playsinline", true);
        video.play();
        scanning = true;
        requestAnimationFrame(tick);
    }).catch(err => {
        alert("Không thể mở camera: " + err);
    });
}

function stopScan() {
    scanning = false;
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
    }
}

function tick() {
    if (!scanning) return;
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
        canvasElement.height = video.videoHeight;
        canvasElement.width = video.videoWidth;
        canvas.drawImage(video, 0, 0, canvasElement.width, canvasElement.height);
        var imageData = canvas.getImageData(0, 0, canvasElement.width, canvasElement.height);
        var code = jsQR(imageData.data, imageData.width, imageData.height, {
            inversionAttempts: "dontInvert",
        });
        if (code) {
            stopScan();
            btnCamera.innerHTML = '<i class="bi bi-camera"></i> Mở camera';
            video.style.display = "none";
            inputCode.value = code.data;
            submitScan(code.data);
            return;
        }
    }
    requestAnimationFrame(tick);
}

function submitScan(code) {
    const eventId = document.getElementById("event-id").value;
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    
    fetch(`/ve/checkin/${eventId}/quet/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({ code: code })
    })
    .then(res => res.json())
    .then(data => {
        renderResult(data);
        updateProgress();
        // Resume after 2s
        setTimeout(() => {
            if (!scanning && btnCamera) {
                startScan();
                btnCamera.innerHTML = '<i class="bi bi-camera-video-off"></i> Tắt camera';
                video.style.display = "block";
            }
        }, 2000);
    })
    .catch(err => {
        console.error(err);
        alert("Lỗi kết nối");
    });
}

function renderResult(data) {
    let icon = "";
    if (data.result === 'OK') icon = '<i class="bi bi-check-circle-fill"></i> HỢP LỆ';
    else if (data.result === 'USED') icon = '<i class="bi bi-exclamation-triangle-fill"></i> ĐÃ SỬ DỤNG';
    else icon = '<i class="bi bi-x-circle-fill"></i> KHÔNG HỢP LỆ';
    
    let ticketHtml = "";
    if (data.ticket) {
        ticketHtml = `
            <div class="bg-body bg-opacity-50 p-3 rounded-3 text-start">
              <div class="text-muted small mb-1">Mã vé</div>
              <div class="checkin-code fs-4 mb-3">${data.ticket.code}</div>
              <hr class="my-2 border-secondary opacity-25">
              <div class="fw-bold fs-5">${data.ticket.user_name}</div>
              <span class="badge bg-secondary px-3 py-2 fs-6">${data.ticket.ticket_type}</span>
            </div>
        `;
    }

    resultDiv.innerHTML = `
        <div class="card shadow-sm mb-4 border-0 text-center checkin-result bg-${data.css_class}-subtle text-${data.css_class}-emphasis">
            <div class="card-body p-4">
              <h2 class="fw-bold mb-2 checkin-verdict">${icon}</h2>
              <div class="fs-5 mb-3">${data.note}</div>
              ${ticketHtml}
            </div>
        </div>
    `;
}

function updateProgress() {
    const eventId = document.getElementById("event-id").value;
    fetch(`/ve/checkin/${eventId}/tiendo/`)
    .then(res => res.json())
    .then(data => {
        document.getElementById("progress-text").textContent = `${data.done} / ${data.total}`;
        document.getElementById("progress-bar").style.width = `${data.percent}%`;
    });
}

setInterval(updateProgress, 5000);
