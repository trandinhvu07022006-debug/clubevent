/*
 * Đổi cảnh nền + màu giao diện đồng bộ.
 * Không thư viện, không CDN — chỉ lật class .scene-0 / .scene-1 trên <body>.
 * Toàn bộ ảnh nền và bảng màu từng cảnh được định nghĩa trong app.css.
 */
(function () {
  "use strict";

  var images = [
    "scene-sunset.jpg",
    "scene-dawn.jpg",
    "scene-2.jpg",
    "scene-3.jpg",
    "scene-4.jpg"
  ];
  var SCENES = 5;          // 5 cảnh nền
  var INTERVAL = 40000;    // mỗi cảnh hiện ~40 giây rồi chuyển
  var body = document.body;
  var current = 0;

  var layers = [];
  var bgContainer = document.createElement("div");
  bgContainer.className = "scene-bg-container";
  for (var i = 0; i < SCENES; i++) {
    var layer = document.createElement("div");
    layer.className = "scene-layer";
    layer.style.backgroundImage = 'linear-gradient(var(--app-bg-overlay), var(--app-bg-overlay)), url("/static/img/' + images[i] + '")';
    bgContainer.appendChild(layer);
    layers.push(layer);
  }
  document.body.prepend(bgContainer);

  function show(n) {
    for (var k = 0; k < SCENES; k++) {
      body.classList.remove("scene-" + k);
      layers[k].style.opacity = 0;
      layers[k].classList.remove("active");   // chỉ lớp đang hiện mới chạy animation -> đỡ giật
    }
    body.classList.add("scene-" + n);
    layers[n].style.opacity = 1;
    layers[n].classList.add("active");
  }

  show(0);

  // Người dùng tắt hiệu ứng chuyển động thì đứng yên ở cảnh đầu.
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (!reduce.matches) {
    setInterval(function () {
      current = (current + 1) % SCENES;
      show(current);
    }, INTERVAL);
  }
})();
