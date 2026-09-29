/*
 * Biểu đồ thống kê, vẽ bằng Chart.js (tải từ static/, không dùng CDN).
 *
 * Cách hoạt động: Django render dữ liệu ra thẻ <script type="application/json">
 * bằng filter |json_script, file này đọc lên rồi vẽ. Làm vậy an toàn hơn nhúng
 * dữ liệu trực tiếp vào JavaScript, vì tránh được lỗ hổng XSS khi tên sự kiện
 * có chứa ký tự đặc biệt hoặc thẻ HTML.
 *
 * Mỗi biểu đồ đều có BẢNG SỐ đi kèm ngay trên cùng trang. Biểu đồ để nhìn
 * nhanh, bảng để đọc số chính xác và để người dùng trình đọc màn hình
 * (screen reader) vẫn tiếp cận được dữ liệu.
 */

// Bảng màu. Dùng MỘT tông xanh với các độ đậm khác nhau, không dùng nhiều màu
// sặc sỡ: khi so sánh độ lớn thì "đậm hơn = nhiều hơn" dễ đọc và vẫn phân biệt
// được với người bị mù màu (color blindness).
const VIZ = {
    surface: "#ffffff",   // màu nền thẻ card, dùng làm khe hở giữa các đoạn
    ink: "#0b0b0b",
    inkSoft: "#52514e",
    muted: "#898781",     // màu chữ nhãn trục
    grid: "#e1e0d9",      // đường kẻ mờ
    axis: "#c3c2b7",
    blue150: "#b7d3f6",
    blue250: "#86b6ef",
    blue350: "#5598e7",
    blue450: "#2a78d6",
    blue550: "#1c5cab",
    blue650: "#104281",
};

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

// Độ dày tối đa của một thanh. Không đặt thì Chart.js kéo giãn thanh cho đầy
// khung, ra những khối màu to đùng nhìn rất thô khi chỉ có vài dòng dữ liệu.
const BAR_MAX = 28;

/** Đọc dữ liệu JSON mà Django đã render ra thẻ script. */
function readData(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    try {
        return JSON.parse(el.textContent);
    } catch (e) {
        console.warn("Không đọc được dữ liệu biểu đồ:", id, e);
        return null;
    }
}

/** Cấu hình dùng chung: chữ nhỏ, kẻ mờ, không animation dài. */
function baseOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        font: { family: FONT },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: VIZ.ink,
                titleFont: { family: FONT, size: 13 },
                bodyFont: { family: FONT, size: 13 },
                padding: 10,
                displayColors: true,
                usePointStyle: true,
            },
        },
    };
}

/** Kiểu chung cho trục có số. */
function valueAxis(extra) {
    return Object.assign({
        beginAtZero: true,
        grid: { color: VIZ.grid, drawTicks: false },
        border: { color: VIZ.axis },
        ticks: { color: VIZ.muted, font: { family: FONT, size: 11 } },
    }, extra || {});
}

/** Kiểu chung cho trục nhãn chữ: bỏ đường kẻ cho đỡ rối. */
function labelAxis(extra) {
    return Object.assign({
        grid: { display: false },
        border: { color: VIZ.axis },
        ticks: { color: VIZ.inkSoft, font: { family: FONT, size: 12 } },
    }, extra || {});
}

/* ------------------------------------------------------------------ */
/* Biểu đồ 1: Check-in theo sự kiện (thanh ngang xếp chồng)            */
/* ------------------------------------------------------------------ */
function drawCheckinChart() {
    const canvas = document.getElementById("chart-checkin");
    const data = readData("data-checkin");
    if (!canvas || !data || !data.labels.length) return;

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: "Đã check-in",
                    data: data.checked,
                    backgroundColor: VIZ.blue450,
                    maxBarThickness: BAR_MAX,
                    borderRadius: 4,
                    // Viền cùng màu nền tạo khe hở 2px giữa 2 đoạn, nhìn rõ
                    // ranh giới mà không phải vẽ đường kẻ quanh thanh.
                    borderColor: VIZ.surface,
                    borderWidth: { right: 2 },
                    borderSkipped: false,
                },
                {
                    label: "Chưa check-in",
                    data: data.remaining,
                    backgroundColor: VIZ.blue150,
                    maxBarThickness: BAR_MAX,
                    borderRadius: 4,
                    borderSkipped: false,
                },
            ],
        },
        options: Object.assign(baseOptions(), {
            indexAxis: "y",   // thanh NGANG, vì tên sự kiện tiếng Việt khá dài
            scales: {
                x: valueAxis({ stacked: true, title: {
                    display: true, text: "Số vé", color: VIZ.muted,
                    font: { family: FONT, size: 11 } } }),
                y: labelAxis({ stacked: true }),
            },
            plugins: Object.assign(baseOptions().plugins, {
                // 2 nhóm dữ liệu nên bắt buộc có chú giải, không để màu tự nói
                legend: {
                    display: true,
                    position: "bottom",
                    labels: { color: VIZ.inkSoft, boxWidth: 10, boxHeight: 10,
                              usePointStyle: true, pointStyle: "rectRounded",
                              font: { family: FONT, size: 12 } },
                },
                tooltip: Object.assign(baseOptions().plugins.tooltip, {
                    callbacks: {
                        footer: (items) => {
                            const i = items[0].dataIndex;
                            const total = data.checked[i] + data.remaining[i];
                            if (!total) return "";
                            const pct = Math.round(data.checked[i] * 100 / total);
                            return `Tổng ${total} vé · tỉ lệ check-in ${pct}%`;
                        },
                    },
                }),
            }),
        }),
    });
}

