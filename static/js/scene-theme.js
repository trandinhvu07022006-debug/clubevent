/*
 * Đổi cảnh nền + màu giao diện đồng bộ.
 * Không thư viện, không CDN — chỉ lật class .scene-0 / .scene-1 trên <body>.
 * Toàn bộ ảnh nền và bảng màu từng cảnh được định nghĩa trong app.css.
 */
(function () {
  "use strict";

  var SCENES = 2;          // scene-0 = hoàng hôn, scene-1 = bình minh
  var INTERVAL = 14000;    // mỗi cảnh hiện ~14 giây rồi chuyển
  var body = document.body;
  var current = 0;

  function show(n) {
    for (var k = 0; k < SCENES; k++) body.classList.remove("scene-" + k);
    body.classList.add("scene-" + n);
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
