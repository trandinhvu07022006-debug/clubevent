"""
Package dùng chung cho toàn dự án.

Chứa các tiện ích không thuộc riêng nghiệp vụ của một app nào (ví dụ:
phân trang). Trước đây `pagination` nằm trong app `accounts`, nhưng phân
trang không liên quan gì tới tài khoản mà app nào cũng dùng, nên gom về
đây cho đúng chỗ.

`core` cố ý KHÔNG phải một Django app (không có models, không đăng ký vào
INSTALLED_APPS) — nó chỉ là package tiện ích thuần Python.
"""