/* ------------------------------------------------------------------ */
/* Biểu đồ 2: Điểm đánh giá trung bình theo sự kiện                    */
/* ------------------------------------------------------------------ */
function drawEventRatingChart() {
    const canvas = document.getElementById("chart-rating-events");
    const data = readData("data-rating-events");
    if (!canvas || !data || !data.labels.length) return;

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: data.labels,
            // Một nhóm dữ liệu thì dùng MỘT màu cho mọi thanh. Không tô thanh
            // cao màu đậm hơn, vì độ dài thanh đã nói lên độ lớn rồi.
            datasets: [{
                label: "Điểm trung bình",
                data: data.values,
                backgroundColor: VIZ.blue450,
                maxBarThickness: BAR_MAX,
                borderRadius: 4,
                borderSkipped: false,
            }],
        },
        options: Object.assign(baseOptions(), {
            indexAxis: "y",
            scales: {
                x: valueAxis({ max: 5, ticks: {
                    color: VIZ.muted, stepSize: 1,
                    font: { family: FONT, size: 11 } } }),
                y: labelAxis(),
            },
            plugins: Object.assign(baseOptions().plugins, {
                tooltip: Object.assign(baseOptions().plugins.tooltip, {
                    callbacks: {
                        label: (item) => `${item.parsed.x} / 5 sao`,
                        footer: (items) => {
                            const n = data.counts[items[0].dataIndex];
                            return `dựa trên ${n} đánh giá`;
                        },
                    },
                }),
            }),
        }),
    });
}

/* ------------------------------------------------------------------ */
/* Biểu đồ 3: Số vé theo loại vé                                       */
/* ------------------------------------------------------------------ */
function drawTicketTypeChart() {
    const canvas = document.getElementById("chart-by-type");
    const data = readData("data-by-type");
    if (!canvas || !data || !data.labels.length) return;

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: data.labels,
            datasets: [{
                label: "Số vé",
                data: data.values,
                backgroundColor: VIZ.blue450,
                maxBarThickness: BAR_MAX,
                borderRadius: 4,
                borderSkipped: false,
            }],
        },
        options: Object.assign(baseOptions(), {
            indexAxis: "y",
            scales: { x: valueAxis({ ticks: {
                color: VIZ.muted, precision: 0,
                font: { family: FONT, size: 11 } } }), y: labelAxis() },
            plugins: Object.assign(baseOptions().plugins, {
                tooltip: Object.assign(baseOptions().plugins.tooltip, {
                    callbacks: { label: (item) => `${item.parsed.x} vé` },
                }),
            }),
        }),
    });
}

/* ------------------------------------------------------------------ */
/* Biểu đồ 4: Phân bố số sao                                           */
/* ------------------------------------------------------------------ */
function drawRatingDistChart() {
    const canvas = document.getElementById("chart-rating-dist");
    const data = readData("data-rating-dist");
    if (!canvas || !data) return;
    if (!data.counts.some((n) => n > 0)) return;   // chưa có đánh giá thì bỏ qua

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: ["1 sao", "2 sao", "3 sao", "4 sao", "5 sao"],
            datasets: [{
                label: "Số đánh giá",
                // 1 đến 5 sao là thang CÓ THỨ TỰ, nên dùng dải màu đậm dần.
                // Khác với danh mục không có thứ tự (loại vé, tên sự kiện) —
                // chỗ đó phải dùng một màu duy nhất.
                data: data.counts,
                backgroundColor: [VIZ.blue250, VIZ.blue350, VIZ.blue450,
                                  VIZ.blue550, VIZ.blue650],
                maxBarThickness: 56,
                borderRadius: 4,
                borderSkipped: false,
            }],
        },
        options: Object.assign(baseOptions(), {
            scales: {
                y: valueAxis({ ticks: {
                    color: VIZ.muted, precision: 0,
                    font: { family: FONT, size: 11 } } }),
                x: labelAxis(),
            },
            plugins: Object.assign(baseOptions().plugins, {
                tooltip: Object.assign(baseOptions().plugins.tooltip, {
                    callbacks: { label: (item) => `${item.parsed.y} người chọn` },
                }),
            }),
        }),
    });
}

/* ------------------------------------------------------------------ */
// Chỉ vẽ biểu đồ nào có canvas tương ứng trên trang, nên file này dùng chung
// được cho mọi trang mà không báo lỗi.
document.addEventListener("DOMContentLoaded", function () {
    if (typeof Chart === "undefined") {
        console.warn("Chưa tải được Chart.js, bỏ qua phần biểu đồ.");
        return;
    }
    Chart.defaults.font.family = FONT;
    Chart.defaults.color = VIZ.inkSoft;

    drawCheckinChart();
    drawEventRatingChart();
    drawTicketTypeChart();
    drawRatingDistChart();
});
