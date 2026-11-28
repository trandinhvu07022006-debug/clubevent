"""Playwright end-to-end UI, responsive, theme, and asset audit on isolated staging.

Run inside CI (or an approved isolated staging environment):
    python deployment/playwright_ui_audit.py --base-url http://127.0.0.1:18080 --out-dir /tmp/pw-report
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

VIEWPORTS: tuple[tuple[int, int], ...] = (
    (320, 640),
    (360, 740),
    (390, 844),
    (768, 1024),
    (1024, 768),
    (1440, 900),
    (1920, 1080),
)
SCREENSHOT_WIDTHS = {320, 390, 768, 1440, 1920}


@dataclass
class PageAuditResult:
    role: str
    path: str
    theme: str
    viewport: str
    status: int
    scroll_width: int
    inner_width: int
    overflow_px: int
    offenders: list[str] = field(default_factory=list)
    zero_box_svgs: int = 0
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    failed_assets: list[str] = field(default_factory=list)


def _login_user(page: Page, base_url: str, username: str, password: str) -> None:
    page.goto(f"{base_url}/taikhoan/dangnhap/", wait_until="networkidle")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    with page.expect_navigation(wait_until="networkidle"):
        page.click('form[method="post"] button[type="submit"], form[method="post"] button.btn-primary')


def _set_theme(page: Page, theme: str) -> None:
    page.evaluate(
        """(t) => {
            try { localStorage.setItem("theme", t); } catch (e) {}
            document.documentElement.setAttribute("data-bs-theme", t);
        }""",
        theme,
    )


def _inspect_page(
    context: BrowserContext,
    base_url: str,
    role: str,
    path: str,
    theme: str,
    width: int,
    height: int,
    out_dir: Path,
    capture_shot: bool,
) -> PageAuditResult:
    page = context.new_page()
    page.set_viewport_size({"width": width, "height": height})
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_assets: list[str] = []

    def on_console(msg) -> None:
        if msg.type == "error":
            console_errors.append(msg.text[:300])

    def on_page_error(exc) -> None:
        page_errors.append(str(exc)[:300])

    def on_response(resp) -> None:
        if "/static/" in resp.url and resp.status >= 400:
            failed_assets.append(f"{resp.status} {resp.url}")

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)

    page.add_init_script(
        f'try {{ localStorage.setItem("theme", "{theme}"); }} catch (e) {{}}'
        f'document.documentElement.setAttribute("data-bs-theme", "{theme}");'
    )
    resp = page.goto(f"{base_url}{path}", wait_until="networkidle")
    _set_theme(page, theme)
    page.wait_for_timeout(120)

    metrics = page.evaluate(
        """() => {
            const vw = window.innerWidth;
            const sw = document.documentElement.scrollWidth;
            const offenders = [];
            if (sw > vw) {
                for (const el of document.querySelectorAll("body *")) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.right > vw + 1) {
                        const cls = (el.className && typeof el.className === "string")
                            ? "." + el.className.trim().split(/\\s+/).slice(0, 2).join(".")
                            : "";
                        offenders.push(`${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${cls} (right=${Math.round(r.right)}, vw=${vw})`);
                        if (offenders.length >= 6) break;
                    }
                }
            }
            let zeroSvgs = 0;
            for (const svg of document.querySelectorAll("svg.kmg-icon")) {
                const r = svg.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) zeroSvgs++;
            }
            return { vw, sw, overflow: Math.max(0, sw - vw), offenders, zeroSvgs };
        }"""
    )

    if capture_shot and width in SCREENSHOT_WIDTHS:
        safe_slug = path.strip("/").replace("/", "_") or "home"
        shot_path = out_dir / "screenshots" / f"{role}__{safe_slug}__{theme}__{width}.png"
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot_path), full_page=False)

    page.close()
    return PageAuditResult(
        role=role,
        path=path,
        theme=theme,
        viewport=f"{width}x{height}",
        status=resp.status if resp else 0,
        scroll_width=metrics["sw"],
        inner_width=metrics["vw"],
        overflow_px=metrics["overflow"],
        offenders=metrics["offenders"],
        zero_box_svgs=metrics["zeroSvgs"],
        console_errors=console_errors,
        page_errors=page_errors,
        failed_assets=failed_assets,
    )


def _run_functional_flows(browser: Browser, base_url: str, password: str) -> list[str]:
    notes: list[str] = []

    # 1. Guest AI Chat + clean 404
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{base_url}/troly/", wait_until="networkidle")
    page.fill("#chat-input", "KMG là gì?")
    page.click('#chat-form button[type="submit"]')
    page.wait_for_function(
        "() => document.querySelectorAll('#chat-log .chat-msg').length >= 3",
        timeout=15000,
    )
    notes.append("Guest /troly/ chat reply rendered cleanly.")

    resp_404 = page.goto(f"{base_url}/duong-dan-khong-ton-tai-playwright-404/", wait_until="networkidle")
    assert resp_404 and resp_404.status == 404, f"Expected 404, got {resp_404 and resp_404.status}"
    assert "Traceback" not in page.content(), "404 page leaked Python traceback"
    notes.append("Guest 404 page cleanly rendered without Traceback.")
    ctx.close()

    # 2. Mobile drawer toggle check at 360px
    ctx_mob = browser.new_context(viewport={"width": 360, "height": 740})
    page_mob = ctx_mob.new_page()
    _login_user(page_mob, base_url, "thanhvien_daban", password)
    page_mob.goto(f"{base_url}/tong-quan/", wait_until="networkidle")
    toggler = page_mob.locator('button[data-bs-toggle="offcanvas"][data-bs-target="#appSidebar"]')
    assert toggler.is_visible(), "Mobile sidebar toggler should be visible at 360px"
    toggler.click()
    page_mob.wait_for_timeout(300)
    assert "show" in (page_mob.locator("#appSidebar").get_attribute("class") or ""), "Mobile offcanvas sidebar did not open"
    notes.append("Member mobile sidebar drawer opened at 360px.")
    ctx_mob.close()

    # 3. Advisor read-only redirect & UI isolation check
    ctx_adv = browser.new_context()
    page_adv = ctx_adv.new_page()
    _login_user(page_adv, base_url, "covan", password)
    page_adv.goto(f"{base_url}/workspace/", wait_until="networkidle")
    assert "/workspace/giam-sat/" in page_adv.url, f"Advisor not redirected to advisor_overview: {page_adv.url}"
    page_adv.goto(f"{base_url}/workspace/tai-chinh/", wait_until="networkidle")
    adv_html = page_adv.content()
    assert "Chế độ Cố vấn — chỉ xem báo cáo tổng hợp." in adv_html
    assert 'value="create_transaction"' not in adv_html, "Advisor UI must not expose transaction create form"
    notes.append("Advisor redirected to /workspace/giam-sat/ and finance hub strictly read-only.")
    ctx_adv.close()

    return notes


def run_audit(base_url: str, out_dir: Path, password: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[PageAuditResult] = []
    flow_notes: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            flow_notes = _run_functional_flows(browser, base_url, password)

            role_routes: dict[str, tuple[str | None, Iterable[str]]] = {
                "guest": (None, ("/", "/sukien/", "/congban/", "/troly/")),
                "member": ("thanhvien_daban", ("/tong-quan/", "/workspace/", "/troly/")),
                "dept_head": ("truongban_cm", ("/workspace/", "/congviec/viec-cua-toi/")),
                "chairman": ("chunhiem", ("/workspace/quan-tri/", "/workspace/tai-chinh/", "/troly/huan-luyen/")),
                "admin": ("admin", ("/dev/design-system/",)),
            }

            for role, (username, paths) in role_routes.items():
                ctx = browser.new_context()
                if username:
                    login_page = ctx.new_page()
                    _login_user(login_page, base_url, username, password)
                    login_page.close()

                for path in paths:
                    for theme in ("light", "dark"):
                        for width, height in VIEWPORTS:
                            capture = theme in ("light", "dark") and width in SCREENSHOT_WIDTHS and path in (
                                "/",
                                "/tong-quan/",
                                "/workspace/",
                                "/workspace/tai-chinh/",
                                "/troly/",
                                "/dev/design-system/",
                            )
                            res = _inspect_page(
                                ctx, base_url, role, path, theme, width, height, out_dir, capture
                            )
                            results.append(res)
                ctx.close()
        finally:
            browser.close()

    hard_failures = [
        r
        for r in results
        if r.status >= 500 or r.status == 0 or r.page_errors or r.console_errors or r.failed_assets
    ]
    overflows = [r for r in results if r.overflow_px > 2]
    zero_svgs = [r for r in results if r.zero_box_svgs > 0]

    report_payload = {
        "total_checks": len(results),
        "hard_failures_count": len(hard_failures),
        "overflows_gt_2px_count": len(overflows),
        "zero_box_svg_count": len(zero_svgs),
        "flow_notes": flow_notes,
        "hard_failures": [asdict(r) for r in hard_failures],
        "overflows": [asdict(r) for r in overflows],
        "results": [asdict(r) for r in results],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_lines = [
        "# Playwright Staging UI Audit Summary",
        f"- Total viewport/theme/page checks: {len(results)}",
        f"- Hard failures (HTTP>=500, JS error, console.error, missing /static/): {len(hard_failures)}",
        f"- Horizontal overflows (>2px): {len(overflows)}",
        f"- Zero-box SVGs: {len(zero_svgs)}",
        "",
        "## Functional Flows",
        *[f"- {note}" for note in flow_notes],
    ]
    if overflows:
        summary_lines.append("")
        summary_lines.append("## Detected Overflows (>2px)")
        for r in overflows:
            summary_lines.append(
                f"- [{r.role}] `{r.path}` ({r.theme}, {r.viewport}): +{r.overflow_px}px -> {r.offenders}"
            )
    if hard_failures:
        summary_lines.append("")
        summary_lines.append("## Hard Failures")
        for r in hard_failures:
            summary_lines.append(
                f"- [{r.role}] `{r.path}` ({r.theme}, {r.viewport}): status={r.status}, page_err={r.page_errors}, console={r.console_errors}, assets={r.failed_assets}"
            )

    summary_text = "\n".join(summary_lines)
    (out_dir / "SUMMARY.md").write_text(summary_text + "\n", encoding="utf-8")
    print(summary_text)
    return 1 if hard_failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Playwright UI audit against KMG staging server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--out-dir", default="playwright-report")
    parser.add_argument("--password", default="Kmg@2026!")
    args = parser.parse_args()
    return run_audit(args.base_url.rstrip("/"), Path(args.out_dir), args.password)


if __name__ == "__main__":
    raise SystemExit(main())
